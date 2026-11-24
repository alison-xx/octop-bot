import Foundation
import Observation
import StoreKit

/// Whether this build offers App Store credit packs. Off until the products have been through App
/// Review: the app then shows the balance but no way to buy, whatever Lynxce's own switch says, so a
/// switch flipped during review cannot expose purchases Apple has not seen.
enum CreditPurchases {
    nonisolated static let inApp = false
}

/// Lynxce credit packs bought with App Store in-app purchase (StoreKit 2).
///
/// Flow: Lynxce issues an account token for the pack → StoreKit purchase carries that token →
/// the signed transaction goes to Lynxce, which verifies it with Apple and credits the wallet →
/// only then is the transaction finished. Unfinished transactions (network failure, app killed,
/// bought while signed in as someone else) stay in StoreKit's queue and are reported again on the
/// next launch or sign-in. Lynxce checks that the transaction's account token is the signed-in
/// account's (`apple_account_token_mismatch` otherwise, which stays queued for that account); a
/// transaction it can never credit is finished so it is not sent again on every launch.
@Observable
final class CreditStore {
    static let shared = CreditStore()

    struct Offer: Identifiable {
        let pack: LynxceBackend.CreditPack
        let product: Product
        var id: String { pack.id }
    }

    enum Phase: Equatable { case idle, loading, ready, unavailable, failed(String) }

    enum Outcome: Equatable { case credited, pending, cancelled, failed(String) }

    /// What Lynxce made of one transaction.
    enum Delivery: Equatable { case credited, queued, refused(String) }

    /// Lynxce error codes for a transaction that can never be credited, whoever reports it:
    /// bad or foreign signed data, family sharing, a sandbox purchase in production, one already
    /// credited to another account, or one with no account token (credit packs cannot be
    /// restored). Not `apple_account_token_mismatch`: that purchase belongs to another account
    /// that may sign in on this phone, and finishing it would lose its credits.
    nonisolated static let finalRefusals: Set<String> = [
        "apple_jws_malformed", "apple_jws_invalid", "apple_app_mismatch",
        "apple_family_sharing_unsupported", "apple_sandbox_rejected",
        "apple_transaction_owned_by_other_account", "apple_account_token_missing",
    ]

    private(set) var phase: Phase = .idle
    private(set) var offers: [Offer] = []
    private(set) var buying: String?

    /// The signed-in Lynxce wallet; nil while signed out or on a server without one.
    private var account: () -> CreditAccount? = { nil }
    /// Called after Lynxce credits a purchase, so the balance on screen catches up.
    private var credited: () async -> Void = {}
    private var updates: Task<Void, Never>?

    /// Start listening for transactions that finish outside a purchase sheet (Ask to Buy, retries).
    func start(account: @escaping () -> CreditAccount?, credited: @escaping () async -> Void) {
        self.account = account
        self.credited = credited
        guard updates == nil else { return }
        updates = Task { [weak self] in
            for await result in Transaction.updates {
                guard let self else { return }
                if await self.deliver(result) == .credited { await self.credited() }
            }
        }
    }

    /// Report transactions an earlier run could not hand to Lynxce.
    func flush() async {
        var any = false
        for await result in Transaction.unfinished where Self.isCreditPack(result.unsafePayloadValue.productID) {
            if await deliver(result) == .credited { any = true }
        }
        if any { await credited() }
    }

    func load() async {
        guard CreditPurchases.inApp, let account = account() else {
            phase = .unavailable
            return
        }
        if offers.isEmpty { phase = .loading }
        do {
            let (packs, enabled) = try await account.creditPacks()
            guard enabled, !packs.isEmpty else {
                offers = []
                phase = .unavailable
                return
            }
            let products = try await Product.products(for: packs.map(\.productId))
            let byId = Dictionary(products.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
            offers = packs.compactMap { pack in byId[pack.productId].map { Offer(pack: pack, product: $0) } }
            phase = offers.isEmpty ? .unavailable : .ready
        } catch {
            phase = .failed(error.localizedDescription)
        }
    }

    func buy(_ offer: Offer) async -> Outcome {
        guard CreditPurchases.inApp else { return .failed(L("credits.unavailable")) }
        guard buying == nil, let account = account() else { return .failed(L("credits.signInFirst")) }
        buying = offer.id
        defer { buying = nil }
        do {
            let intent = try await account.purchaseIntent(packId: offer.pack.id)
            guard intent.productId == offer.product.id else { return .failed(L("credits.unavailable")) }
            let result = try await offer.product.purchase(options: [.appAccountToken(intent.accountToken)])
            switch result {
            case .success(let verification):
                switch await deliver(verification) {
                case .credited:
                    await credited()
                    return .credited
                case .queued:
                    return .failed(L("credits.deliveryPending"))
                case .refused(let reason):
                    return .failed(reason)
                }
            case .pending:
                return .pending
            case .userCancelled:
                return .cancelled
            @unknown default:
                return .cancelled
            }
        } catch {
            return .failed(error.localizedDescription)
        }
    }

    /// Hand one transaction to Lynxce; finish it only once Lynxce has accepted it, or has refused it
    /// for good.
    private func deliver(_ result: VerificationResult<Transaction>) async -> Delivery {
        let transaction = result.unsafePayloadValue
        guard Self.isCreditPack(transaction.productID), let account = account() else { return .queued }
        // Lynxce verifies the JWS signature itself; a locally unverified result is still reported
        // so the server makes the call, and is never finished unless the server accepts it.
        do {
            try await account.submitTransaction(result.jwsRepresentation)
        } catch let error as APIError where Self.isFinalRefusal(error) {
            await transaction.finish()
            return .refused(error.localizedDescription)
        } catch {
            // Offline, signed out, or bought for another account on this phone: keep it queued so
            // it is reported again later; Lynxce credits each transaction once however often it arrives.
            return .queued
        }
        await transaction.finish()
        return .credited
    }

    nonisolated static func isFinalRefusal(_ error: APIError) -> Bool {
        error.kind == .rejected && error.code.map(finalRefusals.contains) == true
    }

    nonisolated static func isCreditPack(_ productId: String) -> Bool {
        productId.hasPrefix(LynxceBackend.iapApp + ".")
    }
}
