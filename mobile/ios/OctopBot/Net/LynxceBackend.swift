import Foundation
import UIKit

/// Signed in with a personal Lynxce (灵策智算) account: chat goes straight to the Lynxce model gateway and
/// conversations sync through Lynxce web-chat sessions, so they also appear in Octop Bot on the desktop.
final class LynxceBackend: ChatBackend {
    struct Grant: Codable {
        var accountId: String
        var displayName: String?
        var accessToken: String
        var refreshToken: String
    }

    static let origin = URL(string: "https://api.lynxce.cn")!
    /// Same prefix the desktop client uses, so desktop and phone list each other's conversations.
    static let sessionPrefix = "octop-bot-v1-"
    private static let grantKey = "lynxce.grant"

    private(set) var grant: Grant
    private let bots: LocalBots
    private var refreshing: Task<Grant, Error>?

    var supportsGroups: Bool { false }
    /// Never the raw account id: with no display name the UI shows a generic name.
    var accountName: String {
        let name = (grant.displayName ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return name.isEmpty ? L("account.genericName") : name
    }

    init(grant: Grant, bots: LocalBots = .shared) {
        self.grant = grant
        self.bots = bots
    }

    static func restore() -> LynxceBackend? {
        Keychain.codable(Grant.self, for: grantKey).map { LynxceBackend(grant: $0) }
    }

    static func signIn(account: String, password: String) async throws -> LynxceBackend {
        try signedIn(try await call(.post, "/api/auth/password-login", json: ["account": account, "password": password]))
    }

    /// Where a verification code goes: an email when the text has "@", otherwise a phone number
    /// (Lynxce normalizes China numbers itself, so it is sent as typed).
    enum CodeTarget: Equatable {
        case phone(String)
        case email(String)

        init?(_ text: String) {
            let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !value.isEmpty else { return nil }
            self = value.contains("@") ? .email(value) : .phone(value)
        }

        var isEmail: Bool { if case .email = self { true } else { false } }

        /// The code request; email codes are written in the app's language.
        func codeRequest(chinese: Bool) -> (path: String, body: [String: String]) {
            switch self {
            case .phone(let phone): ("/api/auth/phone-code", ["phone": phone])
            case .email(let email): ("/api/auth/email-code", ["email": email, "locale": chinese ? "zh-CN" : "en"])
            }
        }

        func loginRequest(code: String) -> (path: String, body: [String: String]) {
            switch self {
            case .phone(let phone): ("/api/auth/phone-login", ["phone": phone, "code": code])
            case .email(let email): ("/api/auth/email-login", ["email": email, "code": code])
            }
        }
    }

    static func isCode(_ text: String) -> Bool {
        text.count == 6 && text.allSatisfy { $0.isASCII && $0.isNumber }
    }

    /// Send a sign-in code. The response's `devCode` is deliberately never read.
    static func requestCode(target: CodeTarget) async throws {
        let request = target.codeRequest(chinese: Preferences.shared.language.isChinese)
        _ = try await call(.post, request.path, json: request.body)
    }

    /// Sign in with a code; Lynxce creates the account when it is new, so no password is needed.
    static func signIn(target: CodeTarget, code: String) async throws -> LynxceBackend {
        guard isCode(code) else { throw APIError(kind: .rejected, status: 400, message: L("error.codeFormat")) }
        let request = target.loginRequest(code: code)
        return try signedIn(try await call(.post, request.path, json: request.body))
    }

    /// Friendly text for a failed code send or code sign-in.
    static func codeMessage(for error: Error) -> String {
        guard let error = error as? APIError else { return error.localizedDescription }
        switch error.status {
        case 401: return L("error.codeInvalid")
        case 429: return L("error.tooFrequent")
        default: return error.localizedDescription
        }
    }

    /// Store the grant a login returns (`{accessToken, refreshToken, user}`) and start a backend with it.
    private static func signedIn(_ data: Any) throws -> LynxceBackend {
        guard
            let body = data as? [String: Any],
            let user = body["user"] as? [String: Any],
            let id = user["id"] as? String,
            let access = body["accessToken"] as? String,
            let refresh = body["refreshToken"] as? String
        else { throw APIError(kind: .server, status: 502, message: nil) }
        let grant = Grant(accountId: id, displayName: user["displayName"] as? String, accessToken: access, refreshToken: refresh)
        Keychain.setCodable(grant, for: grantKey)
        return LynxceBackend(grant: grant)
    }

    // MARK: Transport

    /// Picks Octop Bot's App Store products on Lynxce's in-app purchase endpoints without moving
    /// the sign-in out of the multi-session 'web' channel.
    nonisolated static let iapApp = "cn.lynxce.octopbot"

    private static func headers(_ bearer: String?, iap: Bool = false) -> [String: String] {
        // 'web' is Lynxce's multi-session channel; signing in here never signs other devices out.
        var headers = ["X-Lynxce-Client": "web"]
        if let bearer { headers["Authorization"] = "Bearer \(bearer)" }
        if iap { headers["X-Lynxce-Iap-App"] = iapApp }
        return headers
    }

    private static func url(_ path: String, query: [String: String] = [:]) -> URL {
        var components = URLComponents(url: origin.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { components.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) } }
        return components.url!
    }

    /// Lynxce wraps results as `{code: 0, data}`; anything else is a failure.
    static func unwrap(_ data: Data, status: Int) throws -> Any {
        let object = try? JSONSerialization.jsonObject(with: data)
        guard (200..<300).contains(status) else {
            throw APIError.from(status: status, message: HTTP.errorMessage(data), code: HTTP.errorCode(data))
        }
        guard let envelope = object as? [String: Any], let code = envelope["code"] as? Int else {
            throw APIError(kind: .server, status: 502, message: nil)
        }
        guard code == 0 else {
            let status = code == 402 ? 402 : (code == 401 ? 401 : 400)
            throw APIError.from(status: status, message: envelope["message"] as? String, code: HTTP.errorCode(data))
        }
        return envelope["data"] ?? NSNull()
    }

    private static func call(
        _ method: HTTPMethod, _ path: String, bearer: String? = nil,
        query: [String: String] = [:], json: Any? = nil, form: [FormPart]? = nil, iap: Bool = false
    ) async throws -> Any {
        let request = try HTTP.request(url(path, query: query), method: method, headers: headers(bearer, iap: iap), json: json, form: form)
        let (data, response) = try await HTTP.data(for: request)
        return try unwrap(data, status: response.statusCode)
    }

    /// Authenticated call that rotates the access token once on 401.
    private func call(
        _ method: HTTPMethod, _ path: String, query: [String: String] = [:], json: Any? = nil, form: [FormPart]? = nil,
        iap: Bool = false
    ) async throws -> Any {
        do {
            return try await Self.call(method, path, bearer: grant.accessToken, query: query, json: json, form: form, iap: iap)
        } catch let error as APIError where error.kind == .unauthorized {
            let fresh = try await refreshed()
            return try await Self.call(method, path, bearer: fresh.accessToken, query: query, json: json, form: form, iap: iap)
        }
    }

    private func refreshed() async throws -> Grant {
        if let refreshing { return try await refreshing.value }
        let current = grant
        let task = Task { () throws -> Grant in
            let data = try await Self.call(.post, "/api/auth/refresh", json: ["refreshToken": current.refreshToken])
            guard let body = data as? [String: Any], let access = body["accessToken"] as? String else {
                throw APIError(kind: .unauthorized, status: 401, message: nil)
            }
            var next = current
            next.accessToken = access
            if let refresh = body["refreshToken"] as? String { next.refreshToken = refresh }
            return next
        }
        refreshing = task
        defer { refreshing = nil }
        do {
            let next = try await task.value
            grant = next
            Keychain.setCodable(next, for: Self.grantKey)
            return next
        } catch {
            throw APIError(kind: .unauthorized, status: 401, message: nil)
        }
    }

    // MARK: Bots and conversations

    func bots() async throws -> [BotProfile] { bots.all }

    private var sessionBots: [String: String] {
        get { UserDefaults.standard.dictionary(forKey: "lynxce.sessionBots") as? [String: String] ?? [:] }
        set { UserDefaults.standard.set(newValue, forKey: "lynxce.sessionBots") }
    }

    func conversations(for bot: BotProfile) async throws -> [ConversationSummary] {
        let data = try await call(.get, "/api/user/web-chat-sessions", query: ["limit": "50"])
        let items = (data as? [String: Any])?["items"] as? [[String: Any]] ?? []
        let owners = sessionBots
        return items.compactMap { item in
            guard let id = item["id"] as? String, id.hasPrefix(Self.sessionPrefix) else { return nil }
            let owner = owners[id] ?? LocalBots.chiefId
            guard owner == bot.id else { return nil }
            return ConversationSummary(
                id: id,
                title: (item["title"] as? String).map { $0.components(separatedBy: "\n")[0] } ?? "",
                updatedAt: ISO8601.parse(item["updatedAt"] as? String),
                botId: owner
            )
        }
    }

    func messages(in conversation: ConversationSummary, bot: BotProfile) async throws -> [ChatMessage] {
        let id = conversation.id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? conversation.id
        let data = try await call(.get, "/api/user/web-chat-sessions/\(id)")
        let items = (data as? [String: Any])?["items"] as? [[String: Any]] ?? []
        return items.compactMap { item in
            guard let role = (item["role"] as? String).flatMap(MessageRole.init(rawValue:)), role != .system else { return nil }
            var message = ChatMessage(role: role, text: Self.stripRole(item["content"] as? String ?? ""))
            message.thinking = item["thinking"] as? String ?? ""
            message.createdAt = ISO8601.parse(item["createdAt"] as? String) ?? .now
            if item["status"] as? String == "failed" { message.status = .failed(L("chat.failed")) }
            return message
        }
    }

    /// Desktop Bot tags the user's first message with a role block; hide it on the phone too.
    static func stripRole(_ text: String) -> String {
        guard let range = text.range(of: "\n\n[Octop Bot role/v1] ", options: .backwards) else { return text }
        return String(text[..<range.lowerBound])
    }

    func deleteConversation(_ conversation: ConversationSummary, bot: BotProfile) async throws {
        let id = conversation.id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? conversation.id
        _ = try await call(.delete, "/api/user/web-chat-sessions/\(id)")
        sessionBots[conversation.id] = nil
    }

    func models() async throws -> [ModelOption] {
        let data = try await call(.get, "/api/models/available")
        let rows = (data as? [[String: Any]])
            ?? ((data as? [String: Any])?["items"] as? [[String: Any]])
            ?? ((data as? [String: Any])?["models"] as? [[String: Any]])
            ?? []
        return rows.compactMap { row in
            guard let id = row["modelId"] as? String else { return nil }
            return ModelOption(id: id, name: row["modelName"] as? String ?? id, supportsImage: row["supportsImage"] as? Bool ?? false)
        }
    }

    // MARK: Chat

    private var running: [String: Task<Void, Never>] = [:]
    /// Turns waiting on device tools the phone runs (PROTOCOL.md §C, Lynxce mode), by conversation.
    private var loops: [String: ToolLoop] = [:]
    private static let maxToolRounds = 6

    /// One turn's function-calling loop: the request so far and what to sync when it ends.
    struct ToolLoop {
        var body: [String: Any]
        var user: String
        var startedAt: Date
        var model: String?
        var answer = ""
        var thinking = ""
        var rounds = 0
        var pendingId = ""
    }

    func send(
        _ text: String, images: [Data], to bot: BotProfile, conversation: String?,
        history: [ChatMessage], model: String?
    ) -> AsyncThrowingStream<StreamEvent, Error> {
        let sessionId = conversation ?? Self.sessionPrefix + UUID().uuidString.lowercased()
        loops[sessionId] = nil
        let tools = DeviceConnectors.shared.offeredSpecs.map(\.openAITool)
        let body = Self.chatBody(
            text: text, images: images, bot: bot, history: history, sessionId: sessionId, model: model, tools: tools
        )
        let loop = ToolLoop(body: body, user: text, startedAt: Date(), model: model)
        return run(loop, sessionId: sessionId, announce: conversation == nil ? bot : nil)
    }

    func resume(
        _ pause: HitlPause, decisions: [[String: Any]], conversation: String, bot: BotProfile
    ) -> AsyncThrowingStream<StreamEvent, Error> {
        guard var loop = loops.removeValue(forKey: conversation), loop.pendingId == pause.id else {
            return AsyncThrowingStream { $0.finish(throwing: APIError(kind: .server, status: 409, message: L("device.expired"))) }
        }
        loop.body["messages"] = Self.answering(loop.body["messages"], decisions: decisions)
        return run(loop, sessionId: conversation, announce: nil)
    }

    func openPause(in conversation: ConversationSummary) -> HitlPause? { nil }

    /// Stream completions until the model answers without tool calls, or pauses for the phone's tools.
    private func run(_ start: ToolLoop, sessionId: String, announce bot: BotProfile?) -> AsyncThrowingStream<StreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                var loop = start
                if let bot {
                    sessionBots[sessionId] = bot.id
                    continuation.yield(.conversation(sessionId))
                }
                do {
                    while true {
                        var calls = ToolCallAccumulator()
                        var text = ""
                        if loop.rounds >= Self.maxToolRounds { loop.body["tools"] = nil; loop.body["tool_choice"] = nil }
                        var body = loop.body
                        try await streamWithToolFallback(&body, calls: &calls) { event in
                            switch event {
                            case .text(let delta): text += delta
                            case .thinking(let delta): loop.thinking += delta
                            default: break
                            }
                            continuation.yield(event)
                        }
                        loop.body = body
                        loop.answer += text
                        let made = calls.calls
                        guard !made.isEmpty else { break }
                        loop.rounds += 1
                        var messages = loop.body["messages"] as? [[String: Any]] ?? []
                        messages.append(ToolCallAccumulator.assistantMessage(text: text, calls: made))
                        loop.body["messages"] = messages
                        for call in made {
                            continuation.yield(.tool(id: call.id, name: DeviceConnectors.isDeviceTool(call.name) ? L("device.tool.\(call.name)") : call.name, done: false))
                        }
                        let pending = "local-" + UUID().uuidString.lowercased()
                        let raw: [String: Any] = [
                            "pending_id": pending,
                            "action_requests": made.map { ["name": $0.name, "args": $0.arguments] },
                        ]
                        if let pause = HitlPause.parse(raw) {
                            loop.pendingId = pause.id
                            loops[sessionId] = loop
                            continuation.yield(.pause(pause))
                        }
                        // The chat answers the pause (at once for reads) and `resume` carries on.
                        continuation.yield(.done)
                        continuation.finish()
                        running[sessionId] = nil
                        return
                    }
                    continuation.yield(.done)
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
                await sync(sessionId: sessionId, user: loop.user, startedAt: loop.startedAt, answer: loop.answer, thinking: loop.thinking, model: loop.model)
                running[sessionId] = nil
            }
            running[sessionId] = task
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    /// The model's tool calls answered in order: a result, or the user's refusal.
    static func answering(_ messages: Any?, decisions: [[String: Any]]) -> [[String: Any]] {
        var list = messages as? [[String: Any]] ?? []
        let calls = (list.last?["tool_calls"] as? [[String: Any]]) ?? []
        for (index, call) in calls.enumerated() {
            let decision = index < decisions.count ? decisions[index] : [:]
            let content: String
            if decision["type"] as? String == "respond", let message = decision["message"] as? String {
                content = message
            } else {
                content = DeviceConnectors.json(["error": (decision["message"] as? String) ?? "The user declined."])
            }
            list.append(["role": "tool", "tool_call_id": call["id"] as? String ?? "", "content": content])
        }
        return list
    }

    /// Some gateway models refuse `tools`: then ask once more without them.
    private func streamWithToolFallback(
        _ body: inout [String: Any], calls: inout ToolCallAccumulator, onEvent: (StreamEvent) -> Void
    ) async throws {
        do {
            try await streamCompletion(body, calls: &calls, onEvent: onEvent)
        } catch let error as APIError where error.status == 400 && body["tools"] != nil {
            body["tools"] = nil
            body["tool_choice"] = nil
            calls = ToolCallAccumulator()
            try await streamCompletion(body, calls: &calls, onEvent: onEvent)
        }
    }

    static func chatBody(
        text: String, images: [Data], bot: BotProfile, history: [ChatMessage], sessionId: String, model: String?,
        tools: [[String: Any]] = [], now: Date = .now, zone: TimeZone = .current
    ) -> [String: Any] {
        var messages: [[String: Any]] = []
        if let prompt = bot.systemPrompt, !prompt.isEmpty {
            messages.append(["role": "system", "content": prompt])
        }
        if !tools.isEmpty {
            // Device tools take local times; the model needs to know "now" to resolve "tomorrow afternoon".
            messages.append(["role": "system", "content": "Now: \(DeviceDates.stamp(now, zone: zone)) (\(zone.identifier))."])
        }
        for message in history.suffix(20) where message.status == .done && !message.text.isEmpty {
            messages.append(["role": message.role.rawValue, "content": message.text])
        }
        if images.isEmpty {
            messages.append(["role": "user", "content": text])
        } else {
            var parts: [[String: Any]] = [["type": "text", "text": text]]
            for image in images {
                parts.append(["type": "image_url", "image_url": ["url": "data:image/jpeg;base64," + image.base64EncodedString()]])
            }
            messages.append(["role": "user", "content": parts])
        }
        var body: [String: Any] = [
            "messages": messages,
            "stream": true,
            "stream_options": ["include_usage": true],
            "sessionId": sessionId,
            "metadata": ["client": "octop-bot-ios", "turnId": UUID().uuidString.lowercased()],
        ]
        if let model { body["model"] = model }
        if !tools.isEmpty {
            body["tools"] = tools
            body["tool_choice"] = "auto"
        }
        return body
    }

    private func streamCompletion(
        _ body: [String: Any], calls: inout ToolCallAccumulator, onEvent: (StreamEvent) -> Void
    ) async throws {
        func open(_ token: String) async throws -> (URLSession.AsyncBytes, HTTPURLResponse) {
            var request = try HTTP.request(Self.url("/api/proxy/v1/chat/completions"), method: .post, headers: Self.headers(token), json: body)
            request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
            request.timeoutInterval = 300
            let (bytes, response): (URLSession.AsyncBytes, URLResponse)
            do {
                (bytes, response) = try await HTTP.session.bytes(for: request)
            } catch {
                if Task.isCancelled { throw CancellationError() }
                throw APIError.network
            }
            guard let http = response as? HTTPURLResponse else { throw APIError.network }
            return (bytes, http)
        }
        var (bytes, response) = try await open(grant.accessToken)
        if response.statusCode == 401 {
            (bytes, response) = try await open(try await refreshed().accessToken)
        }
        guard (200..<300).contains(response.statusCode) else {
            var data = Data()
            for try await byte in bytes { data.append(byte); if data.count > 16_384 { break } }
            throw APIError.from(status: response.statusCode, message: HTTP.errorMessage(data), code: HTTP.errorCode(data))
        }
        var completed = false
        for try await event in SSE.events(bytes) {
            if event.data == "[DONE]" { completed = true; break }
            for parsed in try Self.parseChunk(event.data) { onEvent(parsed) }
            calls.add(event.data)
        }
        if !completed && !Task.isCancelled { throw APIError.network }
    }

    /// One OpenAI-style chunk → text / thinking deltas. Error chunks throw.
    static func parseChunk(_ data: String) throws -> [StreamEvent] {
        guard let object = try? JSONSerialization.jsonObject(with: Data(data.utf8)) as? [String: Any] else { return [] }
        if let error = object["error"] {
            let message = (error as? [String: Any])?["message"] as? String ?? error as? String
            let code = (error as? [String: Any])?["code"] as? String
            if APIError.isDailyLimit(code) { throw APIError(kind: .dailyLimit, status: 429, message: message) }
            throw APIError(kind: isCreditError(error) ? .credits : .server, status: isCreditError(error) ? 402 : 500, message: message)
        }
        guard let choice = (object["choices"] as? [[String: Any]])?.first,
              let delta = choice["delta"] as? [String: Any] else { return [] }
        var events: [StreamEvent] = []
        if let reasoning = (delta["reasoning_content"] ?? delta["reasoning"]) as? String, !reasoning.isEmpty {
            events.append(.thinking(reasoning))
        }
        if let content = delta["content"] as? String, !content.isEmpty {
            events.append(.text(content))
        }
        return events
    }

    /// An OpenAI-style error object that means the wallet is empty.
    static func isCreditError(_ error: Any) -> Bool {
        guard let error = error as? [String: Any] else { return false }
        if (error["code"] as? NSNumber)?.intValue == 402 || (error["status"] as? NSNumber)?.intValue == 402 { return true }
        let tags = [error["code"], error["type"]].compactMap { ($0 as? String)?.lowercased() }
        if tags.contains(where: { $0.contains("credit_limit_reached") }) { return false }
        return tags.contains { $0 == APIError.creditsRequired.lowercased() || $0.contains("insufficient") }
    }

    /// Append the finished turn to the synced Lynxce session (idempotent on the server).
    private func sync(sessionId: String, user: String, startedAt: Date, answer: String, thinking: String, model: String?) async {
        var items: [[String: Any]] = [["role": "user", "content": String(user.prefix(20_000)), "createdAt": ISO8601.string(startedAt)]]
        let trimmed = answer.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty {
            var reply: [String: Any] = ["role": "assistant", "content": String(trimmed.prefix(40_000)), "createdAt": ISO8601.string(.now)]
            if !thinking.isEmpty { reply["thinking"] = String(thinking.prefix(20_000)) }
            if let model { reply["model"] = model }
            items.append(reply)
        }
        let title = String(user.trimmingCharacters(in: .whitespacesAndNewlines).prefix(40))
        let id = sessionId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? sessionId
        _ = try? await call(.post, "/api/user/web-chat-sessions/\(id)/items", json: [
            "title": title.isEmpty ? "Octop Bot" : title,
            "model": model ?? "auto",
            "items": items,
        ])
    }

    func stop(conversation: String, bot: BotProfile) async {
        running[conversation]?.cancel()
    }

    // MARK: Voice, push, account

    func transcribe(_ audio: Data) async throws -> String? {
        let lang = Preferences.shared.language.isChinese ? "zh" : "en"
        let data = try await call(.post, "/api/asr/recognize", form: [
            FormPart(name: "langType", value: lang),
            FormPart(name: "file", file: audio, filename: "voice.m4a", mimeType: "audio/mp4"),
        ])
        let body = data as? [String: Any]
        return (body?["text"] as? String) ?? (body?["result"] as? [String])?.first
    }

    func speech(for text: String) async throws -> Data? {
        let data = try await call(.post, "/api/tts/synthesize", json: ["text": String(text.prefix(600)), "format": "mp3"])
        return ((data as? [String: Any])?["audioBase64"] as? String).flatMap { Data(base64Encoded: $0) }
    }

    func registerPush(token: String) async {
        _ = try? await call(.post, "/api/user/push-devices", json: [
            "platform": "ios",
            "token": token,
            "bundleId": Bundle.main.bundleIdentifier ?? "cn.lynxce.octopbot",
            "appVersion": Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0",
            "deviceName": UIDevice.current.model,
        ])
    }

    func wallet() async throws -> Wallet {
        guard let credits = Self.credits(inQuota: try await call(.get, "/api/user/quota")) else {
            throw APIError(kind: .server, status: 502, message: nil)
        }
        return Wallet(credits: credits, accountId: grant.accountId)
    }

    /// The wallet balance from `/api/user/quota`, the figure a recharge adds to. (`effectiveCreditsRemaining`
    /// can instead be an enterprise member's monthly allowance, so it is not shown next to "Recharge".)
    static func credits(inQuota data: Any) -> Double? {
        ((data as? [String: Any])?["creditsRemaining"] as? NSNumber)?.doubleValue
    }

    /// Credits have a cent quantum. Grouped whole numbers, with two decimals only below 1,000 and only
    /// when there is a fraction: 4,454,029.04 → "4,454,029", 12.5 → "12.50", 12 → "12".
    static func formatCredits(_ value: Double) -> String {
        let cents = (value * 100).rounded()
        let small = abs(cents) < 100_000 && cents.truncatingRemainder(dividingBy: 100) != 0
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.usesGroupingSeparator = true
        formatter.groupingSeparator = ","
        formatter.minimumFractionDigits = small ? 2 : 0
        formatter.maximumFractionDigits = small ? 2 : 0
        // Large balances drop their cents rather than round up past what the wallet holds.
        formatter.roundingMode = small ? .halfEven : .down
        return formatter.string(from: NSNumber(value: cents / 100)) ?? String(value)
    }

    /// Whole token counts, grouped: 1234567 → "1,234,567".
    static func formatCount(_ value: Int) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.usesGroupingSeparator = true
        formatter.groupingSeparator = ","
        return formatter.string(from: NSNumber(value: value)) ?? String(value)
    }

    // MARK: Credit packs (App Store)

    struct CreditPack: Identifiable, Equatable {
        let id: String
        let name: String
        let credits: Double
        let productId: String
    }

    /// Packs sold in this app, and whether Lynxce has App Store purchases switched on for it.
    func creditPacks() async throws -> (packs: [CreditPack], enabled: Bool) {
        Self.creditPacks(from: try await call(.get, "/api/billing/app/recharge-packages", iap: true))
    }

    static func creditPacks(from data: Any) -> (packs: [CreditPack], enabled: Bool) {
        let body = data as? [String: Any] ?? [:]
        let rows = body["packages"] as? [[String: Any]] ?? []
        let packs = rows.compactMap { row -> CreditPack? in
            guard let id = row["id"] as? String, let product = row["appleProductId"] as? String, !product.isEmpty else { return nil }
            return CreditPack(id: id, name: row["name"] as? String ?? "", credits: (row["credits"] as? NSNumber)?.doubleValue ?? 0, productId: product)
        }
        let apple = (body["payment"] as? [String: Any])?["apple"] as? [String: Any]
        return (packs, apple?["enabled"] as? Bool ?? false)
    }

    /// Lynxce ties the purchase to this account through the returned App Store account token.
    func purchaseIntent(packId: String) async throws -> (productId: String, accountToken: UUID) {
        try Self.intent(from: try await call(.post, "/api/billing/apple/purchase-intents", json: ["packageId": packId], iap: true))
    }

    /// Report a StoreKit transaction; Lynxce verifies it with Apple and credits the wallet once.
    func submitTransaction(_ signedTransaction: String) async throws {
        _ = try await call(.post, "/api/billing/apple/transactions", json: ["signedTransaction": signedTransaction], iap: true)
    }

    /// App Store rule 5.1.1(v): accounts created in the app can be deleted in the app. Lynxce keeps a
    /// cooling-off period before erasing the account; signing in is refused from now on.
    func requestDeletion() async throws -> Int? {
        let data = try await call(.post, "/api/user/account/deletion-request", json: ["confirm": "注销账号"])
        return ((data as? [String: Any])?["coolingDays"] as? NSNumber)?.intValue
    }

    func signOut() async {
        for task in running.values { task.cancel() }
        _ = try? await Self.call(.post, "/api/auth/logout", bearer: grant.accessToken, json: [:])
        Keychain.set(nil, for: Self.grantKey)
    }
}
