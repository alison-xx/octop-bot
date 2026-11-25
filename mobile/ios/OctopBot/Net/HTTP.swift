import Foundation

/// A user-facing failure from Lynxce or an Octop server.
struct APIError: LocalizedError, Equatable {
    enum Kind: Equatable { case unauthorized, credits, dailyLimit, rejected, network, server }
    var kind: Kind
    var status: Int
    var message: String?
    /// The server's machine-readable error code (`{error: {code}}`), when it sent one.
    var code: String? = nil
    var details: CreditDetails? = nil

    var errorDescription: String? {
        if kind == .credits, let scenario = creditScenario(code: code, details: details) { return scenario.message }
        if code == Self.computerOff { return L("error.computerOff") }
        if code == Self.computerBusy { return L("error.computerBusy") }
        // The server's credits text links to Lynxce's web checkout, which App Store builds don't show.
        if kind != .credits, let message, !message.isEmpty { return message }
        switch kind {
        case .unauthorized: return L("error.unauthorized")
        case .credits: return L(CreditPurchases.inApp ? "error.credits" : "error.creditsNoPurchase")
        case .dailyLimit: return L("error.dailyLimit")
        case .rejected: return L("error.rejected %lld", status)
        case .network: return L("error.network")
        case .server: return L("error.server %lld", status)
        }
    }

    /// Octop Bot cloud: the file is on the Bot's cloud computer, which is off (HTTP 409).
    static let computerOff = "BOT_COMPUTER_OFF"

    /// Octop Bot cloud: every cloud computer slot is taken (HTTP 503).
    static let computerBusy = "BOT_COMPUTER_BUSY"

    /// Octop's error code when a turn billed to the Lynxce wallet runs out of credits.
    static let creditsRequired = "BOT_CLOUD_CREDITS_REQUIRED"

    static let computerCreditsRequired = "BOT_COMPUTER_CREDITS_REQUIRED"
    static let computerPausedNoCredits = "BOT_COMPUTER_PAUSED_NO_CREDITS"
    static func isCreditsRequired(_ code: String?) -> Bool {
        code == creditsRequired || code == computerCreditsRequired || code == computerPausedNoCredits
    }

    /// Octop's error code when the wallet still has credits but Lynxce's per-key daily cap is used up.
    static let dailyLimit = "BOT_LYNXCE_DAILY_LIMIT"

    /// Daily cap (Octop's code, or Lynxce's `api_key_credit_limit_reached`); topping up does not help.
    static func isDailyLimit(_ code: String?) -> Bool {
        guard let code else { return false }
        return code == dailyLimit || code.lowercased().contains("credit_limit_reached")
    }

    static func from(status: Int, message: String?, code: String? = nil, details: CreditDetails? = nil) -> APIError {
        // Checked first: Lynxce can send the daily cap as a 402 too.
        if isDailyLimit(code) { return APIError(kind: .dailyLimit, status: 429, message: message, code: code) }
        if isCreditsRequired(code) { return APIError(kind: .credits, status: 402, message: message, code: code, details: details) }
        return switch status {
        case 401: APIError(kind: .unauthorized, status: status, message: message, code: code)
        case 402: APIError(kind: .credits, status: status, message: message, code: code)
        case 400..<500: APIError(kind: .rejected, status: status, message: message, code: code)
        default: APIError(kind: .server, status: status, message: message, code: code)
        }
    }

    static let network = APIError(kind: .network, status: 0, message: nil)
}

nonisolated struct CreditDetails: Equatable, Hashable {
    var need: Double?
    var balance: Double?
    var kind: String?

    init?(_ object: [String: Any]?) {
        guard let object else { return nil }
        need = (object["need"] as? NSNumber)?.doubleValue
        balance = (object["balance"] as? NSNumber)?.doubleValue
        kind = object["kind"] as? String
    }
}

nonisolated struct CreditScenario: Equatable, Hashable {
    enum Kind: String { case text, image, video, computer, paused }
    var kind: Kind
    var need: Double
    var balance: Double
    var message: String {
        let key: String
        switch kind {
        case .text: key = "credits.scenario.text %@ %@"
        case .image: key = "credits.scenario.image %@ %@"
        case .video: key = "credits.scenario.video %@ %@"
        case .computer: key = "credits.scenario.computer %@ %@"
        case .paused: key = "credits.scenario.paused %@ %@"
        }
        return L(key, LynxceBackend.formatCredits(need), LynxceBackend.formatCredits(balance))
    }
}

/// Which out-of-credits message to show. A paused computer needs no figures; starting one needs `need`;
/// chat, images and video need both `need` and `balance`. Anything missing falls back to the generic text.
nonisolated func creditScenario(code: String?, details: CreditDetails?) -> CreditScenario? {
    let need = details?.need.flatMap { $0.isFinite && $0 > 0 ? $0 : nil }
    let balance = details?.balance.flatMap { $0.isFinite ? $0 : nil }
    switch code {
    case APIError.computerPausedNoCredits:
        return CreditScenario(kind: .paused, need: 0, balance: balance ?? 0)
    case APIError.computerCreditsRequired:
        return need.map { CreditScenario(kind: .computer, need: $0, balance: balance ?? 0) }
    case APIError.creditsRequired:
        guard let value = details?.kind, let kind = CreditScenario.Kind(rawValue: value),
              [.text, .image, .video].contains(kind), let need, let balance else { return nil }
        return CreditScenario(kind: kind, need: need, balance: balance)
    default:
        return nil
    }
}

enum HTTPMethod: String { case get = "GET", head = "HEAD", post = "POST", put = "PUT", patch = "PATCH", delete = "DELETE" }

/// One multipart form part, in the order the server reads them.
struct FormPart {
    var name: String
    var value: String? = nil
    var file: Data? = nil
    var filename: String? = nil
    var mimeType: String? = nil
}

/// Wallet and sign-in APIs must receive credentials and receipts only at the requested endpoint.
final class NoAPIRedirect: NSObject, URLSessionTaskDelegate {
    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask,
                                willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                                completionHandler: @escaping @Sendable (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

enum HTTP {
    static let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 60
        config.timeoutIntervalForResource = 600
        config.waitsForConnectivity = false
        return URLSession(configuration: config)
    }()

    static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .useDefaultKeys
        return decoder
    }()

    static func request(
        _ url: URL,
        method: HTTPMethod = .get,
        headers: [String: String] = [:],
        json: Any? = nil,
        form: [FormPart]? = nil
    ) throws -> URLRequest {
        var request = URLRequest(url: url)
        request.httpMethod = method.rawValue
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(Preferences.shared.language.httpTag, forHTTPHeaderField: "Accept-Language")
        for (key, value) in headers { request.setValue(value, forHTTPHeaderField: key) }
        if let json {
            request.httpBody = try JSONSerialization.data(withJSONObject: json)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        } else if let form {
            let boundary = "octop-\(UUID().uuidString)"
            request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
            request.httpBody = multipart(form, boundary: boundary)
        }
        return request
    }

    static func multipart(_ parts: [FormPart], boundary: String) -> Data {
        var body = Data()
        func line(_ text: String) { body.append(Data((text + "\r\n").utf8)) }
        for part in parts {
            line("--\(boundary)")
            if let file = part.file {
                line("Content-Disposition: form-data; name=\"\(part.name)\"; filename=\"\(part.filename ?? "file")\"")
                line("Content-Type: \(part.mimeType ?? "application/octet-stream")")
                line("")
                body.append(file)
                line("")
            } else {
                line("Content-Disposition: form-data; name=\"\(part.name)\"")
                line("")
                line(part.value ?? "")
            }
        }
        line("--\(boundary)--")
        return body
    }

    /// Send a request and return the raw body, mapping transport and HTTP failures.
    static func data(for request: URLRequest, using session: URLSession = HTTP.session, delegate: URLSessionTaskDelegate? = nil) async throws -> (Data, HTTPURLResponse) {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request, delegate: delegate)
        } catch is CancellationError {
            throw CancellationError()
        } catch let error as URLError where error.code == .cancelled {
            throw CancellationError()
        } catch {
            throw APIError.network
        }
        guard let http = response as? HTTPURLResponse else { throw APIError.network }
        return (data, http)
    }

    /// Pull a human message out of either envelope: Lynxce `{code,message}` or Octop `{error:{message}}`.
    static func errorMessage(_ data: Data) -> String? {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        if let error = object["error"] as? [String: Any] { return error["message"] as? String }
        if let error = object["error"] as? String { return error }
        if let detail = object["detail"] as? String { return detail }
        return object["message"] as? String
    }

    static func errorDetails(_ data: Data) -> CreditDetails? {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return CreditDetails((object["error"] as? [String: Any])?["details"] as? [String: Any] ?? object["details"] as? [String: Any])
    }

    /// The error code in either envelope: Octop `{error:{code}}` / `{error_code}`, or Lynxce's string code.
    static func errorCode(_ data: Data) -> String? {
        let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        let code = ((object?["error"] as? [String: Any])?["code"] as? String)
            ?? (object?["error_code"] as? String) ?? (object?["errorCode"] as? String) ?? (object?["code"] as? String)
        if code != nil { return code }
        // Lynxce's daily-cap marker may sit deeper in its body; it is distinctive enough to find anywhere.
        return String(decoding: data.prefix(16_384), as: UTF8.self).contains("credit_limit_reached")
            ? "api_key_credit_limit_reached" : nil
    }
}

/// Server-Sent Events from a streaming response. Yields each event's `event` name and joined `data`.
struct SSEEvent: Equatable {
    var event: String?
    var data: String
}

enum SSE {
    static func events(_ bytes: URLSession.AsyncBytes) -> AsyncThrowingStream<SSEEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                var parser = SSEParser()
                do {
                    for try await line in bytes.linesKeepingEmpty() {
                        if let event = parser.feed(line) { continuation.yield(event) }
                    }
                    if let event = parser.finish() { continuation.yield(event) }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}

/// Line-oriented SSE parser; kept separate so it can be unit tested.
struct SSEParser {
    private var name: String?
    private var data: [String] = []

    mutating func feed(_ rawLine: String) -> SSEEvent? {
        let line = rawLine.hasSuffix("\r") ? String(rawLine.dropLast()) : rawLine
        if line.isEmpty { return flush() }
        if line.hasPrefix(":") { return nil }
        let field: Substring
        var value: Substring
        if let colon = line.firstIndex(of: ":") {
            field = line[..<colon]
            value = line[line.index(after: colon)...]
            if value.hasPrefix(" ") { value = value.dropFirst() }
        } else {
            field = Substring(line)
            value = ""
        }
        switch field {
        case "event": name = String(value)
        case "data": data.append(String(value))
        default: break
        }
        return nil
    }

    mutating func finish() -> SSEEvent? { flush() }

    private mutating func flush() -> SSEEvent? {
        defer { name = nil; data = [] }
        guard !data.isEmpty || name != nil else { return nil }
        return SSEEvent(event: name, data: data.joined(separator: "\n"))
    }
}

extension URLSession.AsyncBytes {
    /// `lines` drops empty lines, but SSE needs them as event separators.
    func linesKeepingEmpty() -> AsyncThrowingStream<String, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                var buffer = Data()
                do {
                    for try await byte in self {
                        if byte == UInt8(ascii: "\n") {
                            continuation.yield(String(decoding: buffer, as: UTF8.self))
                            buffer.removeAll(keepingCapacity: true)
                        } else {
                            buffer.append(byte)
                        }
                    }
                    if !buffer.isEmpty { continuation.yield(String(decoding: buffer, as: UTF8.self)) }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}
