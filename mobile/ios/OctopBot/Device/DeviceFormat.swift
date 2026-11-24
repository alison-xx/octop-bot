import Foundation

/// Reading tool arguments, which models send as objects or as JSON text.
nonisolated enum DeviceArgs {
    static func object(_ raw: Any?) -> [String: Any] {
        if let dict = raw as? [String: Any] { return dict }
        if let text = raw as? String, let data = text.data(using: .utf8),
           let dict = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] { return dict }
        return [:]
    }

    static func text(_ raw: Any?) -> String? {
        guard let text = raw as? String else { return nil }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    static func int(_ raw: Any?) -> Int? {
        if let value = raw as? Int { return value }
        if let value = raw as? Double { return Int(value) }
        if let text = raw as? String { return Int(text) }
        return nil
    }

    static func string(_ object: [String: Any]) -> String {
        guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) else { return "{}" }
        return String(decoding: data, as: UTF8.self)
    }
}

/// ISO 8601 in and out. No offset means the phone's time zone; a bare date is a whole day.
nonisolated enum DeviceDates {
    struct Parsed: Equatable {
        var date: Date
        var dateOnly: Bool
    }

    static func parse(_ raw: String, zone: TimeZone = .current) -> Parsed? {
        let text = raw.trimmingCharacters(in: .whitespaces)
        let zoned = ISO8601DateFormatter()
        for options: ISO8601DateFormatter.Options in [[.withInternetDateTime, .withFractionalSeconds], [.withInternetDateTime]] {
            zoned.formatOptions = options
            if let date = zoned.date(from: text) { return Parsed(date: date, dateOnly: false) }
        }
        let local = DateFormatter()
        local.locale = Locale(identifier: "en_US_POSIX")
        local.timeZone = zone
        for format in ["yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd'T'HH:mm", "yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd HH:mm"] {
            local.dateFormat = format
            if let date = local.date(from: text) { return Parsed(date: date, dateOnly: false) }
        }
        local.dateFormat = "yyyy-MM-dd"
        if let date = local.date(from: text) { return Parsed(date: date, dateOnly: true) }
        return nil
    }

    static func required(_ raw: Any?, _ field: String) throws -> Parsed {
        guard let text = raw as? String, let parsed = parse(text) else {
            throw DeviceError("\(field) must be an ISO 8601 date or date-time, e.g. 2026-11-25T14:00.")
        }
        return parsed
    }

    static func optional(_ raw: Any?) throws -> Parsed? {
        guard let text = raw as? String, !text.isEmpty else { return nil }
        guard let parsed = parse(text) else { throw DeviceError("\(text) is not an ISO 8601 date or date-time.") }
        return parsed
    }

    static func stamp(_ date: Date, zone: TimeZone = .current) -> String {
        let f = ISO8601DateFormatter()
        f.timeZone = zone
        f.formatOptions = [.withInternetDateTime]
        return f.string(from: date)
    }

    static func day(_ date: Date, zone: TimeZone = .current) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = zone
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: date)
    }

    /// For people: "11月25日 周二 14:00" style, in the app's language.
    static func friendly(_ raw: Any?, locale: Locale) -> String? {
        guard let text = raw as? String, let parsed = parse(text) else { return raw as? String }
        let f = DateFormatter()
        f.locale = locale
        f.setLocalizedDateFormatFromTemplate(parsed.dateOnly ? "MMMdEEE" : "MMMdEEEHHmm")
        return f.string(from: parsed.date)
    }
}

/// The confirmation card's lines for a device action, e.g. ("时间", "11月25日 周二 14:00 – 15:00").
nonisolated enum DevicePreview {
    static func lines(_ name: String, args: [String: Any], locale: Locale) -> [(String, String)] {
        var lines: [(String, String)] = []
        func add(_ key: String, _ value: String?) {
            if let value, !value.isEmpty { lines.append((L(key), String(value.prefix(400)))) }
        }
        add("device.field.title", DeviceArgs.text(args["title"]))
        let start = DeviceDates.friendly(args["start"], locale: locale)
        let end = DeviceDates.friendly(args["end"], locale: locale)
        if let start {
            add("device.field.time", end.map { "\(start) – \($0)" } ?? start)
        }
        add("device.field.due", DeviceDates.friendly(args["due"], locale: locale))
        add("device.field.location", DeviceArgs.text(args["location"]))
        add("device.field.list", DeviceArgs.text(args["list"]))
        if let minutes = DeviceArgs.int(args["alarm_minutes"]) { add("device.field.alarm", L("device.alarm %lld", minutes)) }
        add("device.field.notes", DeviceArgs.text(args["notes"]))
        if name == "device_health_summary", let metrics = args["metrics"] as? [String] {
            add("device.field.metrics", metrics.map { L("device.metric.\($0)") }.joined(separator: "、"))
        }
        return lines
    }
}

/// Names from `device_tools.json`, readable off the main actor.
nonisolated enum DeviceCatalog {
    /// Device tools that only read the phone's data.
    static let readOnly: Set<String> = {
        guard let url = Bundle.main.url(forResource: "device_tools", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let tools = root["tools"] as? [[String: Any]] else { return [] }
        return Set(tools.compactMap { ($0["writes"] as? Bool) == false ? $0["name"] as? String : nil })
    }()
}
