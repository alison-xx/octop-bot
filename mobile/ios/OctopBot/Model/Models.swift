import Foundation

/// The SVG character a Bot wears: a DS Bot shape and an ink, or the Chief octopus.
struct Look: Hashable, Codable {
    var shape: String
    var color: String

    static let chief = Look(shape: "octop", color: "rose")
    static let fallback = Look(shape: "gumdrop", color: "blue")

    var isOctopus: Bool { shape == "octop" }
}

struct BotProfile: Identifiable, Hashable, Codable {
    var id: String
    var name: String
    var subtitle: String?
    var look: Look
    var isChief: Bool
    /// Persona for Lynxce-account bots; server bots keep their prompt on the server.
    var systemPrompt: String?
    /// True for Bots defined on this phone (Lynxce mode); they can be edited and deleted.
    var isLocal: Bool = false
    var state: String? = nil
    var preparing: Bool = false
    var lastError: String? = nil

    var canSend: Bool { isLocal || (!preparing && state != "failed") }

    init(id: String, name: String, subtitle: String? = nil, look: Look, isChief: Bool,
         systemPrompt: String? = nil, isLocal: Bool = false, state: String? = nil,
         preparing: Bool = false, lastError: String? = nil) {
        self.id = id; self.name = name; self.subtitle = subtitle; self.look = look
        self.isChief = isChief; self.systemPrompt = systemPrompt; self.isLocal = isLocal
        self.state = state; self.preparing = preparing; self.lastError = lastError
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(String.self, forKey: .id)
        name = try values.decode(String.self, forKey: .name)
        subtitle = try values.decodeIfPresent(String.self, forKey: .subtitle)
        look = try values.decode(Look.self, forKey: .look)
        isChief = try values.decode(Bool.self, forKey: .isChief)
        systemPrompt = try values.decodeIfPresent(String.self, forKey: .systemPrompt)
        isLocal = try values.decodeIfPresent(Bool.self, forKey: .isLocal) ?? false
        state = try values.decodeIfPresent(String.self, forKey: .state)
        preparing = try values.decodeIfPresent(Bool.self, forKey: .preparing) ?? false
        lastError = try values.decodeIfPresent(String.self, forKey: .lastError)
    }
}

func shouldPollBots(_ bots: [BotProfile]) -> Bool { bots.contains { !$0.isLocal && $0.preparing } }

struct ConversationSummary: Identifiable, Hashable {
    var id: String
    var title: String
    var updatedAt: Date?
    var botId: String?
    var owned: Bool? = nil
    var active = false

    static func personalDefault(_ rows: [Self]) -> Self? {
        rows.first { $0.owned == true && $0.active } ?? rows.first { $0.owned == true }
    }
}

enum MessageRole: String, Codable { case user, assistant, system }

enum MessageStatus: Hashable {
    case done
    case streaming
    case failed(String)
    /// The turn stopped because the Lynxce wallet ran out of credits; shown as a top-up card.
    case outOfCredits
    /// The turn stopped at Lynxce's per-key daily cap (credits left; topping up won't help).
    case dailyLimit

    /// Stopped by Lynxce billing rather than failed: rendered as a card with "Continue".
    var isStoppedByLynxce: Bool { self == .outOfCredits || self == .dailyLimit }
}

struct ToolStep: Hashable, Identifiable {
    var id: String
    var name: String
    var done: Bool
}

struct ChatMessage: Identifiable, Hashable {
    var id: String = UUID().uuidString
    var role: MessageRole
    var text: String
    var thinking: String = ""
    var creditScenario: CreditScenario? = nil
    var images: [Data] = []
    var tools: [ToolStep] = []
    /// Files the Bot sent (server mode); links in `text` become cards too, see `fileCards`.
    var attachments: [FileAttachment] = []
    var status: MessageStatus = .done
    var createdAt: Date = .now
    /// Group rooms: which Bot wrote this message.
    var authorId: String? = nil
    var authorName: String? = nil
}

/// Incremental output of one reply.
enum StreamEvent {
    case conversation(String)
    case turnStarted(String)
    case text(String)
    case thinking(String)
    case tool(id: String, name: String, done: Bool)
    /// A file the Bot sent (server mode).
    case attachment(FileAttachment)
    /// The turn paused for a question or an approval (server mode).
    case pause(HitlPause)
    case done
}

struct GroupSummary: Identifiable, Hashable {
    var id: String
    var name: String
    var members: [BotProfile]
    var updatedAt: Date?
}

struct ModelOption: Identifiable, Hashable {
    var id: String
    var name: String
    var supportsImage: Bool
}

enum ISO8601 {
    private static let fractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private static let plain = ISO8601DateFormatter()

    static func parse(_ text: String?) -> Date? {
        guard let text else { return nil }
        return fractional.date(from: text) ?? plain.date(from: text) ?? naive(text)
    }

    static func string(_ date: Date) -> String { fractional.string(from: date) }

    /// Octop stores some timestamps without a zone; those are UTC.
    private static func naive(_ text: String) -> Date? {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        for format in ["yyyy-MM-dd'T'HH:mm:ss.SSSSSS", "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd HH:mm:ss"] {
            f.dateFormat = format
            if let date = f.date(from: text) { return date }
        }
        return nil
    }
}

struct AccountPhoto {
    let name: String?
    let url: URL?
    var localImage: Data?

    init(name: String?, url: String?) {
        let display = name?.trimmingCharacters(in: .whitespacesAndNewlines)
        self.name = display?.isEmpty == false ? display : nil
        let candidate = url.flatMap { URL(string: $0) }
        self.url = candidate.flatMap {
            $0.scheme?.lowercased() == "https" && $0.host != nil && $0.user == nil && $0.password == nil ? $0 : nil
        }
    }

    static func localAvatar(_ me: [String: Any]) -> (path: String, query: [String: String])? {
        guard let id = me["id"] as? Int, id > 0, let raw = me["avatar_url"] as? String else { return nil }
        let path = "/api/users/\(id)/avatar"
        if raw == path { return (path, [:]) }
        guard raw.hasPrefix(path + "?"), let parts = URLComponents(string: raw), parts.fragment == nil,
              let items = parts.queryItems, items.count == 1, items[0].name == "v", let value = items[0].value else { return nil }
        return (path, ["v": value])
    }

    static func direct(_ profile: [String: Any], accountId: String) -> AccountPhoto? {
        guard profile["id"] as? String == accountId else { return nil }
        return AccountPhoto(name: profile["displayName"] as? String, url: profile["avatarUrl"] as? String)
    }

    static func cloud(_ profile: [String: Any]) -> AccountPhoto {
        guard profile["connected"] as? Bool == true else { return AccountPhoto(name: nil, url: nil) }
        return AccountPhoto(name: profile["display_name"] as? String, url: profile["avatar_url"] as? String)
    }
}

/// Where this phone talks to: the Lynxce cloud with a personal account, or a self-hosted Octop server.
protocol ChatBackend: AnyObject {
    var supportsGroups: Bool { get }
    var accountName: String { get }
    func accountPhoto() async -> AccountPhoto?

    func bots() async throws -> [BotProfile]
    func conversations(for bot: BotProfile) async throws -> [ConversationSummary]
    func messages(in conversation: ConversationSummary, bot: BotProfile) async throws -> [ChatMessage]
    func models() async throws -> [ModelOption]
    /// Stream one reply. The first event may be `.conversation` with the id of a newly created conversation.
    func send(
        _ text: String,
        messageId: String,
        images: [Data],
        to bot: BotProfile,
        conversation: String?,
        history: [ChatMessage],
        model: String?
    ) -> AsyncThrowingStream<StreamEvent, Error>
    func stop(conversation: String, bot: BotProfile) async
    func deleteConversation(_ conversation: ConversationSummary, bot: BotProfile) async throws

    func transcribe(_ audio: Data) async throws -> String?
    func speech(for text: String) async throws -> Data?
    func registerPush(token: String) async
    func signOut() async

    /// Answer a paused turn and stream what the Bot does next.
    func resume(
        _ pause: HitlPause, decisions: [[String: Any]], conversation: String, bot: BotProfile
    ) -> AsyncThrowingStream<StreamEvent, Error>
    /// A pause still open in a conversation just loaded with `messages(in:bot:)`.
    func openPause(in conversation: ConversationSummary) -> HitlPause?
}

extension ChatBackend {
    func accountPhoto() async -> AccountPhoto? { nil }

    func resume(
        _ pause: HitlPause, decisions: [[String: Any]], conversation: String, bot: BotProfile
    ) -> AsyncThrowingStream<StreamEvent, Error> {
        AsyncThrowingStream { $0.finish() }
    }

    func openPause(in conversation: ConversationSummary) -> HitlPause? { nil }
}
