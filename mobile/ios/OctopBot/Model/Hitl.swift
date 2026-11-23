import Foundation

/// A turn paused for the user: a question from the Bot, or a tool waiting for approval.
/// Wire format: mobile/PROTOCOL.md → "Questions and approvals (HITL)".
struct HitlPause: Hashable, Identifiable {
    struct Option: Hashable {
        var label: String
        var description: String?
    }

    struct Question: Hashable {
        var question: String
        var header: String?
        var options: [Option]
        var multiSelect: Bool
    }

    struct Action: Hashable {
        var name: String
        var label: String
        var description: String?
        /// Key arguments worth showing before approving, e.g. ("command", "ls -la").
        var details: [Detail]
    }

    struct Detail: Hashable {
        var key: String
        var value: String
    }

    static let askTool = "ask_user_question"

    var id: String { pendingId ?? actions.map(\.name).joined(separator: ",") }
    var pendingId: String?
    var actions: [Action]
    var questions: [Question]

    var isQuestion: Bool { actions.contains { $0.name == Self.askTool } }

    /// Parse a `hitl_required.request` or `history.hitl_pending` payload.
    static func parse(_ raw: Any?, labels: [String: String] = [:]) -> HitlPause? {
        guard var request = raw as? [String: Any] else { return nil }
        for _ in 0..<3 where !(request["action_requests"] is [Any]) {
            guard let inner = request["value"] as? [String: Any] else { break }
            request = inner
        }
        guard let rows = request["action_requests"] as? [[String: Any]], !rows.isEmpty else { return nil }
        var actions: [Action] = []
        var questions: [Question] = []
        for row in rows {
            let name = row["name"] as? String ?? "tool"
            let args = Self.object(row["args"]) ?? [:]
            if name == askTool, questions.isEmpty {
                questions = Self.questions(args["questions"] ?? args)
            }
            let details = ["command", "cmd", "url", "path", "file_path", "query"].compactMap { key -> Detail? in
                guard let value = args[key] else { return nil }
                let text = (value as? String) ?? "\(value)"
                return text.isEmpty ? nil : Detail(key: key, value: String(text.prefix(400)))
            }
            let description = (row["description"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            actions.append(Action(
                name: name, label: labels[name] ?? name,
                description: description?.isEmpty == false ? description : nil, details: details
            ))
        }
        return HitlPause(pendingId: request["pending_id"] as? String, actions: actions, questions: questions)
    }

    private static func object(_ raw: Any?) -> [String: Any]? {
        if let dict = raw as? [String: Any] { return dict }
        if let text = raw as? String, let data = text.data(using: .utf8) {
            return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        }
        return nil
    }

    private static func questions(_ raw: Any?) -> [Question] {
        var value = raw
        if let text = raw as? String, let data = text.data(using: .utf8) {
            value = (try? JSONSerialization.jsonObject(with: data)) ?? raw
        }
        if let list = value as? [Any] {
            return list.compactMap { ($0 as? [String: Any]).flatMap(question) }
        }
        guard let dict = value as? [String: Any] else { return [] }
        if let nested = dict["questions"] { return questions(nested) }
        return question(dict).map { [$0] } ?? []
    }

    private static func question(_ item: [String: Any]) -> Question? {
        let text = (item["question"] as? String) ?? (item["prompt"] as? String) ?? (item["text"] as? String) ?? ""
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        let options = (item["options"] as? [[String: Any]] ?? []).compactMap { option -> Option? in
            guard let label = option["label"] as? String, !label.isEmpty else { return nil }
            return Option(label: label, description: option["description"] as? String)
        }
        return Question(question: text, header: item["header"] as? String, options: options, multiSelect: item["multi_select"] as? Bool ?? false)
    }

    /// What the user picked for one question.
    struct Answer: Hashable {
        var picked: [String] = []
        var other = ""
    }

    /// One question's answer as text, or nil while unanswered (dashboard `answerText`).
    static func answerText(_ question: Question, _ answer: Answer) -> String? {
        var labels = answer.picked
        let other = answer.other.trimmingCharacters(in: .whitespacesAndNewlines)
        if !other.isEmpty { labels.append(other) }
        return labels.isEmpty ? nil : labels.joined(separator: "; ")
    }

    /// The reply sent to the Bot: one "{header or question}: {answer}" line per question.
    static func answerMessage(_ questions: [Question], _ answers: [Answer]) -> String? {
        var lines: [String] = []
        for (index, question) in questions.enumerated() {
            guard let text = answerText(question, index < answers.count ? answers[index] : Answer()) else { return nil }
            let head = question.header?.trimmingCharacters(in: .whitespaces).nilIfEmpty ?? question.question
            lines.append("\(head): \(text)")
        }
        return lines.joined(separator: "\n")
    }
}

extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
