import Foundation

/// A self-hosted Octop Bot server (NAS / Docker web build): its Bots, tools, memory and groups.
final class ServerBackend: ChatBackend {
    struct Session: Codable {
        var baseURL: URL
        var token: String
        var displayName: String
        /// Octop Bot cloud (bot.lynxce.cn): signed in with Lynxce, which it keeps for the wallet.
        var cloud: Bool?
        var signupExpiryDay: String? = nil
    }

    /// Octop Bot cloud, run by Lynxce.
    static let lynxceCloud = URL(string: "https://bot.lynxce.cn")!
    var isCloud: Bool { session.cloud == true }

    private static let sessionKey = "server.session"
    private(set) var session: Session
    var signupCredits: Double?
    var signupExpiryDay: String? { session.signupExpiryDay }
    private var voice: (stt: Bool, tts: Bool)?
    private var sockets: [String: URLSessionWebSocketTask] = [:]

    var supportsGroups: Bool { true }
    /// The person's display name; never the internal username (`sso_…`, `owner`).
    var accountName: String { session.displayName.isEmpty ? L("account.genericName") : session.displayName }
    var host: String {
        guard let host = session.baseURL.host() else { return session.baseURL.absoluteString }
        return session.baseURL.port.map { "\(host):\($0)" } ?? host
    }

    init(session: Session) { self.session = session }

    static func restore() -> ServerBackend? {
        Keychain.codable(Session.self, for: sessionKey).map { ServerBackend(session: $0) }
    }

    // MARK: Sign-in

    /// How this server signs its owner in. Octop Bot signs in with Lynxce accounts only.
    enum SignInMode: Equatable {
        /// Bot web build owned (or about to be claimed) by a Lynxce account.
        case lynxce(claimed: Bool)
        /// Multi-tenant (Octop Bot cloud): every Lynxce account signs in to its own account.
        case cloud
        /// Set up earlier with a local password: the first Lynxce sign-in also gives that password once.
        case legacy
        /// No Lynxce sign-in (a plain Octop server, or an Octop Bot too old to have it).
        case unsupported
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
        guard status["lynxce_login"] as? Bool == true else { return .unsupported }
        let identity = try? await anonymous(base, .get, "/api/auth/lynxce/status")
        // Octop Bot cloud: every Lynxce account signs in to its own account, nothing to claim.
        if identity?["cloud"] as? Bool == true { return .cloud }
        if identity?["legacy_owner"] as? Bool == true { return .legacy }
        return .lynxce(claimed: identity?["claimed"] as? Bool ?? false)
    }

    static func signInWithLynxce(_ base: URL, account: String, password: String, localPassword: String? = nil) async throws -> ServerBackend {
        var json = ["account": account, "password": password, "locale": Preferences.shared.language.isChinese ? "zh" : "en"]
        if let localPassword, !localPassword.isEmpty { json["local_password"] = localPassword }
        let body = try await anonymous(base, .post, "/api/auth/lynxce/login", json: json)
        return try finish(base, body)
    }

    enum CloudCheck: Equatable {
        case available
        /// The cloud answered but is not open (yet): a Lynxce sign-in talks to Lynxce directly.
        case closed
        /// No answer, even after a slower second try.
        case unreachable
    }

    /// Is Octop Bot cloud up? Until it is, a Lynxce sign-in talks to Lynxce directly.
    /// A slow network gets a second, longer try before it counts as unreachable.
    static func lynxceCloudAvailable() async -> CloudCheck {
        for timeout in [4.0, 10.0] {
            var request = URLRequest(url: lynxceCloud.appending(path: "/api/octop-bot/server-info"))
            request.timeoutInterval = timeout
            guard let (data, response) = try? await HTTP.session.data(for: request),
                  let http = response as? HTTPURLResponse
            else {
                if Task.isCancelled { return .unreachable }
                continue
            }
            guard http.statusCode == 200, let info = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                // A 5xx is the cloud having trouble, not the cloud being closed.
                if http.statusCode >= 500 { continue }
                return .closed
            }
            return isCloudInfo(info) ? .available : .closed
        }
        return .unreachable
    }

    static func isCloudInfo(_ info: [String: Any]) -> Bool {
        info["product"] as? String == "octop-bot" && info["edition"] as? String == "cloud"
    }

    /// Body for `/api/auth/lynxce/code` (no code) and `/api/auth/lynxce/code-login`; the server tells
    /// phone from email itself.
    static func lynxceCodeBody(target: String, code: String? = nil, chinese: Bool) -> [String: String] {
        var body = ["target": target.trimmingCharacters(in: .whitespacesAndNewlines), "locale": chinese ? "zh" : "en"]
        if let code { body["code"] = code }
        return body
    }

    /// Ask the server to have Lynxce text or email the owner a sign-in code.
    static func sendLynxceCode(_ base: URL, target: String) async throws {
        let chinese = Preferences.shared.language.isChinese
        _ = try await anonymous(base, .post, "/api/auth/lynxce/code", json: lynxceCodeBody(target: target, chinese: chinese))
    }

    static func signInWithLynxceCode(_ base: URL, target: String, code: String, localPassword: String? = nil) async throws -> ServerBackend {
        guard LynxceBackend.isCode(code) else { throw APIError(kind: .rejected, status: 400, message: L("error.codeFormat")) }
        let chinese = Preferences.shared.language.isChinese
        var json = lynxceCodeBody(target: target, code: code, chinese: chinese)
        if let localPassword, !localPassword.isEmpty { json["local_password"] = localPassword }
        let body = try await anonymous(base, .post, "/api/auth/lynxce/code-login", json: json)
        return try finish(base, body)
    }

    private static func finish(_ base: URL, _ body: [String: Any]) throws -> ServerBackend {
        guard let token = body["access_token"] as? String else { throw APIError(kind: .server, status: 502, message: nil) }
        let user = body["user"] as? [String: Any]
        // Never the username (`sso_…`, `owner`): with no display name the UI shows a generic name.
        let name = displayName(user)
        // Octop Bot cloud says so in its sign-in response; it then also serves the Lynxce wallet.
        let session = Session(baseURL: base, token: token, displayName: name, cloud: body["cloud"] as? Bool == true ? true : nil,
                              signupExpiryDay: body["cloud"] as? Bool == true ? signupExpiryDayUTC(body) : nil)
        Keychain.setCodable(session, for: sessionKey)
        let backend = ServerBackend(session: session)
        backend.signupCredits = backend.isCloud ? newSignupCredits(body) : nil
        return backend
    }

    static func displayName(_ user: [String: Any]?) -> String {
        ((user?["display_name"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    func accountPhoto() async -> AccountPhoto? {
        if isCloud, let profile = try? await json(.get, "/api/octop-bot/cloud/account") as? [String: Any] {
            return AccountPhoto.cloud(profile)
        }
        guard let me = try? await json(.get, "/api/auth/me") as? [String: Any] else { return nil }
        var photo = AccountPhoto(name: Self.displayName(me), url: me["avatar_url"] as? String)
        if let local = AccountPhoto.localAvatar(me),
           let request = try? HTTP.request(url(local.path, query: local.query), method: .get, headers: authHeaders),
           let (bytes, response) = try? await HTTP.session.data(for: request, delegate: NoAvatarRedirect()),
           (response as? HTTPURLResponse)?.statusCode == 200 {
            photo.localImage = bytes
        }
        return photo
    }

    private static func anonymous(_ base: URL, _ method: HTTPMethod, _ path: String, json: Any? = nil) async throws -> [String: Any] {
        let request = try HTTP.request(base.appending(path: path), method: method, json: json)
        let (data, response) = try await HTTP.data(for: request)
        guard (200..<300).contains(response.statusCode) else {
            throw APIError.from(status: response.statusCode, message: HTTP.errorMessage(data), code: HTTP.errorCode(data), details: HTTP.errorDetails(data))
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
            throw APIError.from(status: response.statusCode, message: HTTP.errorMessage(data), code: HTTP.errorCode(data), details: HTTP.errorDetails(data))
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
            isChief: chief,
            state: row["state"] as? String,
            preparing: row["preparing"] as? Bool ?? false,
            lastError: row["last_error"] as? String
        )
    }

    /// Same remapping as the dashboard's `visibleAppearance`.
    static func normalizedLook(shape: String?, color: String?, chief: Bool) -> Look {
        guard let shape, let color else { return chief ? .chief : .fallback }
        if shape == "whale" { return chief ? .chief : Look(shape: "gumdrop", color: color == "deepseek" ? "blue" : color) }
        return Look(shape: shape, color: color == "deepseek" ? "blue" : color)
    }

    func startBot(_ bot: BotProfile) async throws {
        _ = try await json(.post, "/api/agents/\(bot.id)/start")
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
        var rows: [[String: Any]] = []
        var seen = Set<String>()
        var offset = 0
        let path = "/api/agents/\(bot.id)/threads"
        var window: Int?
        while true {
            let limit = window ?? 50
            let query = ["limit": String(limit), "offset": String(window == nil ? offset : 0)]
            let page = try await json(.get, path, query: query) as? [[String: Any]] ?? []
            let additions = page.filter { ($0["thread_id"] as? String).map { seen.insert($0).inserted } ?? false }
            rows += additions
            if page.count < limit { break }
            if window != nil {
                if additions.isEmpty { break }
                window = limit * 2
            } else if additions.isEmpty {
                // Older servers ignore offset. Their limit can still reach earlier threads.
                window = (offset + 50)
            } else {
                offset += page.count
            }
        }
        return rows.compactMap { row in
            guard let id = row["thread_id"] as? String, row["has_messages"] as? Bool ?? true else { return nil }
            let date = (row["last_active"] as? String).flatMap(ISO8601.parse)
                ?? (row["last_active"] as? Double).map { Date(timeIntervalSince1970: $0 > 1e12 ? $0 / 1000 : $0) }
            let title = (row["title"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? L("chat.untitled")
            return ConversationSummary(id: id, title: title, updatedAt: date, botId: bot.id, owned: row["owned"] as? Bool, active: row["is_active"] as? Bool == true)
        }
        .sorted { ($0.updatedAt ?? .distantPast) > ($1.updatedAt ?? .distantPast) }
    }

    struct HistoryPosition: Equatable {
        var offset = 0
        var cursor: String?
    }

    struct HistoryPage {
        var rows: [[String: Any]]
        var next: HistoryPosition?
        var pause: HitlPause?
    }

    func historyPage(_ thread: String, bot: BotProfile, position: HistoryPosition = .init()) async throws -> HistoryPage {
        let limit = 60
        var query = ["limit": String(limit)]
        if let cursor = position.cursor { query["cursor"] = cursor } else { query["offset"] = String(position.offset) }
        for _ in 0..<20 {
            try Task.checkCancellation()
            let body = try await json(.get, "/api/agents/\(bot.id)/threads/\(thread)/history", query: query) as? [String: Any] ?? [:]
            if body["history_loading"] as? Bool == true {
                let wait = (body["history_retry_after_ms"] as? Double ?? 800) / 1000
                try await Task.sleep(for: .seconds(min(max(wait, 0.3), 3)))
                continue
            }
            let next = body["has_more"] as? Bool == true
                ? HistoryPosition(offset: position.offset + (body["limit"] as? Int ?? limit), cursor: body["next_cursor"] as? String)
                : nil
            return HistoryPage(rows: body["messages"] as? [[String: Any]] ?? [], next: next,
                               pause: HitlPause.parse(body["hitl_pending"], labels: toolLabels))
        }
        throw APIError.network
    }

    func historyMessages(_ rows: [[String: Any]], bot: BotProfile) -> [ChatMessage] {
        Self.history(rows, labels: toolLabels, agent: bot.id)
    }

    func messages(in conversation: ConversationSummary, bot: BotProfile) async throws -> [ChatMessage] {
        let page = try await historyPage(conversation.id, bot: bot)
        pauses[conversation.id] = page.pause
        return historyMessages(page.rows, bot: bot)
    }

    /// Server history rows → chat messages; tool rows are folded into the assistant's tool steps,
    /// and files a delivery tool sent become that reply's attachments.
    static func history(_ rows: [[String: Any]], labels: [String: String] = [:], agent: String? = nil) -> [ChatMessage] {
        var out: [ChatMessage] = []
        var pending: [FileAttachment] = []
        func attach(_ files: [FileAttachment], to index: Int) {
            for file in files where !out[index].attachments.contains(where: { $0.url == file.url }) {
                out[index].attachments.append(file)
            }
        }
        for row in rows {
            if row["role"] as? String == "tool" {
                guard let agent else { continue }
                let files = (row["content"] as? [[String: Any]] ?? [])
                    .filter { $0["type"] as? String == "tool_result" && FileAttachment.isDeliveryTool($0["name"] as? String) }
                    .flatMap { FileAttachment.fromToolOutput($0["output"], agent: (row["agent_id"] as? String) ?? agent) }
                if let last = out.indices.last, out[last].role == .assistant { attach(files, to: last) } else { pending += files }
                continue
            }
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
                // A paused turn also stores a summary row repeating its segments; skip what is already there.
                if Self.contains(last.text, text) { text = "" }
                if Self.contains(last.thinking, thinking) { thinking = "" }
                out[out.count - 1].text += (last.text.isEmpty || text.isEmpty ? "" : "\n\n") + text
                out[out.count - 1].thinking += thinking
                out[out.count - 1].tools += tools
                attach(pending, to: out.count - 1)
                pending = []
                if row["status"] as? String == "error", let stopped = Self.stoppedStatus(row["error_code"] as? String) {
                    out[out.count - 1].status = stopped
                }
                continue
            }
            var message = ChatMessage(role: role, text: text, thinking: thinking, tools: tools)
            if let ms = row["timestamp"] as? Double { message.createdAt = Date(timeIntervalSince1970: ms / 1000) }
            if row["status"] as? String == "error" {
                message.status = Self.stoppedStatus(row["error_code"] as? String) ?? .failed(L("chat.failed"))
            }
            if let id = row["id"] as? String { message.id = id }
            else if let seq = row["history_seq"] as? Int { message.id = "history-\(seq)" }
            if role == .assistant {
                message.attachments = pending
                pending = []
            }
            // A turn stopped by credits or the daily cap may have written nothing; it still shows as its card.
            if !message.text.isEmpty || !message.tools.isEmpty || !message.thinking.isEmpty || !message.attachments.isEmpty || message.status.isStoppedByLynxce {
                out.append(message)
            }
        }
        if !pending.isEmpty { out.append(ChatMessage(role: .assistant, text: "", attachments: pending)) }
        return out
    }

    /// History `error_code`s that render as a card instead of a red error.
    static func stoppedStatus(_ code: String?) -> MessageStatus? {
        if APIError.isCreditsRequired(code) { return .outOfCredits }
        if APIError.isDailyLimit(code) { return .dailyLimit }
        return nil
    }

    /// Whether `part` (non-empty) already appears in `whole`, ignoring whitespace.
    static func contains(_ whole: String, _ part: String) -> Bool {
        let squeeze = { (text: String) in text.filter { !$0.isWhitespace } }
        let needle = squeeze(part)
        return !needle.isEmpty && squeeze(whole).contains(needle)
    }

    func deleteConversation(_ conversation: ConversationSummary, bot: BotProfile) async throws {
        _ = try await raw(.delete, "/api/agents/\(bot.id)/threads/\(conversation.id)")
    }

    // MARK: Questions and approvals

    /// Open pauses seen in the last history load, per conversation.
    private var pauses: [String: HitlPause] = [:]

    func openPause(in conversation: ConversationSummary) -> HitlPause? { pauses[conversation.id] }

    func resume(
        _ pause: HitlPause, decisions: [[String: Any]], conversation: String, bot: BotProfile
    ) -> AsyncThrowingStream<StreamEvent, Error> {
        pauses[conversation] = nil
        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var body: [String: Any] = ["thread_id": conversation, "decisions": decisions]
                    if let id = pause.pendingId { body["pending_id"] = id }
                    var request = try HTTP.request(
                        url("/api/agents/\(bot.id)/chat/hitl/resume"), method: .post, headers: authHeaders, json: body
                    )
                    request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                    request.timeoutInterval = 600
                    let (bytes, response) = try await HTTP.session.bytes(for: request)
                    guard let http = response as? HTTPURLResponse else { throw APIError.network }
                    guard (200..<300).contains(http.statusCode) else {
                        var data = Data()
                        for try await byte in bytes { data.append(byte); if data.count > 16_384 { break } }
                        throw APIError.from(status: http.statusCode, message: HTTP.errorMessage(data), code: HTTP.errorCode(data), details: HTTP.errorDetails(data))
                    }
                    var mapper = ServerFrameMapper(labels: toolLabels, endsOnDone: true)
                    loop: for try await event in SSE.events(bytes) {
                        guard let frame = try? JSONSerialization.jsonObject(with: Data(event.data.utf8)) as? [String: Any] else { continue }
                        switch try mapper.map(frame) {
                        case .events(let events): events.forEach { continuation.yield($0) }
                        case .finished: break loop
                        }
                    }
                    continuation.yield(.done)
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: Task.isCancelled ? CancellationError() : (error as? APIError ?? APIError.network))
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    // MARK: Chat over WebSocket

    enum Observation {
        case status(active: Bool, turn: String?)
        case user(ChatMessage)
        case delta(StreamEvent)
        case finished
    }

    private func threadSocket(_ bot: BotProfile) -> URLSessionWebSocketTask {
        var components = URLComponents(url: url("/api/agents/\(bot.id)/chat/ws"), resolvingAgainstBaseURL: false)!
        components.scheme = components.scheme == "https" ? "wss" : "ws"
        components.queryItems = [URLQueryItem(name: "token", value: session.token)]
        return HTTP.session.webSocketTask(with: components.url!)
    }

    func observe(_ thread: String, bot: BotProfile) -> AsyncThrowingStream<Observation, Error> {
        AsyncThrowingStream { output in
            let socket = threadSocket(bot)
            let task = Task {
                defer { socket.cancel(with: .normalClosure, reason: nil) }
                do {
                    socket.resume()
                    try await socket.send(.string(Self.encode(["type": "subscribe", "thread_id": thread])))
                    var mapper = ServerFrameMapper(labels: toolLabels)
                    while !Task.isCancelled {
                        guard case .string(let raw) = try await socket.receive(),
                              let frame = try JSONSerialization.jsonObject(with: Data(raw.utf8)) as? [String: Any],
                              frame["thread_id"] as? String == thread else { continue }
                        switch frame["type"] as? String {
                        case "turn_status":
                            output.yield(.status(active: frame["active"] as? Bool == true, turn: frame["turn_id"] as? String))
                        case "turn.started", "turn.resumed":
                            output.yield(.status(active: true, turn: frame["turn_id"] as? String))
                        case "user":
                            let id = frame["message_id"] as? String ?? UUID().uuidString
                            let row = ChatMessage(id: id, role: .user, text: frame["content"] as? String ?? "",
                                                  authorName: (frame["author"] as? [String: Any])?["display_name"] as? String)
                            output.yield(.user(row))
                        case "turn.ended":
                            output.yield(.finished)
                            mapper = ServerFrameMapper(labels: toolLabels)
                        default:
                            if case .events(let events) = try mapper.map(frame) {
                                for event in events { output.yield(.delta(event)) }
                            }
                        }
                    }
                    output.finish()
                } catch { output.finish(throwing: error) }
            }
            output.onTermination = { _ in socket.cancel(with: .normalClosure, reason: nil); task.cancel() }
        }
    }

    func send(
        _ text: String, messageId: String, images: [Data], to bot: BotProfile, conversation: String?,
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
                        "messages": [["role": "user", "content": content, "id": messageId]],
                    ]
                    if let model { turn["model"] = model }
                    // Health, Calendar and Reminders run on this phone (PROTOCOL.md §C).
                    turn["device_tools"] = DeviceConnectors.shared.offeredTools

                    let ws = threadSocket(bot)
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

    // MARK: Usage

    struct UsageSummary: Equatable {
        struct Bucket: Equatable, Identifiable {
            var key: String
            var label: String
            var totalTokens: Int
            var id: String { key }
        }

        var totalTokens = 0
        var modelCalls = 0
        var buckets: [Bucket] = []

        static func parse(_ data: Any) -> UsageSummary {
            let body = data as? [String: Any] ?? [:]
            let number = { (value: Any?) in (value as? NSNumber)?.intValue ?? 0 }
            let rows = body["buckets"] as? [[String: Any]] ?? []
            return UsageSummary(
                totalTokens: number(body["total_tokens"]),
                modelCalls: number(body["model_calls"]),
                buckets: rows.compactMap { row in
                    let key = (row["key"] as? String) ?? (row["key"] as? NSNumber)?.stringValue ?? ""
                    let label = (row["label"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? key
                    let total = number(row["total_tokens"])
                    guard !label.isEmpty, total > 0 else { return nil }
                    return Bucket(key: key, label: label, totalTokens: total)
                }
            )
        }
    }

    /// The last 30 days, by Bot and by model.
    func usage() async throws -> (byBot: UsageSummary, byModel: UsageSummary) {
        async let bots = usage(by: "by_agent")
        async let models = usage(by: "by_model")
        return (try await bots, try await models)
    }

    private func usage(by granularity: String) async throws -> UsageSummary {
        UsageSummary.parse(try await json(.get, "/api/usage/summary", query: ["window": "last_30d", "granularity": granularity]))
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
    /// The HITL resume stream ends with `done`; the socket ends with `turn.ended`.
    var endsOnDone = false

    init(labels: [String: String] = [:], endsOnDone: Bool = false) {
        self.labels = labels
        self.endsOnDone = endsOnDone
    }

    mutating func map(_ frame: [String: Any]) throws -> Outcome {
        switch frame["type"] as? String {
        case "turn.started", "turn.resumed":
            return .events((frame["turn_id"] as? String).map { [.turnStarted($0)] } ?? [])
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
        case "attachment":
            return .events(FileAttachment.fromFrame(frame).map { [.attachment($0)] } ?? [])
        case "error":
            throw Self.error(frame)
        case "hitl_required":
            guard let pause = HitlPause.parse(frame["request"], labels: labels) else {
                throw APIError(kind: .rejected, status: 409, message: L("chat.needsApproval"))
            }
            return .events([.pause(pause)])
        case "done" where endsOnDone:
            return .finished
        case "turn.ended":
            if frame["failed"] as? Bool == true { throw Self.error(frame, message: false) }
            return .finished
        default:
            return .events([])
        }
    }

    /// An error frame keeps its `error_code`, so running out of credits is told apart from a failure.
    static func error(_ frame: [String: Any], message: Bool = true) -> APIError {
        let text = message ? frame["message"] as? String : nil
        if APIError.isDailyLimit(frame["error_code"] as? String) {
            return APIError(kind: .dailyLimit, status: 429, message: text)
        }
        if APIError.isCreditsRequired(frame["error_code"] as? String) {
            return APIError(kind: .credits, status: 402, message: text, code: frame["error_code"] as? String, details: CreditDetails((frame["error_details"] ?? frame["details"]) as? [String: Any]))
        }
        if frame["error_code"] as? String == "insufficient_balance" || text == "octop:stream_errors.insufficient_balance" || text == "The model provider rejected this request due to insufficient balance or quota. Top up or upgrade the plan for this API key, then try again." || text == "模型服务返回余额或额度不足。请为该 API Key 对应的账户充值或升级套餐后再试。" {
            return APIError(kind: .server, status: 500, message: L("error.providerBalance"))
        }
        return APIError(kind: .server, status: 500, message: text)
    }
}


private final class NoAvatarRedirect: NSObject, URLSessionTaskDelegate {
    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                                newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
