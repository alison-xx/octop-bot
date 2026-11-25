import StoreKit
import StoreKitTest
import XCTest

/// Select the Xcode store in a separate host launch. On a fresh simulator StoreKit can
/// otherwise keep the initial Sandbox purchase connection for the life of that process.
@MainActor
final class StoreKitSetupTests: XCTestCase {
    func testActivateLocalStore() async throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "CreditPacks", withExtension: "storekit"))
        let session = try SKTestSession(contentsOf: url)
        session.disableDialogs = true
        let sku = "cn.lynxce.octopbot.credits.5000"
        let products = try await Product.products(for: [sku])
        XCTAssertEqual(products.map(\.id), [sku])
    }
}
