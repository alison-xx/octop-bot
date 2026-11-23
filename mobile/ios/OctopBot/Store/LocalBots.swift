import Foundation
import Observation

/// Bots that live on this phone when signed in with a Lynxce account.
/// Built-in roles use the same shape/ink mapping as the desktop (`bot_appearance._ROLE_LOOKS`).
@Observable
final class LocalBots {
    static let shared = LocalBots()
    static let chiefId = "chief"
    private static let key = "localBots.custom"

    private(set) var custom: [BotProfile]

    init() {
        custom = (UserDefaults.standard.data(forKey: Self.key))
            .flatMap { try? JSONDecoder().decode([BotProfile].self, from: $0) } ?? []
    }

    var all: [BotProfile] { Self.builtIns + custom }

    static var builtIns: [BotProfile] {
        [
            BotProfile(
                id: chiefId, name: "Chief", subtitle: L("bot.chief.subtitle"),
                look: .chief, isChief: true, systemPrompt: L("bot.chief.prompt")
            ),
            role("researcher", "acorn", "green"),
            role("engineer", "beacon", "cobalt"),
            role("translator", "wave", "sky"),
            role("writer", "cushion", "violet"),
            role("companion", "bunny", "tangerine"),
        ]
    }

    private static func role(_ id: String, _ shape: String, _ color: String) -> BotProfile {
        BotProfile(
            id: id,
            name: L("bot.\(id).name"),
            subtitle: L("bot.\(id).subtitle"),
            look: Look(shape: shape, color: color),
            isChief: false,
            systemPrompt: L("bot.\(id).prompt")
        )
    }

    func save(_ bot: BotProfile) {
        var bot = bot
        bot.isLocal = true
        if let index = custom.firstIndex(where: { $0.id == bot.id }) {
            custom[index] = bot
        } else {
            custom.append(bot)
        }
        persist()
    }

    func delete(_ id: String) {
        custom.removeAll { $0.id == id }
        persist()
    }

    /// The account was deleted: its phone-local Bots go with it.
    func deleteAll() {
        custom = []
        persist()
    }

    private func persist() {
        UserDefaults.standard.set(try? JSONEncoder().encode(custom), forKey: Self.key)
    }
}
