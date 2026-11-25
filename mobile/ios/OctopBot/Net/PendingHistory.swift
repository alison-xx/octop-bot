import CryptoKit
import Foundation
import Observation

/// The exact history append, kept on this device until Lynxce acknowledges it.
struct PendingHistory: Codable {
    let id: UUID
    let botID: String
    let sessionID: String
    let user: String
    let startedAt: String
    let answer: String
    let thinking: String
    let wireUser: String
    let wireAnswer: String
    let finishedAt: String
    let model: String?
    let generationFailure: String?
    let creditFailure: Bool
    let dailyLimit: Bool

    init(turn: CompletionChat.Turn, sessionID: String) {
        id = UUID()
        botID = turn.botID
        self.sessionID = sessionID
        user = turn.user
        startedAt = ISO8601.string(turn.startedAt)
        answer = turn.answer
        thinking = turn.thinking
        finishedAt = ISO8601.string(.now)
        model = turn.model
        let error = turn.generationError
        generationFailure = error is CancellationError ? nil : error?.localizedDescription
        creditFailure = (error as? APIError)?.kind == .credits
        dailyLimit = (error as? APIError)?.kind == .dailyLimit
        // The append API requires nonempty content and measures limits in UTF-16 code units.
        wireUser = Self.wireText(user.isEmpty ? L("chat.image") : user, limit: 20_000)
        let trimmed = answer.trimmingCharacters(in: .whitespacesAndNewlines)
        let fallback = generationFailure ?? (thinking.isEmpty ? "" : L("chat.thought"))
        wireAnswer = Self.wireText(trimmed.isEmpty ? fallback : trimmed, limit: 40_000)
    }

    private static func wireText(_ text: String, limit: Int) -> String {
        String(decoding: text.utf16.prefix(limit), as: UTF16.self)
    }

    var status: MessageStatus {
        if creditFailure { return .outOfCredits }
        if dailyLimit { return .dailyLimit }
        return generationFailure.map(MessageStatus.failed) ?? .done
    }

    var title: String {
        let text = String(user.trimmingCharacters(in: .whitespacesAndNewlines).prefix(40))
        return text.isEmpty ? "Octop Bot" : text
    }

    var body: [String: Any] {
        var items: [[String: Any]] = [["role": "user", "content": wireUser, "createdAt": startedAt]]
        if !wireAnswer.isEmpty {
            var reply: [String: Any] = ["role": "assistant", "content": wireAnswer, "createdAt": finishedAt]
            if !thinking.isEmpty { reply["thinking"] = Self.wireText(thinking, limit: 20_000) }
            if let model { reply["model"] = model }
            if generationFailure != nil { reply["status"] = "failed" }
            items.append(reply)
        }
        return ["title": title, "model": model ?? "auto", "items": items]
    }

    func overlay(on messages: inout [ChatMessage]) {
        var question = ChatMessage(id: id.uuidString + "-user", role: .user, text: user)
        question.createdAt = ISO8601.parse(startedAt) ?? .distantPast
        var reply = ChatMessage(id: id.uuidString, role: .assistant, text: answer, thinking: thinking, status: status)
        reply.createdAt = ISO8601.parse(finishedAt) ?? question.createdAt
        for message in [question, reply] {
            messages.removeAll { $0.role == message.role && $0.createdAt == message.createdAt }
            messages.append(message)
        }
    }
}

/// Each account and service has its own protected directory. Records contain no credentials.
struct PendingHistoryStore {
    @Observable
    fileprivate final class Operations {
        var writes: [UUID: (session: String, task: Task<Void, Error>)] = [:]
        var deleting: Set<String> = []
        var deleted: Set<String> = []
    }

    private static var operationsByDirectory: [URL: Operations] = [:]
    private let operations: Operations
    private let directory: URL
    // If iOS temporarily denies disk writes, keep the reply across view and account changes.
    private static var memoryOnly: [URL: [UUID: PendingHistory]] = [:]
    init(origin: URL, account: String, root: URL = URL.applicationSupportDirectory) {
        let scope = SHA256.hash(data: Data((origin.absoluteString + "\u{0}" + account).utf8))
        let key = scope.map { String(format: "%02x", $0) }.joined()
        directory = root.appendingPathComponent("PendingHistory").appendingPathComponent(key)
        let shared = Self.operationsByDirectory[directory] ?? Operations()
        Self.operationsByDirectory[directory] = shared
        operations = shared
    }

    func remember(_ turn: PendingHistory) {
        guard !operations.deleted.contains(turn.sessionID) else { return }
        do { try put(turn) }
        catch { Self.memoryOnly[directory, default: [:]][turn.id] = turn }
    }

    func put(_ turn: PendingHistory) throws {
        var folder = directory
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try folder.setResourceValues(values)
        try JSONEncoder().encode(turn).write(to: directory.appendingPathComponent(turn.id.uuidString),
                                              options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }

    func turns(bot: String, session: String? = nil) -> [PendingHistory] {
        let files = (try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)) ?? []
        let saved = files.compactMap { url -> PendingHistory? in
            guard let data = try? Data(contentsOf: url), let turn = try? JSONDecoder().decode(PendingHistory.self, from: data),
                  turn.botID == bot, session == nil || turn.sessionID == session else { return nil }
            return turn
        }
        let memory = (Self.memoryOnly[directory] ?? [:]).values.filter {
            $0.botID == bot && (session == nil || $0.sessionID == session)
        }
        return (saved + memory).filter { !operations.deleted.contains($0.sessionID) }.sorted { $0.startedAt < $1.startedAt }
    }

    func canRetry(_ turn: PendingHistory) -> Bool {
        guard operations.writes[turn.id] == nil, !operations.deleting.contains(turn.sessionID),
              !operations.deleted.contains(turn.sessionID) else { return false }
        return Self.memoryOnly[directory]?[turn.id] != nil ||
            FileManager.default.fileExists(atPath: directory.appendingPathComponent(turn.id.uuidString).path)
    }

    func write(_ turn: PendingHistory, append: @escaping @MainActor () async throws -> Void) async throws {
        guard !operations.deleting.contains(turn.sessionID), !operations.deleted.contains(turn.sessionID) else {
            throw CancellationError()
        }
        if let current = operations.writes[turn.id] { return try await current.task.value }
        let task = Task {
            try await append()
            try remove(turn)
        }
        operations.writes[turn.id] = (turn.sessionID, task)
        defer { operations.writes[turn.id] = nil }
        try await task.value
    }

    func delete(bot: String, session: String, request: () async throws -> Void) async throws {
        guard operations.deleting.insert(session).inserted else { throw CancellationError() }
        defer { operations.deleting.remove(session) }
        let active = operations.writes.values.filter { $0.session == session }
        for write in active { _ = await write.task.result }
        try await request()
        operations.deleted.insert(session)
        for turn in turns(bot: bot, session: session) { try remove(turn) }
    }

    func remove(_ turn: PendingHistory) throws {
        Self.memoryOnly[directory]?[turn.id] = nil
        let url = directory.appendingPathComponent(turn.id.uuidString)
        if FileManager.default.fileExists(atPath: url.path) { try FileManager.default.removeItem(at: url) }
    }
}
