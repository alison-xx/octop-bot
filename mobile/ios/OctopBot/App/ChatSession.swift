import Foundation
import Observation
import UIKit

/// One Bot's chat: its conversation list, the open conversation and its live reply.
@Observable
final class ChatSession {
    weak var app: AppModel?
    var bot: BotProfile
    private(set) var conversationId: String?
    var messages: [ChatMessage] = []
    var conversations: [ConversationSummary] = []
    private(set) var isStreaming = false
    private(set) var isLoading = false
    var error: String?
    /// The composer's unsent text; kept per Bot so leaving the chat doesn't lose it.
    var draft = ""
    /// Bumped to ask the composer to take focus (e.g. after "Edit").
    private(set) var focusRequest = 0
    private var task: Task<Void, Never>?
    /// A question or approval the Bot is waiting on.
    var pause: HitlPause?
    /// Device tools are running on this phone for the open pause.
    private(set) var isRunningDevice = false
    /// Messages written while a reply was streaming; sent in order when it ends.
    private(set) var queued: [ChatMessage] = []
    private weak var historyBackend: ChatBackend?
    private(set) var unsavedReplies: [String: LynxceBackend.HistorySaveError] = [:]
    private(set) var savingReplies: Set<String> = []
    private var currentRun: UUID?
    /// Called with the finished reply text (voice mode reads it aloud).
    var onReply: ((String) -> Void)?

    init(bot: BotProfile, app: AppModel) {
        self.bot = bot
        self.app = app
    }

    var motion: BotMotion {
        guard isStreaming, let last = messages.last, last.role == .assistant else { return .idle }
        if last.text.isEmpty { return last.thinking.isEmpty ? .working : .thinking }
        return .working
    }

    /// The open conversation's title, once the server has named it.
    var title: String? {
        guard let conversationId else { return nil }
        return conversations.first { $0.id == conversationId }?.title
    }

    /// Put a sent message back into the composer to edit and send again.
    func edit(_ message: ChatMessage) {
        draft = message.text
        focusRequest += 1
    }

    func newChat() {
        cancel()
        conversationId = nil
        messages = []
        pause = nil
        error = nil
    }

    func reloadConversations() async {
        guard let backend = app?.backend else { return }
        if let rows = try? await backend.conversations(for: bot) { conversations = rows }
    }

    func open(_ conversation: ConversationSummary) async {
        cancel()
        conversationId = conversation.id
        messages = []
        pause = nil
        error = nil
        guard let backend = app?.backend else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let loaded = try await backend.messages(in: conversation, bot: bot)
            if conversationId == conversation.id {
                messages = loaded
                pause = backend.openPause(in: conversation)
                runDeviceReads()
            }
        } catch {
            if conversationId == conversation.id { self.error = error.localizedDescription }
        }
    }

    func delete(_ conversation: ConversationSummary) async {
        conversations.removeAll { $0.id == conversation.id }
        if conversationId == conversation.id { newChat() }
        try? await app?.backend?.deleteConversation(conversation, bot: bot)
    }

    func send(_ text: String, images: [Data] = []) {
        guard bot.canSend else { return }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let backend = app?.backend, !trimmed.isEmpty || !images.isEmpty else { return }
        // Never block: while a reply streams, queue the message and send it when the reply ends.
        if isStreaming || isRunningDevice {
            queued.append(ChatMessage(role: .user, text: trimmed, images: images))
            return
        }
        // An open question takes the text as its answer; an open approval is declined with it as the reason.
        if let pause {
            if !trimmed.isEmpty {
                if pause.isQuestion { answer(pause, text: trimmed) } else { decide(pause, approve: false, reason: trimmed) }
                // Photos can't ride on an answer; they follow as the next message.
                if !images.isEmpty { queued.append(ChatMessage(role: .user, text: "", images: images)) }
                return
            }
            // Photos alone: close the pause and send them as a normal message.
            if pause.isQuestion { dismissQuestion(pause) } else { decide(pause, approve: false) }
            queued.append(ChatMessage(role: .user, text: "", images: images))
            return
        }
        if app?.notifyOnReply == true { Notifier.requestPermission() }
        let history = messages
        messages.append(ChatMessage(role: .user, text: trimmed, images: images))
        // A choice saved before Lynxce moved Octop Bot to its Tencent line falls back to the default.
        let model = app?.isLynxce == true
            ? app?.selectedModel.flatMap { $0.hasPrefix(LynxceBackend.modelPrefix) ? $0 : nil }
            : nil
        run(backend.send(trimmed, images: images, to: bot, conversation: conversationId, history: history, model: model))
    }

    /// Drop a queued message before it is sent.
    func unqueue(_ message: ChatMessage) {
        queued.removeAll { $0.id == message.id }
    }

    /// Send the next queued message once the current reply is over.
    private func sendQueued() {
        guard !isStreaming, !queued.isEmpty else { return }
        let next = queued.removeFirst()
        send(next.text, images: next.images)
    }

    /// Reply to an open question with text.
    func answer(_ pause: HitlPause, text: String) {
        resume(pause, decisions: pause.actions.map { _ in ["type": "respond", "message": text] }, echo: text)
    }

    /// Approve or reject an open approval.
    /// `reason` is the user's own message when they decline by just writing something else.
    func decide(_ pause: HitlPause, approve: Bool, reason: String? = nil) {
        let names = pause.actions.map(\.label).joined(separator: "、")
        let note = L(approve ? "hitl.approvedNote %@" : "hitl.rejectedNote %@", names)
        if approve, pause.hasDeviceActions {
            runDevice(pause, note: note)
            return
        }
        let decision: [String: Any] = approve
            ? ["type": "approve"]
            : ["type": "reject", "message": reason ?? L(pause.hasDeviceActions ? "device.declined" : "hitl.rejectedMessage")]
        resume(pause, decisions: pause.actions.map { _ in decision }, echo: reason, note: note)
    }

    /// Device tools that only read run as soon as the Bot asks; writes wait for the card.
    private func runDeviceReads() {
        guard let pause, pause.runsUnattended, !isStreaming else { return }
        runDevice(pause, note: nil)
    }

    /// Run the pause's device tools on this phone and answer with their results; other tools are approved.
    private func runDevice(_ pause: HitlPause, note: String?) {
        self.pause = nil
        isRunningDevice = true
        let conversation = conversationId
        Task {
            var decisions: [[String: Any]] = []
            for action in pause.actions {
                if action.isDevice {
                    decisions.append(["type": "respond", "message": await DeviceConnectors.shared.run(action.name, argsJSON: action.args)])
                } else {
                    decisions.append(["type": "approve"])
                }
            }
            isRunningDevice = false
            // The user may have left this conversation while the tools ran.
            guard conversationId == conversation, self.pause == nil else { return }
            resume(pause, decisions: decisions, note: note)
        }
    }

    /// Close an open question without answering.
    func dismissQuestion(_ pause: HitlPause) {
        resume(pause, decisions: pause.actions.map { _ in ["type": "respond", "message": L("hitl.ask.dismissMessage")] }, note: L("hitl.ask.dismissed"))
    }

    private func resume(_ pause: HitlPause, decisions: [[String: Any]], echo: String? = nil, note: String? = nil) {
        guard let backend = app?.backend, let conversationId, !isStreaming else { return }
        self.pause = nil
        if let note { messages.append(ChatMessage(role: .system, text: note)) }
        if let echo { messages.append(ChatMessage(role: .user, text: echo)) }
        run(backend.resume(pause, decisions: decisions, conversation: conversationId, bot: bot))
    }

    /// Stream one reply into a new assistant message.
    private func run(_ stream: AsyncThrowingStream<StreamEvent, Error>) {
        let bot = bot
        var reply = ChatMessage(role: .assistant, text: "", status: .streaming)
        reply.authorId = bot.id
        messages.append(reply)
        error = nil
        isStreaming = true
        let replyId = reply.id
        let backend = app?.backend
        let background = UIApplication.shared.beginBackgroundTask(withName: "reply")
        // A cancelled earlier reply must not touch the state of this one.
        let run = UUID()
        currentRun = run
        task = Task {
            defer {
                if currentRun == run { isStreaming = false }
                // Nothing keeps spinning once the reply is over.
                update(replyId) { message in
                    for index in message.tools.indices { message.tools[index].done = true }
                }
                UIApplication.shared.endBackgroundTask(background)
            }
            do {
                for try await event in stream {
                    apply(event, to: replyId)
                }
                update(replyId) { $0.status = .done }
                removeEmptyReply(replyId)
                // Paused only for device reads: the phone answers by itself and the reply goes on.
                if pause?.runsUnattended != true {
                    let text = messages.first { $0.id == replyId }?.text ?? ""
                    let summary = text.isEmpty ? (pause?.questions.first?.question ?? pause.map { _ in L("hitl.title") } ?? "") : text
                    app?.recordPreview(summary, for: bot)
                    if app?.notifyOnReply == true, !summary.isEmpty { Notifier.replyFinished(bot: bot.name, text: summary) }
                    if let onReply {
                        onReply(text)
                    } else if app?.readAloud == true, !text.isEmpty {
                        Speaker.shared.speak(text, backend: backend, id: replyId)
                    }
                    await reloadConversations()
                }
                // Each reply spends credits; keep the balance (and the low-balance banner) current.
                Task { await self.app?.refreshBalance() }
            } catch is CancellationError {
                update(replyId) { $0.status = .done }
                removeEmptyReply(replyId)
            } catch let failure as LynxceBackend.HistorySaveError {
                guard currentRun == run, app?.backend === backend else { return }
                historyBackend = backend
                unsavedReplies[replyId] = failure
                update(replyId) { $0.status = .failed(failure.localizedDescription) }
            } catch let error as APIError where error.kind == .credits {
                // Out of credits: the reply becomes a top-up card with "Continue" instead of an error.
                update(replyId) {
                    $0.status = .outOfCredits
                    $0.creditScenario = creditScenario(code: error.code, details: error.details)
                }
                Task { await self.app?.refreshBalance() }
            } catch let error as APIError where error.kind == .dailyLimit {
                // Credits are left but today's cap is used up: a card that says when it resets.
                update(replyId) { $0.status = .dailyLimit }
            } catch {
                let message = error.localizedDescription
                update(replyId) { $0.status = .failed(message) }
                if case .unauthorized = (error as? APIError)?.kind { Task { await self.app?.signOut() } }
            }
            guard currentRun == run else { return }
            isStreaming = false
            runDeviceReads()
            sendQueued()
        }
    }

    private func apply(_ event: StreamEvent, to id: String) {
        switch event {
        case .conversation(let created):
            conversationId = created
        case .text(let delta):
            update(id) { $0.text += delta }
        case .thinking(let delta):
            update(id) { $0.thinking += delta }
        case .tool(let toolId, let name, let done):
            update(id) { message in
                if let index = message.tools.firstIndex(where: { $0.id == toolId }) {
                    message.tools[index].done = done
                } else {
                    message.tools.append(ToolStep(id: toolId, name: name, done: done))
                }
            }
        case .attachment(let file):
            update(id) { message in
                if !message.attachments.contains(where: { $0.url == file.url }) { message.attachments.append(file) }
            }
        case .pause(let pause):
            self.pause = pause
        case .done:
            break
        }
    }

    private func update(_ id: String, _ change: (inout ChatMessage) -> Void) {
        guard let index = messages.lastIndex(where: { $0.id == id }) else { return }
        change(&messages[index])
    }

    private func removeEmptyReply(_ id: String) {
        messages.removeAll { $0.id == id && $0.text.isEmpty && $0.tools.isEmpty && $0.thinking.isEmpty && $0.attachments.isEmpty }
    }

    func retrySaving(_ id: String) async {
        guard let historyBackend, historyBackend === app?.backend,
              let failure = unsavedReplies[id], savingReplies.insert(id).inserted else { return }
        defer { savingReplies.remove(id) }
        do {
            try await failure.retry()
            guard historyBackend === app?.backend, unsavedReplies.removeValue(forKey: id) != nil else { return }
            update(id) { $0.status = .done }
            await reloadConversations()
        } catch {
            // Leave the reply and its original payload available for the next save attempt.
        }
    }

    func stop() {
        guard isStreaming, let backend = app?.backend else { return }
        if let conversationId { Task { await backend.stop(conversation: conversationId, bot: bot) } }
        task?.cancel()
    }

    func cancel() {
        unsavedReplies.removeAll()
        queued = []
        currentRun = nil
        task?.cancel()
        task = nil
        isStreaming = false
    }

    /// Re-ask the last question after a failed or unwanted reply.
    func retry() {
        guard !isStreaming, pause == nil, let lastUser = messages.lastIndex(where: { $0.role == .user }) else { return }
        let question = messages[lastUser]
        messages.removeSubrange(lastUser...)
        send(question.text, images: question.images)
    }
}
