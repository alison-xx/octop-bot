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
    private var historyRows: [[String: Any]] = []
    private(set) var older: ServerBackend.HistoryPosition?
    private(set) var loadingOlder = false
    private var historyRevision = 0
    private var visited = false
    /// Uncommitted rows on a subscribed turn survive a socket or foreground reconciliation.
    struct ObservedTurn {
        var id: String?
        var anchor: ChatMessage?
        var rows: [ChatMessage] = []
        var ended = false

        func committedTail(_ history: [ChatMessage]) -> ArraySlice<ChatMessage> {
            guard let anchor else { return history[...] }
            let position = history.lastIndex { $0.id == anchor.id }
                ?? history.lastIndex { $0.role == anchor.role && $0.text == anchor.text }
            guard let position else { return history[history.endIndex...] }
            return history.suffix(from: position + 1)
        }

        func merged(_ history: [ChatMessage]) -> [ChatMessage] {
            let tail = committedTail(history)
            return history + rows.filter { row in
                !tail.contains { $0.id == row.id || ($0.role == row.role && $0.text == row.text) }
            }
        }
    }

    private var observedTurn: ObservedTurn?
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
        visited = true
        historyRevision += 1
        historyRows = []
        older = nil
        isLoading = false
        observedTurn = nil
        conversationId = nil
        messages = []
        pause = nil
        error = nil
    }

    func reloadConversations() async {
        guard let backend = app?.backend else { return }
        if let rows = try? await backend.conversations(for: bot) { conversations = rows }
    }

    /// Restore the latest server thread on the first visit; keep an explicitly empty new chat.
    func showConversation() async {
        let first = !visited
        visited = true
        let revision = historyRevision
        await reloadConversations()
        guard revision == historyRevision, !isStreaming, !isLoading else { return }
        if let id = conversationId, let row = conversations.first(where: { $0.id == id }) {
            await open(row)
        } else if first, conversationId == nil, messages.isEmpty, let row = app?.server == nil ? conversations.first : ConversationSummary.personalDefault(conversations) {
            await open(row)
        }
    }

    func open(_ conversation: ConversationSummary) async {
        guard !isStreaming, let backend = app?.backend else { return }
        visited = true
        historyRevision += 1
        let revision = historyRevision
        if conversationId != conversation.id {
            observedTurn = nil
            historyRows = []
            older = nil
            messages = []
            pause = nil
        }
        conversationId = conversation.id
        error = nil
        isLoading = true
        defer { if historyRevision == revision { isLoading = false } }
        do {
            if let server = backend as? ServerBackend {
                let page = try await server.historyPage(conversation.id, bot: bot)
                guard historyRevision == revision else { return }
                var fresh = page.rows
                var next = page.next
                let known = Set(historyRows.compactMap(Self.historyKey))
                while !known.isEmpty, !fresh.contains(where: { Self.historyKey($0).map(known.contains) == true }),
                      let position = next {
                    let prior = try await server.historyPage(conversation.id, bot: bot, position: position)
                    guard historyRevision == revision else { return }
                    fresh = Self.joinHistory(older: prior.rows, newer: fresh)
                    next = prior.next
                }
                let previousCount = historyRows.count
                if next == nil {
                    historyRows = fresh
                    older = nil
                } else {
                    historyRows = Self.joinHistory(older: historyRows, newer: fresh)
                    if historyRows.count == fresh.count { older = next }
                    else if older?.cursor == nil { older?.offset += max(0, historyRows.count - previousCount) }
                }
                // The selected thread may have a pending write, so restore its approval card too.
                installObservedHistory(server.historyMessages(historyRows, bot: bot))
                pause = page.pause
            } else {
                let loaded = try await backend.messages(in: conversation, bot: bot)
                guard historyRevision == revision else { return }
                messages = loaded
                pause = backend.openPause(in: conversation)
            }
            runDeviceReads()
        } catch {
            if historyRevision == revision { self.error = error.localizedDescription }
        }
    }

    private static func historyKey(_ row: [String: Any]) -> String? {
        if let seq = row["history_seq"] as? Int { return "seq:\(seq)" }
        return row["id"] as? String
    }

    static func joinHistory(older: [[String: Any]], newer: [[String: Any]]) -> [[String: Any]] {
        // Rows are in chronological order. The newest copy of an overlapping id is authoritative.
        let ids = Set(newer.compactMap(historyKey))
        if let overlap = older.firstIndex(where: { row in historyKey(row).map(ids.contains) == true }) {
            return Array(older[..<overlap]) + newer
        }
        return older + newer
    }

    func loadOlder() async {
        guard !isStreaming, !isLoading, !loadingOlder, let older, let thread = conversationId, let server = app?.server else { return }
        let revision = historyRevision
        loadingOlder = true
        defer { loadingOlder = false }
        do {
            let page = try await server.historyPage(thread, bot: bot, position: older)
            guard historyRevision == revision, !isStreaming else { return }
            historyRows = Self.joinHistory(older: page.rows, newer: historyRows)
            self.older = page.next
            installObservedHistory(server.historyMessages(historyRows, bot: bot))
        } catch {
            if historyRevision == revision { self.error = error.localizedDescription }
        }
    }

    private func installObservedHistory(_ history: [ChatMessage]) {
        if let turn = observedTurn, turn.ended, turn.committedTail(history).contains(where: { $0.role == .assistant }) {
            observedTurn = nil
        }
        messages = observedTurn?.merged(history) ?? history
    }

    /// Subscribe without sending a turn. Keep the uncommitted prefix until the durable reply appears.
    func observe(_ thread: String) async {
        guard let server = app?.server else { return }
        let row = ConversationSummary(id: thread, title: "", updatedAt: nil, botId: bot.id)
        func start(_ id: String?) {
            if let id, let prior = observedTurn?.id, prior != id {
                observedTurn = nil
                messages = server.historyMessages(historyRows, bot: bot)
            }
            if observedTurn == nil { observedTurn = ObservedTurn(id: id, anchor: messages.last) }
            if let id { observedTurn?.id = id }
            observedTurn?.ended = false
        }
        func finish() async {
            observedTurn?.ended = true
            for attempt in 0..<4 {
                guard !Task.isCancelled, !isStreaming, conversationId == thread else { return }
                await open(row)
                guard observedTurn?.ended == true, attempt < 3 else { return }
                try? await Task.sleep(for: .milliseconds(300))
            }
        }
        while !Task.isCancelled, conversationId == thread, !isStreaming {
            do {
                for try await event in server.observe(thread, bot: bot) {
                    guard !Task.isCancelled, !isStreaming, conversationId == thread else { return }
                    switch event {
                    case .status(let active, let turn):
                        if active {
                            if let turn, let prior = observedTurn?.id, prior != turn { await finish() }
                            start(turn)
                        } else { await finish() }
                    case .finished:
                        await finish()
                    case .user(let user):
                        start(nil)
                        if !messages.contains(where: { $0.id == user.id }) {
                            observedTurn?.rows.append(user)
                            messages.append(user)
                        }
                    case .delta(let delta):
                        start(nil)
                        if observedTurn?.rows.last?.role != .assistant {
                            let reply = ChatMessage(role: .assistant, text: "", status: .streaming)
                            observedTurn?.rows.append(reply)
                            messages.append(reply)
                        }
                        if let id = observedTurn?.rows.last?.id {
                            apply(delta, to: id)
                            if let updated = messages.last(where: { $0.id == id }), let index = observedTurn?.rows.indices.last {
                                observedTurn?.rows[index] = updated
                            }
                        }
                    }
                }
            } catch { if Task.isCancelled { return } }
            try? await Task.sleep(for: .seconds(2))
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
        historyRevision += 1
        isLoading = false
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
                    guard currentRun == run, !Task.isCancelled else { return }
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

    func stop() {
        guard isStreaming, let backend = app?.backend else { return }
        if let conversationId { Task { await backend.stop(conversation: conversationId, bot: bot) } }
        task?.cancel()
    }

    func cancel() {
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
