import Foundation

/// OpenAI streamed `delta.tool_calls` joined back into whole calls (arguments arrive in pieces, keyed by `index`).
nonisolated struct ToolCallAccumulator {
    struct Call: Equatable {
        var id: String
        var name: String
        var arguments: String
    }

    private var byIndex: [Int: Call] = [:]

    var calls: [Call] { byIndex.keys.sorted().compactMap { byIndex[$0] }.filter { !$0.name.isEmpty } }

    mutating func add(_ data: String) {
        guard let object = (try? JSONSerialization.jsonObject(with: Data(data.utf8))) as? [String: Any],
              let choice = (object["choices"] as? [[String: Any]])?.first,
              let delta = (choice["delta"] ?? choice["message"]) as? [String: Any],
              let parts = delta["tool_calls"] as? [[String: Any]] else { return }
        for (position, part) in parts.enumerated() {
            let index = (part["index"] as? Int) ?? position
            var call = byIndex[index] ?? Call(id: "", name: "", arguments: "")
            if let id = part["id"] as? String, !id.isEmpty { call.id = id }
            if let function = part["function"] as? [String: Any] {
                if let name = function["name"] as? String, !name.isEmpty, name != call.name { call.name += name }
                if let arguments = function["arguments"] as? String { call.arguments += arguments }
            }
            if call.id.isEmpty { call.id = "call_\(index)" }
            byIndex[index] = call
        }
    }

    /// The assistant turn that made the calls, as the next request must repeat it.
    static func assistantMessage(text: String, calls: [Call]) -> [String: Any] {
        [
            "role": "assistant",
            "content": text.isEmpty ? NSNull() : text,
            "tool_calls": calls.map { call -> [String: Any] in
                ["id": call.id, "type": "function", "function": ["name": call.name, "arguments": call.arguments.isEmpty ? "{}" : call.arguments]]
            },
        ]
    }
}
