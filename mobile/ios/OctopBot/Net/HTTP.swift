import Foundation

/// A user-facing failure from Lynxce or an Octop server.
struct APIError: LocalizedError, Equatable {
    enum Kind: Equatable { case unauthorized, credits, rejected, network, server }
    var kind: Kind
    var status: Int
    var message: String?

    var errorDescription: String? {
        if let message, !message.isEmpty { return message }
        switch kind {
        case .unauthorized: return L("error.unauthorized")
        case .credits: return L("error.credits")
        case .rejected: return L("error.rejected %lld", status)
        case .network: return L("error.network")
        case .server: return L("error.server %lld", status)
        }
    }

    static func from(status: Int, message: String?) -> APIError {
        switch status {
        case 401: APIError(kind: .unauthorized, status: status, message: message)
        case 402: APIError(kind: .credits, status: status, message: message)
        case 400..<500: APIError(kind: .rejected, status: status, message: message)
        default: APIError(kind: .server, status: status, message: message)
        }
    }

    static let network = APIError(kind: .network, status: 0, message: nil)
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
    static func data(for request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
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
