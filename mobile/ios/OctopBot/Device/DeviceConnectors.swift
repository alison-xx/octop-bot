import EventKit
import Foundation
import HealthKit
import Observation

/// What the phone can share with its Bots. Wire contract: mobile/PROTOCOL.md → "C. Device connectors".
enum DeviceCapability: String, CaseIterable, Identifiable {
    case health, calendar, reminders
    var id: String { rawValue }
}

/// One entry of `device_tools.json` (the same file the server uses).
struct DeviceToolSpec {
    var name: String
    var capability: DeviceCapability
    var writes: Bool
    var description: String
    var parameters: [String: Any]

    var openAITool: [String: Any] {
        ["type": "function", "function": ["name": name, "description": description, "parameters": parameters]]
    }
}

/// The Health, Calendar and Reminders connectors: their switches, permissions and tool runs.
@Observable
final class DeviceConnectors {
    static let shared = DeviceConnectors()
    private static let key = "device.connectors"

    let specs: [DeviceToolSpec]
    /// Connectors the user switched on (and granted when asked).
    private(set) var enabled: Set<DeviceCapability>
    /// Connectors whose system permission was refused; Settings points to the system app.
    private(set) var denied: Set<DeviceCapability> = []

    @ObservationIgnored private let events = EKEventStore()
    @ObservationIgnored private let health = HKHealthStore()

    private init() {
        specs = Self.loadSpecs()
        let saved = UserDefaults.standard.stringArray(forKey: Self.key) ?? []
        enabled = Set(saved.compactMap(DeviceCapability.init(rawValue:)))
    }

    static func loadSpecs() -> [DeviceToolSpec] {
        guard let url = Bundle.main.url(forResource: "device_tools", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let tools = root["tools"] as? [[String: Any]] else { return [] }
        return tools.compactMap { tool in
            guard let name = tool["name"] as? String,
                  let capability = (tool["capability"] as? String).flatMap(DeviceCapability.init(rawValue:)) else { return nil }
            return DeviceToolSpec(
                name: name, capability: capability, writes: tool["writes"] as? Bool ?? true,
                description: tool["description"] as? String ?? "", parameters: tool["parameters"] as? [String: Any] ?? [:]
            )
        }
    }

    static func isDeviceTool(_ name: String) -> Bool { name.hasPrefix("device_") }

    func spec(_ name: String) -> DeviceToolSpec? { specs.first { $0.name == name } }

    /// True for tools that change the user's data and so wait for the card. Unknown tools count as writes.
    func writes(_ name: String) -> Bool { spec(name)?.writes ?? true }

    var isAvailable: [DeviceCapability: Bool] {
        [.health: HKHealthStore.isHealthDataAvailable(), .calendar: true, .reminders: true]
    }

    func isOn(_ capability: DeviceCapability) -> Bool {
        enabled.contains(capability) && permitted(capability)
    }

    private func permitted(_ capability: DeviceCapability) -> Bool {
        switch capability {
        // Apple hides whether Health reads were allowed; a refused type simply returns no data.
        case .health: HKHealthStore.isHealthDataAvailable()
        case .calendar: EKEventStore.authorizationStatus(for: .event) == .fullAccess
        case .reminders: EKEventStore.authorizationStatus(for: .reminder) == .fullAccess
        }
    }

    /// The tools to offer the Bot on the next turn.
    var offeredSpecs: [DeviceToolSpec] { specs.filter { isOn($0.capability) } }
    var offeredTools: [String] { offeredSpecs.map(\.name) }

    /// Turn a connector on (asking for the permission) or off.
    func set(_ capability: DeviceCapability, on: Bool) async {
        guard on else {
            enabled.remove(capability)
            save()
            return
        }
        let granted: Bool
        switch capability {
        case .health:
            if HKHealthStore.isHealthDataAvailable() {
                granted = (try? await health.requestAuthorization(toShare: [], read: HealthMetric.readTypes)) != nil
            } else {
                granted = false
            }
        case .calendar:
            granted = (try? await events.requestFullAccessToEvents()) ?? false
        case .reminders:
            granted = (try? await events.requestFullAccessToReminders()) ?? false
        }
        if granted {
            enabled.insert(capability)
            denied.remove(capability)
        } else {
            enabled.remove(capability)
            denied.insert(capability)
        }
        save()
    }

    /// Re-check permissions changed in the system Settings app.
    func refresh() {
        denied = denied.filter { !permitted($0) }
        for capability in enabled where !permitted(capability) { denied.insert(capability) }
    }

    private func save() {
        UserDefaults.standard.set(enabled.map(\.rawValue).sorted(), forKey: Self.key)
    }

    // MARK: Running a tool

    /// Run one tool and return its JSON result; failures come back as `{"error": …}`.
    func run(_ name: String, argsJSON: String) async -> String {
        let args = DeviceArgs.object(argsJSON)
        guard let spec = spec(name) else { return Self.json(["error": "Unknown device tool \(name)."]) }
        guard isOn(spec.capability) else {
            return Self.json(["error": "The user has not turned on the \(spec.capability.rawValue) connector in Octop Bot."])
        }
        do {
            let result: [String: Any]
            switch name {
            case "device_health_summary": result = try await healthSummary(args)
            case "device_calendar_events": result = try calendarEvents(args)
            case "device_calendar_create_event": result = try createEvent(args)
            case "device_calendar_update_event": result = try updateEvent(args)
            case "device_reminders": result = try await reminders(args)
            case "device_reminder_create": result = try createReminder(args)
            default: throw DeviceError("Unknown device tool \(name).")
            }
            return Self.json(result)
        } catch {
            return Self.json(["error": (error as? DeviceError)?.message ?? error.localizedDescription])
        }
    }

    nonisolated static func json(_ object: [String: Any]) -> String {
        guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) else { return "{}" }
        return String(decoding: data, as: UTF8.self)
    }

    // MARK: Health

    private func healthSummary(_ args: [String: Any]) async throws -> [String: Any] {
        let names = (args["metrics"] as? [String]) ?? []
        let metrics = names.compactMap(HealthMetric.init(rawValue:))
        guard !metrics.isEmpty else { throw DeviceError("metrics must name at least one of: \(HealthMetric.allCases.map(\.rawValue).joined(separator: ", ")).") }
        let days = min(max(DeviceArgs.int(args["days"]) ?? 7, 1), 30)
        let calendar = Calendar.current
        let end = calendar.date(byAdding: .day, value: 1, to: calendar.startOfDay(for: .now))!
        let start = calendar.date(byAdding: .day, value: -days, to: end)!
        var rows: [String: [String: Any]] = [:]
        var units: [String: String] = [:]
        for metric in metrics {
            let values = try await metric.daily(from: start, to: end, store: health)
            guard !values.isEmpty else { continue }
            units[metric.rawValue] = metric.unitLabel
            for (day, value) in values {
                rows[DeviceDates.day(day), default: [:]][metric.rawValue] = (value * 10).rounded() / 10
            }
        }
        let list = rows.keys.sorted().map { day -> [String: Any] in
            var row = rows[day] ?? [:]
            row["date"] = day
            return row
        }
        return [
            "from": DeviceDates.day(start),
            "to": DeviceDates.day(calendar.date(byAdding: .day, value: -1, to: end)!),
            "units": units,
            "days": list,
        ]
    }

    // MARK: Calendar

    private func calendarEvents(_ args: [String: Any]) throws -> [String: Any] {
        let start = try DeviceDates.required(args["start"], "start")
        var end = try DeviceDates.required(args["end"], "end")
        if end.dateOnly { end.date = Calendar.current.date(byAdding: .day, value: 1, to: end.date)! }
        guard end.date > start.date else { throw DeviceError("end must be after start.") }
        guard end.date.timeIntervalSince(start.date) <= 62 * 86_400 else { throw DeviceError("Ask for at most 62 days at a time.") }
        let predicate = events.predicateForEvents(withStart: start.date, end: end.date, calendars: nil)
        let found = events.events(matching: predicate).sorted { $0.startDate < $1.startDate }.prefix(200)
        return ["events": found.map(Self.eventRow)]
    }

    private func createEvent(_ args: [String: Any]) throws -> [String: Any] {
        guard let title = DeviceArgs.text(args["title"]) else { throw DeviceError("title is required.") }
        let start = try DeviceDates.required(args["start"], "start")
        let end = try DeviceDates.required(args["end"], "end")
        let allDay = (args["all_day"] as? Bool ?? false) || (start.dateOnly && end.dateOnly)
        guard let calendar = events.defaultCalendarForNewEvents else { throw DeviceError("This phone has no calendar to add events to.") }
        let event = EKEvent(eventStore: events)
        event.calendar = calendar
        event.title = title
        event.isAllDay = allDay
        event.startDate = start.date
        event.endDate = allDay && end.dateOnly ? Calendar.current.date(byAdding: .day, value: 1, to: end.date)! : end.date
        guard event.endDate >= event.startDate else { throw DeviceError("end must be after start.") }
        event.location = DeviceArgs.text(args["location"])
        event.notes = DeviceArgs.text(args["notes"])
        if let minutes = DeviceArgs.int(args["alarm_minutes"]) {
            event.addAlarm(EKAlarm(relativeOffset: -Double(minutes) * 60))
        }
        try events.save(event, span: .thisEvent, commit: true)
        return Self.eventRow(event)
    }

    private func updateEvent(_ args: [String: Any]) throws -> [String: Any] {
        guard let id = DeviceArgs.text(args["event_id"]), let event = events.event(withIdentifier: id) else {
            throw DeviceError("No event with that event_id; list events first.")
        }
        if let title = DeviceArgs.text(args["title"]) { event.title = title }
        if let start = try DeviceDates.optional(args["start"]) { event.startDate = start.date }
        if let end = try DeviceDates.optional(args["end"]) { event.endDate = end.date }
        guard event.endDate >= event.startDate else { throw DeviceError("end must be after start.") }
        if args["location"] != nil { event.location = DeviceArgs.text(args["location"]) }
        if args["notes"] != nil { event.notes = DeviceArgs.text(args["notes"]) }
        try events.save(event, span: .thisEvent, commit: true)
        return Self.eventRow(event)
    }

    private static func eventRow(_ event: EKEvent) -> [String: Any] {
        var row: [String: Any] = [
            "id": event.eventIdentifier ?? "",
            "title": event.title ?? "",
            "all_day": event.isAllDay,
            "calendar": event.calendar?.title ?? "",
        ]
        if event.isAllDay {
            row["start"] = DeviceDates.day(event.startDate)
            row["end"] = DeviceDates.day(Calendar.current.date(byAdding: .second, value: -1, to: event.endDate) ?? event.endDate)
        } else {
            row["start"] = DeviceDates.stamp(event.startDate)
            row["end"] = DeviceDates.stamp(event.endDate)
        }
        if let location = event.location, !location.isEmpty { row["location"] = location }
        if let notes = event.notes, !notes.isEmpty { row["notes"] = String(notes.prefix(1000)) }
        return row
    }

    // MARK: Reminders

    private func reminders(_ args: [String: Any]) async throws -> [String: Any] {
        let includeCompleted = args["include_completed"] as? Bool ?? false
        let limit = min(max(DeviceArgs.int(args["limit"]) ?? 50, 1), 200)
        let predicate = includeCompleted
            ? events.predicateForReminders(in: nil)
            : events.predicateForIncompleteReminders(withDueDateStarting: nil, ending: nil, calendars: nil)
        let rows: [ReminderRow] = await withCheckedContinuation { continuation in
            events.fetchReminders(matching: predicate) { @Sendable found in
                continuation.resume(returning: (found ?? []).map(ReminderRow.init))
            }
        }
        let sorted = rows.sorted { ($0.due ?? .distantFuture, $0.title) < ($1.due ?? .distantFuture, $1.title) }
        return ["reminders": sorted.prefix(limit).map(\.json)]
    }

    private func createReminder(_ args: [String: Any]) throws -> [String: Any] {
        guard let title = DeviceArgs.text(args["title"]) else { throw DeviceError("title is required.") }
        let reminder = EKReminder(eventStore: events)
        reminder.title = title
        reminder.notes = DeviceArgs.text(args["notes"])
        let lists = events.calendars(for: .reminder)
        let wanted = DeviceArgs.text(args["list"])
        guard let list = lists.first(where: { $0.title == wanted }) ?? events.defaultCalendarForNewReminders() else {
            throw DeviceError("This phone has no Reminders list to add to.")
        }
        reminder.calendar = list
        reminder.priority = ReminderRow.priority(DeviceArgs.text(args["priority"]))
        if let due = try DeviceDates.optional(args["due"]) {
            let parts: Set<Calendar.Component> = due.dateOnly ? [.year, .month, .day] : [.year, .month, .day, .hour, .minute]
            reminder.dueDateComponents = Calendar.current.dateComponents(parts, from: due.date)
            if !due.dateOnly { reminder.addAlarm(EKAlarm(absoluteDate: due.date)) }
        }
        try events.save(reminder, commit: true)
        return ReminderRow(reminder).json
    }
}

nonisolated struct DeviceError: Error, Sendable {
    var message: String
    init(_ message: String) { self.message = message }
}

/// A reminder copied off EventKit's callback queue.
nonisolated struct ReminderRow: Sendable {
    var id: String
    var title: String
    var due: Date?
    var dueIsDate: Bool
    var completed: Bool
    var priority: Int
    var notes: String?
    var list: String

    init(_ reminder: EKReminder) {
        id = reminder.calendarItemIdentifier
        title = reminder.title ?? ""
        let components = reminder.dueDateComponents
        due = components.flatMap { Calendar.current.date(from: $0) }
        dueIsDate = components?.hour == nil
        completed = reminder.isCompleted
        priority = reminder.priority
        notes = reminder.notes
        list = reminder.calendar?.title ?? ""
    }

    static func priority(_ name: String?) -> Int {
        switch name {
        case "high": 1
        case "medium": 5
        case "low": 9
        default: 0
        }
    }

    var json: [String: Any] {
        var row: [String: Any] = ["id": id, "title": title, "completed": completed, "list": list]
        row["priority"] = switch priority {
        case 1...4: "high"
        case 5: "medium"
        case 6...9: "low"
        default: "none"
        }
        if let due { row["due"] = dueIsDate ? DeviceDates.day(due) : DeviceDates.stamp(due) }
        if let notes, !notes.isEmpty { row["notes"] = String(notes.prefix(1000)) }
        return row
    }
}

/// Health metrics in `device_health_summary`, one value per day.
enum HealthMetric: String, CaseIterable {
    case steps, active_energy, exercise_minutes, sleep_hours, heart_rate, resting_heart_rate, weight

    static var readTypes: Set<HKObjectType> {
        var types: Set<HKObjectType> = [HKCategoryType(.sleepAnalysis)]
        for metric in allCases { if let type = metric.quantityType { types.insert(type) } }
        return types
    }

    var quantityType: HKQuantityType? {
        switch self {
        case .steps: HKQuantityType(.stepCount)
        case .active_energy: HKQuantityType(.activeEnergyBurned)
        case .exercise_minutes: HKQuantityType(.appleExerciseTime)
        case .heart_rate: HKQuantityType(.heartRate)
        case .resting_heart_rate: HKQuantityType(.restingHeartRate)
        case .weight: HKQuantityType(.bodyMass)
        case .sleep_hours: nil
        }
    }

    var unitLabel: String {
        switch self {
        case .steps: "count"
        case .active_energy: "kcal"
        case .exercise_minutes: "min"
        case .sleep_hours: "h"
        case .heart_rate, .resting_heart_rate: "bpm"
        case .weight: "kg"
        }
    }

    private var unit: HKUnit {
        switch self {
        case .steps: .count()
        case .active_energy: .kilocalorie()
        case .exercise_minutes: .minute()
        case .heart_rate, .resting_heart_rate: .count().unitDivided(by: .minute())
        case .weight: .gramUnit(with: .kilo)
        case .sleep_hours: .hour()
        }
    }

    private var options: HKStatisticsOptions {
        switch self {
        case .steps, .active_energy, .exercise_minutes, .sleep_hours: .cumulativeSum
        case .heart_rate, .resting_heart_rate: .discreteAverage
        case .weight: .mostRecent
        }
    }

    /// Day start → value, for days that have data.
    func daily(from start: Date, to end: Date, store: HKHealthStore) async throws -> [(Date, Double)] {
        guard let type = quantityType else { return try await sleep(from: start, to: end, store: store) }
        let range = HKQuery.predicateForSamples(withStart: start, end: end)
        let query = HKStatisticsCollectionQueryDescriptor(
            predicate: .quantitySample(type: type, predicate: range),
            options: options, anchorDate: start, intervalComponents: DateComponents(day: 1)
        )
        let collection = try await query.result(for: store)
        var values: [(Date, Double)] = []
        collection.enumerateStatistics(from: start, to: end) { statistics, _ in
            let quantity = switch self.options {
            case .cumulativeSum: statistics.sumQuantity()
            case .discreteAverage: statistics.averageQuantity()
            default: statistics.mostRecentQuantity()
            }
            if let quantity { values.append((statistics.startDate, quantity.doubleValue(for: self.unit))) }
        }
        return values
    }

    /// Hours asleep per night, counted on the day the user woke up; overlapping sources count once.
    private func sleep(from start: Date, to end: Date, store: HKHealthStore) async throws -> [(Date, Double)] {
        let calendar = Calendar.current
        let range = HKQuery.predicateForSamples(withStart: calendar.date(byAdding: .hour, value: -12, to: start), end: end)
        let query = HKSampleQueryDescriptor(
            predicates: [.categorySample(type: HKCategoryType(.sleepAnalysis), predicate: range)],
            sortDescriptors: [SortDescriptor(\.startDate)]
        )
        let asleep: Set<Int> = [
            HKCategoryValueSleepAnalysis.asleepUnspecified.rawValue, HKCategoryValueSleepAnalysis.asleepCore.rawValue,
            HKCategoryValueSleepAnalysis.asleepDeep.rawValue, HKCategoryValueSleepAnalysis.asleepREM.rawValue,
        ]
        var byDay: [Date: [DateInterval]] = [:]
        for sample in try await query.result(for: store) where asleep.contains(sample.value) {
            let day = calendar.startOfDay(for: sample.endDate)
            guard day >= start, day < end else { continue }
            byDay[day, default: []].append(DateInterval(start: sample.startDate, end: sample.endDate))
        }
        return byDay.keys.sorted().map { day in (day, Self.union(byDay[day] ?? []) / 3600) }
    }

    static func union(_ intervals: [DateInterval]) -> TimeInterval {
        var total: TimeInterval = 0
        var current: DateInterval?
        for interval in intervals.sorted(by: { $0.start < $1.start }) {
            if let open = current, interval.start <= open.end {
                current = DateInterval(start: open.start, end: max(open.end, interval.end))
            } else {
                if let open = current { total += open.duration }
                current = interval
            }
        }
        return total + (current?.duration ?? 0)
    }
}
