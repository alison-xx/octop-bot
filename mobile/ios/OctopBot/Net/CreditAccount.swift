import Foundation

/// Lynxce credits for whoever is signed in: straight with Lynxce (`LynxceBackend`), or through
/// Octop Bot cloud, which holds the Lynxce session on the user's behalf (`ServerBackend.isCloud`).
protocol CreditAccount: AnyObject {
    func balance() async -> String?
    func creditPacks() async throws -> (packs: [LynxceBackend.CreditPack], enabled: Bool)
    func purchaseIntent(packId: String) async throws -> (productId: String, accountToken: UUID)
    func submitTransaction(_ signedTransaction: String) async throws
    /// Delete the Lynxce account; returns the cooling-off days.
    func requestDeletion() async throws -> Int
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

    func balance() async -> String? {
        guard isCloud, let body = try? await json(.get, "/api/octop-bot/wallet", query: ["source": "cloud"]) as? [String: Any],
              let credits = body["credits"] as? NSNumber
        else { return nil }
        return LynxceBackend.formatCredits(credits.doubleValue)
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

    func requestDeletion() async throws -> Int {
        try requireCloud()
        let body = try await json(.post, "/api/octop-bot/account/delete") as? [String: Any]
        return body?["cooling_days"] as? Int ?? 7
    }
}
