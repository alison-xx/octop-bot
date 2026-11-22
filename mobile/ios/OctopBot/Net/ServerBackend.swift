import Foundation

/// A self-hosted Octop Bot server (NAS / Docker web build): its Bots, tools, memory and groups.
final class ServerBackend: ChatBackend {
    struct Session: Codable {
        var baseURL: URL
        var token: String
        var displayName: String
    }

    private static let sessionKey = "server.session"
    private(set) var session: Session
    private var voice: (stt: Bool, tts: Bool)?
    private var sockets: [String: URLSessionWebSocketTask] = [:]

    var supportsGroups: Bool { true }
    var accountName: String { session.displayName }
    var host: String {
        guard let host = session.baseURL.host() else { return session.baseURL.absoluteString }
        return session.baseURL.port.map { "\(host):\($0)" } ?? host
    }

    init(session: Session) { self.session = session }

    static func restore() -> ServerBackend? {
        Keychain.codable(Session.self, for: sessionKey).map { ServerBackend(session: $0) }
    }

    // MARK: Sign-in

    /// How this server wants its owner to sign in, mirroring the dashboard's login route.
    enum SignInMode: Equatable {
        /// Bot web build owned (or about to be claimed) by a Lynxce account.
        case lynxce(claimed: Bool)
        /// Bot web build whose owner chose a local password (username `local`).
        case localPassword
        /// A regular Octop server: username and password.
        case password
    }

    /// Accepts "nas.local:8080" as well as a full URL.
    static func normalize(_ text: String) -> URL? {
        var raw = text.trimmingCharacters(in: .whitespacesAndNewlines)
        while raw.hasSuffix("/") { raw.removeLast() }
        if !raw.contains("://") { raw = "https://" + raw }
        guard let url = URL(string: raw), let scheme = url.scheme, ["http", "https"].contains(scheme), url.host() != nil else {
            return nil
        }
        return url
    }

    /// Without a typed scheme, try https first and fall back to http (LAN NAS boxes often lack TLS).
    static func probeTryingHTTP(_ base: URL, typedScheme: Bool) async throws -> (SignInMode, URL) {
        do {
            return (try await probe(base), base)
        } catch let error as APIError where error.kind == .network && !typedScheme {
            var components = URLComponents(url: base, resolvingAgainstBaseURL: false)!
            components.scheme = "http"
            guard let plain = components.url else { throw error }
            return (try await probe(plain), plain)
        }
    }

    static func probe(_ base: URL) async throws -> SignInMode {
        let status = try await anonymous(base, .get, "/api/setup/status")
        guard status["lynxce_login"] as? Bool == true else { return .password }
        let setupRequired = status["setup_required"] as? Bool ?? false
        let identity = try? await anonymous(base, .get, "/api/auth/lynxce/status")
        let claimed = identity?["claimed"] as? Bool ?? false
        return setupRequired || claimed ? .lynxce(claimed: claimed) : .localPassword
    }

    enum SignInResult {
        case signedIn(ServerBackend)
        case mfa(token: String)
    }

    static func signInWithLynxce(_ base: URL, account: String, password: String) async throws -> ServerBackend {
        let body = try await anonymous(base, .post, "/api/auth/lynxce/login", json: [
            "account": account, "password": password, "locale": Preferences.shared.language.isChinese ? "zh" : "en",
        ])
        return try finish(base, body)
    }

    static func signIn(_ base: URL, username: String, password: String) async throws -> SignInResult {
        let body = try await anonymous(base, .post, "/api/auth/login", json: ["username": username, "password": password])
        if body["mfa_required"] as? Bool == true, let token = body["mfa_token"] as? String {
            return .mfa(token: token)
        }
        return .signedIn(try finish(base, body))
    }

    static func verifyMFA(_ base: URL, token: String, code: String) async throws -> ServerBackend {
        let body = try await anonymous(base, .post, "/api/auth/mfa/verify", json: ["mfa_token": token, "method": "totp", "code": code])
        return try finish(base, body)
    }

    private static func finish(_ base: URL, _ body: [String: Any]) throws -> ServerBackend {
        guard let token = body["access_token"] as? String else { throw APIError(kind: .server, status: 502, message: nil) }
        let user = body["user"] as? [String: Any]
        let name = (user?["display_name"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? user?["username"] as? String ?? "Octop"
        let session = Session(baseURL: base, token: token, displayName: name)
        Keychain.setCodable(session, for: sessionKey)
        return ServerBackend(session: session)
    }

    private static func anonymous(_ base: URL, _ method: HTTPMethod, _ path: String, json: Any? = nil) async throws -> [String: Any] {
        let request = try HTTP.request(base.appending(path: path), method: method, json: json)
        let (data, response) = try await HTTP.data(for: request)
        guard (200..<300).contains(response.statusCode) else {
            throw APIError.from(status: response.statusCode, message: HTTP.errorMessage(data))
        }
        return (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
    }

    // MARK: Transport

    func url(_ path: String, query: [String: String] = [:]) -> URL {
        var components = URLComponents(url: session.baseURL.appending(path: path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { components.queryItems = query.sorted { $0.key < $1.key }.map { URLQueryItem(name: $0.key, value: $0.value) } }
        return components.url!
    }

    var authHeaders: [String: String] { ["Authorization": "Bearer \(session.token)"] }

    func raw(
        _ method: HTTPMethod, _ path: String, query: [String: String] = [:], json: Any? = nil,
        form: [FormPart]? = nil, timeout: TimeInterval = 60
    ) async throws -> Data {
        var request = try HTTP.request(url(path, query: query), method: method, headers: authHeaders, json: json, form: form)
        request.timeoutInterval = timeout
        let (data, response) = try await HTTP.data(for: request)
        // Sliding sessions: the server hands out a fresh token near expiry.
        if let renewed = response.value(forHTTPHeaderField: "X-Octop-Access-Token"), !renewed.isEmpty, renewed != session.token {
            session.token = renewed
            Keychain.setCodable(session, for: Self.sessionKey)
        }
        guard (200..<300).contains(response.statusCode) else {
            throw APIError.from(status: response.statusCode, message: HTTP.errorMessage(data))
        }
        return data
    }

    func json(
        _ method: HTTPMethod, _ path: String, query: [String: String] = [:], json body: Any? = nil,
        form: [FormPart]? = nil, timeout: TimeInterval = 60
    ) async throws -> Any {
        let data = try await raw(method, path, query: query, json: body, form: form, timeout: timeout)
        return data.isEmpty ? NSNull() : ((try? JSONSerialization.jsonObject(with: data)) ?? NSNull())
    }

    // MARK: Directory

    private(set) var directory: [BotProfile] = []
    private(set) var groupRows: [[String: Any]] = []

    /// Localized tool names (`execute` → "执行指令"), in the app's language.
    private(set) var toolLabels: [String: String] = [:]
    private var toolLabelsLanguage: String?

    private func loadToolLabels() async {
        let language = Preferences.shared.language.httpTag
        guard toolLabelsLanguage != language else { return }
        if let body = try? await json(.get, "/api/i18n/tools") as? [String: Any], let labels = body["labels"] as? [String: String] {
            toolLabels = labels
            toolLabelsLanguage = language
        }
    }

    func bots() async throws -> [BotProfile] {
        await loadToolLabels()
        let workspace = try await json(.get, "/api/octop-bot/workspace") as? [String: Any] ?? [:]
        let rows = workspace["bots"] as? [[String: Any]] ?? []
        directory = rows.compactMap(Self.bot)
        groupRows = workspace["groups"] as? [[String: Any]] ?? []
        return directory
    }

    static func bot(_ row: [String: Any]) -> BotProfile? {
        guard let id = row["agent_id"] as? String else { return nil }
        let chief = row["is_main"] as? Bool ?? false
        let avatar = row["avatar"] as? [String: Any]
        return BotProfile(
            id: id,
            name: row["name"] as? String ?? id,
            subtitle: (row["description"] as? String).flatMap { $0.isEmpty ? nil : $0 },
            look: normalizedLook(shape: avatar?["shape"] as? String, color: avatar?["color"] as? String, chief: chief),
            isChief: chief
        )
    }

    /// Same remapping as the dashboard's `visibleAppearance`.
    static func normalizedLook(shape: String?, color: String?, chief: Bool) -> Look {
        guard let shape, let color else { return chief ? .chief : .fallback }
        if shape == "whale" { return chief ? .chief : Look(shape: "gumdrop", color: color == "deepseek" ? "blue" : color) }
        return Look(shape: shape, color: color == "deepseek" ? "blue" : color)
    }

    func setLook(_ look: Look, for bot: BotProfile) async throws {
        _ = try await json(.put, "/api/octop-bot/bots/\(bot.id)/appearance", json: ["shape": look.shape, "color": look.color])
    }

    /// A new teammate Bot with a role prompt and look, like the dashboard's quick create.
    func createBot(name: String, role: String, look: Look) async throws -> String {
        let created = try await json(.post, "/api/agents", json: [
            "name": name, "description": role, "system_prompt": role,
        ], timeout: 120) as? [String: Any]
        guard let id = created?["agent_id"] as? String else { throw APIError(kind: .server, status: 502, message: nil) }
        _ = try? await json(.put, "/api/octop-bot/bots/\(id)/appearance", json: ["shape": look.shape, "color": look.color])
        return id
    }

    func createGroup(name: String, admin: String, members: [String]) async throws {
        _ = try await json(.post, "/api/octop-bot/groups", json: [
            "name": name, "admin_id": admin, "member_ids": members, "reply_mode": "admin_first",
        ])
    }

    func models() async throws -> [ModelOption] { [] }

    // MARK: Threads

    func conversations(for bot: BotProfile) async throws -> [ConversationSummary] {
        let rows = try await json(.get, "/api/agents/\(bot.id)/threads", query: ["limit": "50"]) as? [[String: Any]] ?? []
        return rows.compactMap { row in
            guard let id = row["thread_id"] as? String, row["has_messages"] as? Bool ?? true else { return nil }
            let date = (row["last_active"] as? String).flatMap(ISO8601.parse)
                ?? (row["last_active"] as? Double).map { Date(timeIntervalSince1970: $0 > 1e12 ? $0 / 1000 : $0) }
            let title = (row["title"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? L("chat.untitled")
            return ConversationSummary(id: id, title: title, updatedAt: date, botId: bot.id)
        }
        .sorted { ($0.updatedAt ?? .distantPast) > ($1.updatedAt ?? .distantPast) }
    }

    func messages(in conversation: ConversationSummary, bot: BotProfile) async throws -> [ChatMessage] {
        for _ in 0..<20 {
            let body = try await json(
                .get, "/api/agents/\(bot.id)/threads/\(conversation.id)/history", query: ["limit": "60"]
            ) as? [String: Any] ?? [:]
            if body["history_loading"] as? Bool == true {
                let wait = (body["history_retry_after_ms"] as? Double ?? 800) / 1000
                try await Task.sleep(for: .seconds(min(max(wait, 0.3), 3)))
                continue
            }
            return Self.history(body["messages"] as? [[String: Any]] ?? [], labels: toolLabels)
        }
        return []
    }

    /// Server history rows → chat messages; tool rows are folded into the assistant's tool steps.
    static func history(_ rows: [[String: Any]], labels: [String: String] = [:]) -> [ChatMessage] {
        var out: [ChatMessage] = []
        for row in rows {
            guard let role = (row["role"] as? String).flatMap(MessageRole.init(rawValue:)), role != .system else { continue }
            var text = ""
            var thinking = ""
            var tools: [ToolStep] = []
            let blocks = row["content"] as? [[String: Any]] ?? []
            for block in blocks {
                switch block["type"] as? String {
                case "text": text += block["text"] as? String ?? ""
                case "thinking": thinking += block["thinking"] as? String ?? ""
                case "tool_use":
                    let id = block["id"] as? String ?? UUID().uuidString
                    let name = block["name"] as? String ?? "tool"
                    tools.append(ToolStep(id: id, name: labels[name] ?? name, done: true))
                default: break
                }
            }
            if let plain = row["content"] as? String { text = plain }
            if role == .user, let files = row["inbound_attachments"] as? [[String: Any]], !files.isEmpty {
                let names = files.compactMap { $0["filename"] as? String }.map { "📎 " + $0 }
                text = (names + [text]).filter { !$0.isEmpty }.joined(separator: "\n")
            }
            // Consecutive assistant segments of one turn read as one reply.
            if role == .assistant, let last = out.last, last.role == .assistant {
                out[out.count - 1].text += (last.text.isEmpty || text.isEmpty ? "" : "\n\n") + text
                out[out.count - 1].thinking += thinking
                out[out.count - 1].tools += tools
                continue
            }
            var message = ChatMessage(role: role, text: text, thinking: thinking, tools: tools)
            if let ms = row["timestamp"] as? Double { message.createdAt = Date(timeIntervalSince1970: ms / 1000) }
            if row["status"] as? String == "error" { message.status = .failed(L("chat.failed")) }
            if let id = row["id"] as? String { message.id = id }
            if !message.text.isEmpty || !message.tools.isEmpty || !message.thinking.isEmpty { out.append(message) }
        }
        return out
    }

    func deleteConversation(_ conversation: ConversationSummary, bot: BotProfile) async throws {
        _ = try await raw(.delete, "/api/agents/\(bot.id)/threads/\(conversation.id)")
    }

    // MARK: Chat over WebSocket

    func send(
        _ text: String, images: [Data], to bot: BotProfile, conversation: String?,
        history: [ChatMessage], model: String?
    ) -> AsyncThrowingStream<StreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                var socket: URLSessionWebSocketTask?
                do {
                    var threadId = conversation
                    if threadId == nil {
                        let created = try await json(.post, "/api/agents/\(bot.id)/threads") as? [String: Any]
                        guard let id = created?["thread_id"] as? String else { throw APIError(kind: .server, status: 502, message: nil) }
                        threadId = id
                        continuation.yield(.conversation(id))
                    }
                    guard let threadId else { return }
                    var content: Any = text
                    if !images.isEmpty {
                        var blocks: [[String: Any]] = [["type": "text", "text": text]]
                        for (index, image) in images.enumerated() {
                            blocks.append(try await upload(image, index: index, bot: bot))
                        }
                        content = blocks
                    }
                    var turn: [String: Any] = [
                        "type": "user_turn", "thread_id": threadId, "text": text,
                        "messages": [["role": "user", "content": content, "id": UUID().uuidString]],
                    ]
                    if let model { turn["model"] = model }

                    var components = URLComponents(url: url("/api/agents/\(bot.id)/chat/ws"), resolvingAgainstBaseURL: false)!
                    components.scheme = components.scheme == "https" ? "wss" : "ws"
                    components.queryItems = [URLQueryItem(name: "token", value: session.token)]
                    let ws = HTTP.session.webSocketTask(with: components.url!)
                    socket = ws
                    sockets[threadId] = ws
                    ws.resume()
                    try await ws.send(.string(Self.encode(turn)))

                    let pinger = Task {
                        while !Task.isCancelled {
                            try? await Task.sleep(for: .seconds(25))
                            try? await ws.send(.string(#"{"type":"ping"}"#))
                        }
                    }
                    defer { pinger.cancel() }
                    var mapper = ServerFrameMapper(labels: toolLabels)
                    loop: while true {
                        let message = try await ws.receive()
                        guard case .string(let raw) = message,
                              let frame = try? JSONSerialization.jsonObject(with: Data(raw.utf8)) as? [String: Any] else { continue }
                        switch try mapper.map(frame) {
                        case .events(let events): events.forEach { continuation.yield($0) }
                        case .finished: break loop
                        }
                    }
                    continuation.yield(.done)
                    continuation.finish()
                } catch {
                    if let close = socket?.closeCode, close.rawValue == 4001 {
                        continuation.finish(throwing: APIError(kind: .unauthorized, status: 401, message: nil))
                    } else {
                        continuation.finish(throwing: Task.isCancelled ? CancellationError() : (error as? APIError ?? APIError.network))
                    }
                }
                socket?.cancel(with: .normalClosure, reason: nil)
                if let conversation { sockets[conversation] = nil }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    static func encode(_ object: [String: Any]) -> String {
        String(decoding: (try? JSONSerialization.data(withJSONObject: object)) ?? Data("{}".utf8), as: UTF8.self)
    }

    private func upload(_ image: Data, index: Int, bot: BotProfile) async throws -> [String: Any] {
        let name = "photo-\(Int(Date().timeIntervalSince1970))-\(index + 1).jpg"
        let body = try await json(.post, "/api/agents/\(bot.id)/upload", form: [
            FormPart(name: "file", file: image, filename: name, mimeType: "image/jpeg"),
        ], timeout: 180) as? [String: Any] ?? [:]
        guard let path = body["workspace_path"] as? String else { throw APIError(kind: .server, status: 502, message: nil) }
        let media = body["media_type"] as? String ?? "image/jpeg"
        return [
            "type": "image",
            "source": ["type": "url", "url": body["url"] as? String ?? "", "media_type": media],
            "workspace_path": path,
            "filename": body["filename"] as? String ?? name,
        ]
    }

    func stop(conversation: String, bot: BotProfile) async {
        try? await sockets[conversation]?.send(.string(Self.encode(["type": "cancel", "thread_id": conversation])))
    }

    // MARK: Groups

    func groups() async throws -> [GroupSummary] {
        if directory.isEmpty { _ = try await bots() }
        let rows = try await json(.get, "/api/octop-bot/groups") as? [[String: Any]] ?? groupRows
        let byId = Dictionary(directory.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        return rows.compactMap { row in
            guard let id = row["group_id"] as? String else { return nil }
            let members = (row["member_ids"] as? [String] ?? []).compactMap { byId[$0] }
            return GroupSummary(id: id, name: row["name"] as? String ?? id, members: members, updatedAt: nil)
        }
    }

    struct GroupMessage: Hashable {
        var id: String
        var role: String
        var agentId: String?
        var text: String
        var createdAt: Date
        var requestId: String?
    }

    static func groupMessage(_ row: [String: Any]) -> GroupMessage? {
        guard let id = (row["message_id"] as? String) ?? (row["message_id"] as? Int).map(String.init) else { return nil }
        let created = row["created_at"] as? Double ?? 0
        return GroupMessage(
            id: id, role: row["role"] as? String ?? "assistant", agentId: row["agent_id"] as? String,
            text: row["text"] as? String ?? "",
            createdAt: Date(timeIntervalSince1970: created > 1e12 ? created / 1000 : created),
            requestId: row["request_id"] as? String
        )
    }

    func groupMessages(_ group: String, after: String?) async throws -> [GroupMessage] {
        let rows = try await json(
            .get, "/api/octop-bot/groups/\(group)/messages", query: after.map { ["after_id": $0] } ?? [:]
        ) as? [[String: Any]] ?? []
        return rows.compactMap(Self.groupMessage)
    }

    func groupDrafts(_ group: String) async throws -> [(agentId: String, text: String)] {
        let rows = try await json(.get, "/api/octop-bot/groups/\(group)/drafts") as? [[String: Any]] ?? []
        return rows.compactMap { row in
            guard let agent = row["agent_id"] as? String else { return nil }
            return (agent, row["text"] as? String ?? "")
        }
    }

    func postGroupMessage(_ group: String, text: String, mentions: [String], requestId: String) async throws {
        _ = try await raw(.post, "/api/octop-bot/groups/\(group)/messages", json: [
            "request_id": requestId, "text": text, "mention_ids": mentions,
        ], timeout: 900)
    }

    func groupMemory(_ group: String) async throws -> String {
        (try await json(.get, "/api/octop-bot/groups/\(group)/memory") as? [String: Any])?["text"] as? String ?? ""
    }

    func groupGoal(_ group: String) async throws -> (title: String, status: String)? {
        guard let goal = try await json(.get, "/api/octop-bot/groups/\(group)/goal") as? [String: Any],
              let title = goal["title"] as? String, !title.isEmpty else { return nil }
        return (title, goal["status"] as? String ?? "draft")
    }

    // MARK: Voice, push, account

    private func voiceSupport() async -> (stt: Bool, tts: Bool) {
        if let voice { return voice }
        let active = (try? await json(.get, "/api/voice/active")) as? [String: Any]
        let support = (active?["stt"] is String, active?["tts"] is String)
        voice = support
        return support
    }

    func transcribe(_ audio: Data) async throws -> String? {
        guard await voiceSupport().stt else { return nil }
        let language = Preferences.shared.language.httpTag
        let body = try await json(.post, "/api/voice/stt", form: [
            FormPart(name: "audio", file: audio, filename: "voice.m4a", mimeType: "audio/mp4"),
            FormPart(name: "language", value: language),
        ], timeout: 120) as? [String: Any]
        return body?["text"] as? String
    }

    func speech(for text: String) async throws -> Data? {
        guard await voiceSupport().tts else { return nil }
        return try await raw(.post, "/api/voice/tts", json: ["text": String(text.prefix(4000))], timeout: 120)
    }

    func registerPush(token: String) async {}

    func signOut() async {
        for socket in sockets.values { socket.cancel(with: .goingAway, reason: nil) }
        _ = try? await raw(.post, "/api/auth/logout")
        Keychain.set(nil, for: Self.sessionKey)
    }
}

/// Maps Octop chat WebSocket frames to stream events. Separate for unit tests.
struct ServerFrameMapper {
    enum Outcome { case events([StreamEvent]), finished }
    private var toolNames: [String: String] = [:]
    var labels: [String: String] = [:]

    init(labels: [String: String] = [:]) { self.labels = labels }

    mutating func map(_ frame: [String: Any]) throws -> Outcome {
        switch frame["type"] as? String {
        case "token":
            let text = frame["content"] as? String ?? ""
            return .events(text.isEmpty ? [] : [.text(text)])
        case "reasoning":
            let text = frame["content"] as? String ?? ""
            return .events(text.isEmpty ? [] : [.thinking(text)])
        case "tool_call_chunk":
            guard let id = frame["id"] as? String, !id.isEmpty else { return .events([]) }
            let raw = frame["name"] as? String
            let name = (frame["display_name"] as? String) ?? raw.map { labels[$0] ?? $0 }
            guard let name, !name.isEmpty, toolNames[id] == nil else { return .events([]) }
            toolNames[id] = name
            return .events([.tool(id: id, name: name, done: false)])
        case "tool_result":
            let messages = frame["messages"] as? [[String: Any]] ?? []
            var events: [StreamEvent] = []
            for message in messages {
                let id = (message["tool_call_id"] as? String) ?? (message["id"] as? String) ?? ""
                if let name = toolNames[id] { events.append(.tool(id: id, name: name, done: true)) }
            }
            return .events(events)
        case "error":
            throw APIError(kind: .server, status: 500, message: frame["message"] as? String)
        case "hitl_required":
            throw APIError(kind: .rejected, status: 409, message: L("chat.needsApproval"))
        case "turn.ended":
            if frame["failed"] as? Bool == true { throw APIError(kind: .server, status: 500, message: nil) }
            return .finished
        default:
            return .events([])
        }
    }
}
