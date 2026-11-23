import CryptoKit
import Foundation
import Observation

/// Checks the signed Octop Bot release manifest for a newer iOS version.
/// iOS apps cannot install themselves, so an update opens the App Store or TestFlight link.
/// Format and rules: docs/octop-bot-updates.md.
@Observable
final class AppUpdater {
    static let shared = AppUpdater()

    enum Status: Equatable {
        case idle
        case checking
        case upToDate
        case available(version: String, url: URL, urgent: Bool)
        case failed
    }

    struct Release: Equatable {
        var version: String
        var url: URL
        var urgent: Bool
    }

    static let manifestURL = URL(string: "https://dl.lynxce.cn/releases/octop-bot/manifest.json")!
    /// Raw 32-byte Ed25519 public key of the release signing key (same key as desktop and server).
    static let publicKey = "jfzS5kpiVxqx/79rU5tYno7Js31ezDt05RmrmXnRTa0="
    static let checkInterval: TimeInterval = 24 * 60 * 60

    private(set) var status: Status = .idle
    var receiveBeta: Bool {
        didSet { UserDefaults.standard.set(receiveBeta, forKey: "update.beta") }
    }
    private(set) var dismissedVersion: String?

    private var running: Task<Void, Never>?

    init() {
        receiveBeta = UserDefaults.standard.bool(forKey: "update.beta")
        dismissedVersion = UserDefaults.standard.string(forKey: "update.dismissed")
    }

    var installedVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"
    }

    /// The release to show in the home banner, unless the user closed it for this version.
    var bannerRelease: Release? {
        guard case .available(let version, let url, let urgent) = status, version != dismissedVersion else { return nil }
        return Release(version: version, url: url, urgent: urgent)
    }

    func dismissBanner() {
        guard case .available(let version, _, _) = status else { return }
        dismissedVersion = version
        UserDefaults.standard.set(version, forKey: "update.dismissed")
    }

    /// Check when the last check is older than a day (launch and return to foreground).
    func checkIfDue() {
        let last = UserDefaults.standard.double(forKey: "update.lastCheck")
        guard Date().timeIntervalSince1970 - last > Self.checkInterval else { return }
        check()
    }

    /// Check now. Quiet: a failure only shows as a status in Settings.
    @discardableResult
    func check() -> Task<Void, Never> {
        if let running { return running }
        status = .checking
        let task = Task { [weak self] in
            guard let self else { return }
            defer { self.running = nil }
            do {
                let (body, signature) = try await Self.fetch()
                let manifest = try Self.verify(body, signature: signature, publicKey: Self.overrideKey ?? Self.publicKey)
                UserDefaults.standard.set(Date().timeIntervalSince1970, forKey: "update.lastCheck")
                if let release = Self.select(
                    manifest, installed: installedVersion, receiveBeta: receiveBeta, installId: Self.installId
                ) {
                    status = .available(version: release.version, url: release.url, urgent: release.urgent)
                } else {
                    status = .upToDate
                }
            } catch {
                status = .failed
            }
        }
        running = task
        return task
    }

    // MARK: Network

    private static func fetch() async throws -> (Data, String) {
        let url = overrideURL ?? manifestURL
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 20)
        request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        let (body, response) = try await URLSession.shared.data(for: request)
        var sigRequest = request
        sigRequest.url = url.appendingPathExtension("sig")
        let (sig, sigResponse) = try await URLSession.shared.data(for: sigRequest)
        guard (response as? HTTPURLResponse)?.statusCode == 200, (sigResponse as? HTTPURLResponse)?.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }
        return (body, String(decoding: sig, as: UTF8.self))
    }

    /// Debug builds can point at a local test manifest and key (Settings → update.* defaults).
    private static var overrideURL: URL? {
        #if DEBUG
        UserDefaults.standard.string(forKey: "update.debugManifestURL").flatMap(URL.init(string:))
        #else
        nil
        #endif
    }

    private static var overrideKey: String? {
        #if DEBUG
        UserDefaults.standard.string(forKey: "update.debugPublicKey")
        #else
        nil
        #endif
    }

    private static var installId: String {
        if let id = UserDefaults.standard.string(forKey: "update.installId") { return id }
        let id = UUID().uuidString
        UserDefaults.standard.set(id, forKey: "update.installId")
        return id
    }

    // MARK: Pure logic (unit-tested)

    enum UpdateError: Error { case badSignature, badManifest }

    /// The manifest, when its detached Ed25519 signature matches the exact bytes.
    static func verify(_ body: Data, signature: String, publicKey: String) throws -> [String: Any] {
        guard
            let keyData = Data(base64Encoded: publicKey),
            let key = try? Curve25519.Signing.PublicKey(rawRepresentation: keyData),
            let signatureData = Data(base64Encoded: signature.trimmingCharacters(in: .whitespacesAndNewlines)),
            key.isValidSignature(signatureData, for: body)
        else { throw UpdateError.badSignature }
        guard
            let manifest = try JSONSerialization.jsonObject(with: body) as? [String: Any],
            manifest["product"] as? String == "octop-bot"
        else { throw UpdateError.badManifest }
        return manifest
    }

    /// The newest iOS release this install should be offered, or nil when current.
    static func select(_ manifest: [String: Any], installed: String, receiveBeta: Bool, installId: String) -> Release? {
        let channels = manifest["channels"] as? [String: Any] ?? [:]
        var best: Release?
        for name in receiveBeta ? ["stable", "beta"] : ["stable"] {
            guard
                let entry = channels[name] as? [String: Any],
                let ios = (entry["assets"] as? [String: Any])?["ios"] as? [String: Any],
                let version = ios["version"] as? String,
                let link = (ios["url"] as? String).flatMap(URL.init(string:)), link.scheme == "https",
                compare(version, installed) == .orderedDescending
            else { continue }
            let rollout = entry["rollout"] as? Int ?? 100
            let releaseVersion = entry["version"] as? String ?? version
            guard rollout >= 100 || (rollout > 0 && bucket(installId: installId, version: releaseVersion) < rollout) else { continue }
            let minimum = ios["min_version"] as? String
            let urgent = minimum.map { compare($0, installed) == .orderedDescending } ?? false
            if best == nil || compare(version, best!.version) == .orderedDescending {
                best = Release(version: version, url: link, urgent: urgent)
            }
        }
        return best
    }

    /// Stable 0–99 rollout bucket: first 4 bytes of SHA-256("installId:version"), big-endian.
    static func bucket(installId: String, version: String) -> Int {
        let digest = Array(SHA256.hash(data: Data("\(installId):\(version)".utf8)))
        let value = UInt32(digest[0]) << 24 | UInt32(digest[1]) << 16 | UInt32(digest[2]) << 8 | UInt32(digest[3])
        return Int(value % 100)
    }

    /// Dotted numeric comparison: "0.10.0" > "0.9.1"; missing parts count as 0.
    static func compare(_ a: String, _ b: String) -> ComparisonResult {
        func parts(_ v: String) -> [Int] {
            v.split(whereSeparator: { !$0.isNumber }).map { Int($0) ?? 0 }
        }
        let pa = parts(a), pb = parts(b)
        for i in 0..<max(pa.count, pb.count) {
            let x = i < pa.count ? pa[i] : 0, y = i < pb.count ? pb[i] : 0
            if x != y { return x < y ? .orderedAscending : .orderedDescending }
        }
        return .orderedSame
    }
}
