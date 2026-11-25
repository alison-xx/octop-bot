import Foundation
import Security

/// Small Keychain wrapper for tokens. Values never leave this device's Keychain.
enum Keychain {
    private static let service = "io.github.alisonxx.octopbot"

    static func set(_ value: Data?, for key: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]
        SecItemDelete(query as CFDictionary)
        guard let value else { return }
        var item = query
        item[kSecValueData as String] = value
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(item as CFDictionary, nil)
    }

    static func get(_ key: String) -> Data? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var out: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &out) == errSecSuccess else { return nil }
        return out as? Data
    }

    /// A delayed rotation or logout may only change the exact credential that initiated it.
    @discardableResult
    static func replace<T: Codable & Equatable>(_ expected: T, with next: T?, for key: String) -> Bool {
        guard codable(T.self, for: key) == expected else { return false }
        if let next { setCodable(next, for: key) } else { set(nil, for: key) }
        return true
    }

    static func setCodable<T: Encodable>(_ value: T?, for key: String) {
        set(value.flatMap { try? JSONEncoder().encode($0) }, for: key)
    }

    static func codable<T: Decodable>(_ type: T.Type, for key: String) -> T? {
        get(key).flatMap { try? JSONDecoder().decode(T.self, from: $0) }
    }
}
