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
    private var task: Task<Void, Never>?
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

    func newChat() {
        cancel()
        conversationId = nil
        messages = []
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
        error = nil
        guard let backend = app?.backend else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let loaded = try await backend.messages(in: conversation, bot: bot)
            if conversationId == conversation.id { messages = loaded }
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
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let backend = app?.backend, !isStreaming, !trimmed.isEmpty || !images.isEmpty else { return }
        if app?.notifyOnReply == true { Notifier.requestPermission() }
        let bot = bot
        let history = messages
        messages.append(ChatMessage(role: .user, text: trimmed, images: images))
        var reply = ChatMessage(role: .assistant, text: "", status: .streaming)
        reply.authorId = bot.id
        messages.append(reply)
        error = nil
        isStreaming = true
        let replyId = reply.id
        let model = app?.isLynxce == true ? app?.selectedModel : nil
        let stream = backend.send(trimmed, images: images, to: bot, conversation: conversationId, history: history, model: model)
        let background = UIApplication.shared.beginBackgroundTask(withName: "reply")
        task = Task {
            defer {
                isStreaming = false
                UIApplication.shared.endBackgroundTask(background)
            }
            do {
                for try await event in stream {
                    apply(event, to: replyId)
                }
                update(replyId) { $0.status = .done }
                let text = messages.first { $0.id == replyId }?.text ?? ""
                app?.recordPreview(text, for: bot)
                if app?.notifyOnReply == true { Notifier.replyFinished(bot: bot.name, text: text) }
                if let onReply {
                    onReply(text)
                } else if app?.readAloud == true {
                    Speaker.shared.speak(text, backend: backend)
                }
                await reloadConversations()
            } catch is CancellationError {
                update(replyId) { $0.status = .done }
                removeEmptyReply(replyId)
            } catch {
                let message = error.localizedDescription
                update(replyId) { $0.status = .failed(message) }
                if case .unauthorized = (error as? APIError)?.kind { Task { await self.app?.signOut() } }
            }
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
        case .done:
            break
        }
    }

    private func update(_ id: String, _ change: (inout ChatMessage) -> Void) {
        guard let index = messages.lastIndex(where: { $0.id == id }) else { return }
        change(&messages[index])
    }

    private func removeEmptyReply(_ id: String) {
        messages.removeAll { $0.id == id && $0.text.isEmpty && $0.tools.isEmpty }
    }

    func stop() {
        guard isStreaming, let backend = app?.backend else { return }
        if let conversationId { Task { await backend.stop(conversation: conversationId, bot: bot) } }
        task?.cancel()
    }

    func cancel() {
        task?.cancel()
        task = nil
        isStreaming = false
    }

    /// Re-ask the last question after a failed or unwanted reply.
    func retry() {
        guard !isStreaming, let lastUser = messages.lastIndex(where: { $0.role == .user }) else { return }
        let question = messages[lastUser]
        messages.removeSubrange(lastUser...)
        send(question.text, images: question.images)
    }
}
