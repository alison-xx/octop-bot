import CoreFoundation
import Foundation

/// Lynxce credits for whoever is signed in: straight with Lynxce (`LynxceBackend`), or through
/// Octop Bot cloud, which holds the Lynxce session on the user's behalf (`ServerBackend.isCloud`).
protocol CreditAccount: AnyObject {
    var signupCredits: Double? { get set }
    var signupExpiryDay: String? { get }
    func wallet() async throws -> Wallet
    func creditPacks() async throws -> (packs: [LynxceBackend.CreditPack], enabled: Bool)
    func purchaseIntent(packId: String) async throws -> (productId: String, accountToken: UUID)
    func submitTransaction(_ signedTransaction: String) async throws
    /// Delete the Lynxce account; returns the cooling-off days when the server says.
    func requestDeletion() async throws -> Int?
}

/// Only a new-account login can issue a signup grant. Restored sessions never replay it.
func newSignupCredits(_ body: [String: Any]) -> Double? {
    guard let fresh = body["isNewUser"] as? NSNumber, CFGetTypeID(fresh) == CFBooleanGetTypeID(), fresh.boolValue,
          let grant = body["signupGrant"] as? [String: Any],
          let credits = grant["credits"] as? NSNumber, CFGetTypeID(credits) != CFBooleanGetTypeID(),
          credits.doubleValue.isFinite, credits.doubleValue > 0
    else { return nil }
    return credits.doubleValue
}

func signupExpiryDayUTC(_ body: [String: Any]) -> String? {
    guard newSignupCredits(body) != nil, let grant = body["signupGrant"] as? [String: Any],
          let expiry = ISO8601.parse(grant["expiresAt"] as? String) else { return nil }
    return String(expiry.ISO8601Format().prefix(10))
}

/// One read of the Lynxce wallet: the balance and whose it is.
struct Wallet: Equatable {
    var credits: Double
    var accountId: String
}

extension LynxceBackend: CreditAccount {}

extension LynxceBackend {
    /// The App Store intent Lynxce returns (`{productId, appAccountToken}`), from either route.
    static func intent(from data: Any) throws -> (productId: String, accountToken: UUID) {
        guard
            let body = data as? [String: Any],
            let product = body["productId"] as? String,
            let token = (body["appAccountToken"] as? String).flatMap(UUID.init(uuidString:))
        else { throw APIError(kind: .server, status: 502, message: nil) }
        return (product, token)
    }
}

extension ServerBackend: CreditAccount {
    /// Octop Bot cloud keeps the Lynxce wallet; other servers have none.
    private func requireCloud() throws {
        guard isCloud else { throw APIError(kind: .rejected, status: 404, message: nil) }
    }

    func wallet() async throws -> Wallet {
        try requireCloud()
        guard let body = try await json(.get, "/api/octop-bot/wallet", query: ["source": "cloud"]) as? [String: Any],
              let credits = body["credits"] as? NSNumber
        else { throw APIError(kind: .server, status: 502, message: nil) }
        let account = (body["account_id"] as? String) ?? (body["account_id"] as? NSNumber)?.stringValue
        return Wallet(credits: credits.doubleValue, accountId: account ?? "\(host)/\(session.displayName)")
    }

    func creditPacks() async throws -> (packs: [LynxceBackend.CreditPack], enabled: Bool) {
        try requireCloud()
        return LynxceBackend.creditPacks(from: try await json(.get, "/api/octop-bot/wallet/packs"))
    }

    func purchaseIntent(packId: String) async throws -> (productId: String, accountToken: UUID) {
        try requireCloud()
        return try LynxceBackend.intent(from: try await json(.post, "/api/octop-bot/wallet/apple/intent", json: ["package_id": packId]))
    }

    func submitTransaction(_ signedTransaction: String) async throws {
        try requireCloud()
        _ = try await json(.post, "/api/octop-bot/wallet/apple/transaction", json: ["signed_transaction": signedTransaction])
    }

    func requestDeletion() async throws -> Int? {
        try requireCloud()
        let body = try await json(.post, "/api/octop-bot/account/delete") as? [String: Any]
        return (body?["cooling_days"] as? NSNumber)?.intValue
    }
}
