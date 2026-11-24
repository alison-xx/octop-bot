import Foundation

/// The OpenAI-style chat loop the phone runs itself (Lynxce, the user's own keys, a local model
/// server): stream a completion, and when the model calls the phone's device tools, pause for the
/// user and carry on in `resume`.
final class CompletionChat {
    /// One turn's function-calling loop: the request so far and what to keep when it ends.
    struct Turn {
        var body: [String: Any]
        var user: String
        var startedAt: Date
        var model: String?
        /// Set when the phone calls the model itself rather than through Lynxce.
        var endpoint: ModelEndpoint?
        var answer = ""
        var thinking = ""
        var rounds = 0
        var pendingId = ""
    }

    typealias Stream = (_ turn: Turn, _ body: [String: Any], _ calls: inout ToolCallAccumulator, _ onEvent: (StreamEvent) -> Void) async throws -> Void

    static let maxToolRounds = 6

    private let stream: Stream
    private let finished: (_ turn: Turn, _ sessionId: String) async -> Void
    private var running: [String: Task<Void, Never>] = [:]
    /// Turns waiting on device tools the phone runs (PROTOCOL.md §C), by conversation.
    private var loops: [String: Turn] = [:]

    init(stream: @escaping Stream, finished: @escaping (Turn, String) async -> Void) {
        self.stream = stream
        self.finished = finished
    }

    func start(_ turn: Turn, sessionId: String, announce: (() -> Void)?) -> AsyncThrowingStream<StreamEvent, Error> {
        loops[sessionId] = nil
        return run(turn, sessionId: sessionId, announce: announce)
    }

    func resume(_ pause: HitlPause, decisions: [[String: Any]], conversation: String) -> AsyncThrowingStream<StreamEvent, Error> {
        guard var turn = loops.removeValue(forKey: conversation), turn.pendingId == pause.id else {
            return AsyncThrowingStream { $0.finish(throwing: APIError(kind: .server, status: 409, message: L("device.expired"))) }
        }
        turn.body["messages"] = LynxceBackend.answering(turn.body["messages"], decisions: decisions)
        return run(turn, sessionId: conversation, announce: nil)
    }

    func stop(_ conversation: String) {
        running[conversation]?.cancel()
    }

    func cancelAll() {
        for task in running.values { task.cancel() }
    }

    /// Stream completions until the model answers without tool calls, or pauses for the phone's tools.
    private func run(_ start: Turn, sessionId: String, announce: (() -> Void)?) -> AsyncThrowingStream<StreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                var turn = start
                if let announce {
                    announce()
                    continuation.yield(.conversation(sessionId))
                }
                do {
                    while true {
                        var calls = ToolCallAccumulator()
                        var text = ""
                        if turn.rounds >= Self.maxToolRounds { turn.body["tools"] = nil; turn.body["tool_choice"] = nil }
                        var body = turn.body
                        var thinking = ""
                        try await streamWithToolFallback(turn, &body, calls: &calls) { event in
                            switch event {
                            case .text(let delta): text += delta
                            case .thinking(let delta): thinking += delta
                            default: break
                            }
                            continuation.yield(event)
                        }
                        turn.thinking += thinking
                        turn.body = body
                        turn.answer += text
                        let made = calls.calls
                        guard !made.isEmpty else { break }
                        turn.rounds += 1
                        var messages = turn.body["messages"] as? [[String: Any]] ?? []
                        messages.append(ToolCallAccumulator.assistantMessage(text: text, calls: made))
                        turn.body["messages"] = messages
                        for call in made {
                            continuation.yield(.tool(id: call.id, name: DeviceConnectors.isDeviceTool(call.name) ? L("device.tool.\(call.name)") : call.name, done: false))
                        }
                        let raw: [String: Any] = [
                            "pending_id": "local-" + UUID().uuidString.lowercased(),
                            "action_requests": made.map { ["name": $0.name, "args": $0.arguments] },
                        ]
                        if let pause = HitlPause.parse(raw) {
                            turn.pendingId = pause.id
                            loops[sessionId] = turn
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
                await finished(turn, sessionId)
                running[sessionId] = nil
            }
            running[sessionId] = task
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    /// Some models refuse `tools`: then ask once more without them.
    private func streamWithToolFallback(
        _ turn: Turn, _ body: inout [String: Any], calls: inout ToolCallAccumulator, onEvent: (StreamEvent) -> Void
    ) async throws {
        do {
            try await stream(turn, body, &calls, onEvent)
        } catch let error as APIError where error.status == 400 && body["tools"] != nil {
            body["tools"] = nil
            body["tool_choice"] = nil
            calls = ToolCallAccumulator()
            try await stream(turn, body, &calls, onEvent)
        }
    }

    // MARK: The user's own endpoint

    /// The request as a vendor takes it: Lynxce's own fields dropped, the endpoint's model set.
    static func vendorBody(_ body: [String: Any], model: String) -> [String: Any] {
        var body = body
        body["model"] = model
        for key in ["sessionId", "metadata", "stream_options"] { body[key] = nil }
        return body
    }

    /// Stream from an OpenAI-compatible endpoint the phone calls itself (a vendor or a local server).
    static func streamEndpoint(
        _ endpoint: ModelEndpoint, _ body: [String: Any], calls: inout ToolCallAccumulator, onEvent: (StreamEvent) -> Void
    ) async throws {
        var request = try HTTP.request(endpoint.completionsURL, method: .post, headers: endpoint.headers, json: vendorBody(body, model: endpoint.model))
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        request.timeoutInterval = 300
        let (bytes, response): (URLSession.AsyncBytes, URLResponse)
        do {
            (bytes, response) = try await HTTP.session.bytes(for: request)
        } catch {
            if Task.isCancelled { throw CancellationError() }
            throw APIError(kind: .network, status: 0, message: L("models.error.unreachable"))
        }
        guard let http = response as? HTTPURLResponse else { throw APIError.network }
        guard (200..<300).contains(http.statusCode) else {
            var data = Data()
            for try await byte in bytes { data.append(byte); if data.count > 16_384 { break } }
            throw vendorError(status: http.statusCode, data: data)
        }
        var completed = false
        for try await event in SSE.events(bytes) {
            if event.data == "[DONE]" { completed = true; break }
            do {
                for parsed in try LynxceBackend.parseChunk(event.data) { onEvent(parsed) }
            } catch let error as APIError {
                // A vendor's quota is not the Lynxce wallet: never show the top-up card for it.
                throw APIError(kind: .server, status: error.status, message: error.code == "insufficient_balance" ? L("error.providerBalance") : error.message)
            }
            calls.add(event.data)
            if finishReason(event.data) != nil { completed = true }
        }
        if !completed && !Task.isCancelled { throw APIError.network }
    }

    /// Ollama and some vendors end with `finish_reason` and no `[DONE]`.
    static func finishReason(_ data: String) -> String? {
        guard let object = try? JSONSerialization.jsonObject(with: Data(data.utf8)) as? [String: Any],
              let choice = (object["choices"] as? [[String: Any]])?.first else { return nil }
        return choice["finish_reason"] as? String
    }

    /// A vendor's failure in the user's words; a refused key never signs the user out.
    static func vendorError(status: Int, data: Data) -> APIError {
        let message = HTTP.errorMessage(data)
        switch status {
        case 401, 403: return APIError(kind: .rejected, status: status, message: L("models.error.keyRejected"))
        case 402, 429: return APIError(kind: .rejected, status: status, message: message.map { L("models.error.quota") + " " + $0 } ?? L("models.error.quota"))
        case 400..<500: return APIError(kind: .rejected, status: status, message: message)
        default: return APIError(kind: .server, status: status, message: message)
        }
    }
}
