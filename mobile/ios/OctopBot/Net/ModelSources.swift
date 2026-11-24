import Foundation
import Observation

// Where a Bot's replies come from (docs/octop-bot-cloud-plan.md §12.9, docs/octop-bot-saas.md):
// Lynxce models paid in credits, the user's own vendor API keys (billed by the vendor), or a model
// server on the user's own network (Ollama, LM Studio). Signed in to Octop Bot cloud the keys live in
// the account (`/api/octop-bot/model-keys`); otherwise they stay on this phone and the phone calls
// the vendor itself.

/// A model a vendor offers.
struct KeyModel: Codable, Hashable, Identifiable {
    var id: String
    var name: String

    var label: String { name.isEmpty ? id : name }
}

/// A vendor plan the user can add their own key for (`GET /model-keys/vendors`, or the bundled copy).
struct KeyVendor: Codable, Hashable, Identifiable {
    var id: String
    var name: String
    /// Company, e.g. `tencent`, `aliyun`, `volcengine`.
    var vendor: String
    var baseURL: String
    var apiKeyPrefix: String
    var docs: String?
    var models: [KeyModel]

    enum CodingKeys: String, CodingKey {
        case id, name, vendor, docs, models
        case baseURL = "base_url"
        case apiKeyPrefix = "api_key_prefix"
    }

    init(id: String, name: String, vendor: String, baseURL: String, apiKeyPrefix: String = "", docs: String? = nil, models: [KeyModel] = []) {
        self.id = id
        self.name = name
        self.vendor = vendor
        self.baseURL = baseURL
        self.apiKeyPrefix = apiKeyPrefix
        self.docs = docs
        self.models = models
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? id
        vendor = try c.decodeIfPresent(String.self, forKey: .vendor) ?? id
        baseURL = try c.decodeIfPresent(String.self, forKey: .baseURL) ?? ""
        apiKeyPrefix = try c.decodeIfPresent(String.self, forKey: .apiKeyPrefix) ?? ""
        docs = try c.decodeIfPresent(String.self, forKey: .docs)
        models = try c.decodeIfPresent([KeyModel].self, forKey: .models) ?? []
    }
}

struct VendorCatalog: Equatable {
    var vendors: [KeyVendor]
    /// Whether a custom OpenAI-compatible URL may be added (not on Octop Bot cloud).
    var customAllowed: Bool

    /// The copy bundled with the app (`mobile/scripts/vendor-catalog.py`), for keys kept on the phone.
    static let bundled: VendorCatalog = {
        let url = Bundle.main.url(forResource: "own-key-vendors", withExtension: "json")
        let vendors = url.flatMap { try? Data(contentsOf: $0) }.flatMap { try? JSONDecoder().decode([KeyVendor].self, from: $0) } ?? []
        return VendorCatalog(vendors: vendors, customAllowed: true)
    }()
}

/// A company and its plans (Tencent Cloud sells TokenHub, Coding Plan, Token Plan …).
struct VendorCompany: Identifiable, Hashable {
    var id: String
    var plans: [KeyVendor]

    static let custom = "custom"
    /// Companies shown first, in this order; the rest sit behind "More vendors" (same as the dashboard).
    static let featured = ["tencent", "aliyun", "volcengine", "deepseek", "zhipu", "kimi", "minimax", "siliconflow"]
    /// The plan picked first when a company sells several.
    static let preferredPlan = [
        "tencent": "tencent-tokenhub", "aliyun": "dashscope", "volcengine": "volcengine-cn", "zhipu": "zhipu-cn",
        "kimi": "kimi-cn", "minimax": "minimax-cn", "siliconflow": "siliconflow-cn",
    ]

    static func group(_ vendors: [KeyVendor]) -> [VendorCompany] {
        var order: [String] = []
        var plans: [String: [KeyVendor]] = [:]
        for vendor in vendors {
            if plans[vendor.vendor] == nil { order.append(vendor.vendor) }
            plans[vendor.vendor, default: []].append(vendor)
        }
        func rank(_ id: String) -> Int { featured.firstIndex(of: id) ?? featured.count }
        let companies = order.enumerated().map { index, id in
            let preferred = preferredPlan[id]
            let sorted = plans[id]!.enumerated().sorted { a, b in
                let pa = a.element.id == preferred, pb = b.element.id == preferred
                return pa != pb ? pa : a.offset < b.offset
            }.map(\.element)
            return (index, VendorCompany(id: id, plans: sorted))
        }
        return companies.sorted { a, b in
            let ra = rank(a.1.id), rb = rank(b.1.id)
            return ra != rb ? ra < rb : a.0 < b.0
        }.map(\.1)
    }

    var isFeatured: Bool { Self.featured.contains(id) }

    /// "腾讯云", "阿里云百炼" …; other companies use the catalog's name.
    var name: String { Self.name(of: id, fallback: plans.first?.name ?? id) }

    static func name(of company: String, fallback: String) -> String {
        let key = "models.company.\(company)"
        let named = L(key)
        return named == key ? fallback : named
    }
}

/// One of the user's own keys. The key itself never comes back, only `****` and its last four.
struct OwnKey: Identifiable, Hashable {
    var id: String
    var vendor: String
    var name: String
    var baseURL: String
    var keyHint: String
    var models: [KeyModel]

    /// "腾讯云", "DeepSeek", or the name given to a custom endpoint.
    var displayName: String {
        guard vendor != VendorCompany.custom else { return name }
        let company = VendorCatalog.bundled.vendors.first { $0.id == vendor }?.vendor ?? vendor
        return VendorCompany.name(of: company, fallback: name)
    }

    var company: String {
        vendor == VendorCompany.custom ? VendorCompany.custom : (VendorCatalog.bundled.vendors.first { $0.id == vendor }?.vendor ?? vendor)
    }
}

struct OwnKeyList: Equatable {
    var keys: [OwnKey]
    /// Id of the key the user chats on, if any.
    var inUse: String?
    var selectedModel: String?

    static let empty = OwnKeyList(keys: [], inUse: nil, selectedModel: nil)

    static func parse(_ data: Any) -> OwnKeyList {
        let body = data as? [String: Any] ?? [:]
        let keys = (body["keys"] as? [[String: Any]] ?? []).compactMap(ownKey)
        return OwnKeyList(keys: keys, inUse: body["in_use"] as? String, selectedModel: body["selected_model"] as? String)
    }

    static func ownKey(_ row: [String: Any]) -> OwnKey? {
        guard let id = row["id"] as? String else { return nil }
        let models = (row["models"] as? [[String: Any]] ?? []).compactMap { m -> KeyModel? in
            guard let id = m["id"] as? String else { return nil }
            return KeyModel(id: id, name: m["name"] as? String ?? id)
        }
        return OwnKey(
            id: id, vendor: row["vendor"] as? String ?? "", name: row["name"] as? String ?? "",
            baseURL: row["base_url"] as? String ?? "", keyHint: row["key_hint"] as? String ?? "****", models: models
        )
    }
}

/// What "Add API key" sends.
struct NewOwnKey {
    var vendor: String
    var apiKey: String
    var name: String? = nil
    var baseURL: String? = nil
}

/// The user's own keys, kept by Octop Bot cloud or on this phone.
protocol ModelKeyStore: AnyObject {
    /// True when keys stay on this phone (not signed in to Octop Bot cloud).
    var onPhone: Bool { get }
    func vendors() async throws -> VendorCatalog
    func list() async throws -> OwnKeyList
    /// Checks the key with the vendor's model list before keeping it.
    func add(_ key: NewOwnKey) async throws -> OwnKey
    func remove(_ id: String) async throws
    /// Chat on this key's model from now on.
    func use(_ id: String, model: String) async throws -> OwnKeyList
}

/// Octop Bot cloud: `/api/octop-bot/model-keys`. Errors come back localized by the server.
final class ServerModelKeys: ModelKeyStore {
    private let server: ServerBackend
    private static let base = "/api/octop-bot/model-keys"

    init(server: ServerBackend) { self.server = server }

    var onPhone: Bool { false }

    func vendors() async throws -> VendorCatalog {
        let data = try await server.raw(.get, Self.base + "/vendors")
        return try Self.catalog(data)
    }

    static func catalog(_ data: Data) throws -> VendorCatalog {
        struct Body: Decodable {
            var vendors: [KeyVendor]
            var custom_allowed: Bool?
        }
        let body = try JSONDecoder().decode(Body.self, from: data)
        // Phones show the same "get a key" pages as the bundled list.
        let docs = Dictionary(VendorCatalog.bundled.vendors.map { ($0.id, $0.docs) }, uniquingKeysWith: { a, _ in a })
        let vendors = body.vendors.map { vendor in
            var vendor = vendor
            if vendor.docs == nil { vendor.docs = docs[vendor.id] ?? nil }
            return vendor
        }
        return VendorCatalog(vendors: vendors, customAllowed: body.custom_allowed ?? false)
    }

    func list() async throws -> OwnKeyList {
        OwnKeyList.parse(try await server.json(.get, Self.base))
    }

    func add(_ key: NewOwnKey) async throws -> OwnKey {
        var body: [String: Any] = ["vendor": key.vendor, "api_key": key.apiKey]
        if let name = key.name, !name.isEmpty { body["name"] = name }
        if let url = key.baseURL, !url.isEmpty { body["base_url"] = url }
        // The vendor may take a while to answer its model list.
        let data = try await server.json(.post, Self.base, json: body, timeout: 45)
        guard let row = data as? [String: Any], let added = OwnKeyList.ownKey(row) else {
            throw APIError(kind: .server, status: 502, message: nil)
        }
        return added
    }

    func remove(_ id: String) async throws {
        _ = try await server.raw(.delete, Self.base + "/" + Self.escape(id))
    }

    func use(_ id: String, model: String) async throws -> OwnKeyList {
        OwnKeyList.parse(try await server.json(.put, Self.base + "/" + Self.escape(id) + "/model", json: ["model_id": model]))
    }

    private static func escape(_ id: String) -> String {
        id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed.subtracting(CharacterSet(charactersIn: "/"))) ?? id
    }
}

/// An OpenAI-compatible chat endpoint the phone calls itself.
struct ModelEndpoint: Equatable {
    var baseURL: URL
    var apiKey: String?
    var model: String

    var completionsURL: URL { baseURL.appending(path: "chat/completions") }

    var headers: [String: String] {
        apiKey.map { ["Authorization": "Bearer \($0)"] } ?? [:]
    }
}

/// A model server on the user's network (Ollama, LM Studio) the phone talks to directly.
struct LocalServer: Codable, Hashable, Identifiable {
    var id: String
    var name: String
    /// The OpenAI-compatible base, ending in `/v1`.
    var baseURL: String
    var models: [KeyModel]

    /// "192.168.1.8:11434" for the row's second line.
    var host: String {
        guard let url = URL(string: baseURL), let host = url.host() else { return baseURL }
        return url.port.map { "\(host):\($0)" } ?? host
    }
}

/// What the phone chats on when it calls a model itself: an own key's model or a local server's.
struct PhoneSelection: Codable, Equatable {
    enum Source: String, Codable { case key, local }
    var source: Source
    var id: String
    var model: String
}

/// Keys and local servers kept on this phone (not signed in, or signed in to Lynxce directly).
/// Key metadata sits in UserDefaults; each API key itself only in the Keychain.
@Observable
final class PhoneModels: ModelKeyStore {
    static let shared = PhoneModels()
    static let maxKeys = 20

    private struct StoredKey: Codable {
        var id: String
        var vendor: String
        var name: String
        var baseURL: String
        var hint: String
        var models: [KeyModel]
    }

    private static let keysKey = "models.phone.keys"
    private static let localKey = "models.phone.local"
    private static let selectionKey = "models.phone.selection"

    private var stored: [StoredKey]
    private(set) var local: [LocalServer]
    /// nil: Lynxce's model when signed in to Lynxce; no model at all otherwise.
    private(set) var selection: PhoneSelection?
    private let defaults: UserDefaults
    private let secrets: (String) -> String?
    private let saveSecret: (String?, String) -> Void

    init(
        defaults: UserDefaults = .standard,
        secrets: @escaping (String) -> String? = { Keychain.get("models.key.\($0)").flatMap { String(data: $0, encoding: .utf8) } },
        saveSecret: @escaping (String?, String) -> Void = { value, id in Keychain.set(value.map { Data($0.utf8) }, for: "models.key.\(id)") }
    ) {
        self.defaults = defaults
        self.secrets = secrets
        self.saveSecret = saveSecret
        stored = defaults.data(forKey: Self.keysKey).flatMap { try? JSONDecoder().decode([StoredKey].self, from: $0) } ?? []
        local = defaults.data(forKey: Self.localKey).flatMap { try? JSONDecoder().decode([LocalServer].self, from: $0) } ?? []
        selection = defaults.data(forKey: Self.selectionKey).flatMap { try? JSONDecoder().decode(PhoneSelection.self, from: $0) }
    }

    var onPhone: Bool { true }

    var keys: [OwnKey] {
        stored.map { OwnKey(id: $0.id, vendor: $0.vendor, name: $0.name, baseURL: $0.baseURL, keyHint: $0.hint, models: $0.models) }
    }

    /// Something to chat on without a Lynxce account.
    var hasModel: Bool { endpoint() != nil }

    func vendors() async throws -> VendorCatalog { VendorCatalog.bundled }

    func list() async throws -> OwnKeyList { snapshot }

    var snapshot: OwnKeyList {
        let inUse = selection?.source == .key ? selection?.id : nil
        return OwnKeyList(keys: keys, inUse: inUse, selectedModel: inUse == nil ? nil : selection?.model)
    }

    /// The model in use and where it runs, for the Settings row: ("deepseek-flash", "DeepSeek").
    var current: (model: String, source: String)? {
        guard let selection else { return nil }
        switch selection.source {
        case .key: return keys.first { $0.id == selection.id }.map { (selection.model, $0.displayName) }
        case .local: return local.first { $0.id == selection.id }.map { (selection.model, $0.name) }
        }
    }

    func add(_ key: NewOwnKey) async throws -> OwnKey {
        guard stored.count < Self.maxKeys else { throw Self.error("models.error.limit") }
        let apiKey = key.apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let vendor: KeyVendor
        if key.vendor == VendorCompany.custom {
            guard let base = Self.normalizedBase(key.baseURL ?? "") else { throw Self.error("models.error.url") }
            let name = (key.name ?? "").trimmingCharacters(in: .whitespaces)
            vendor = KeyVendor(id: VendorCompany.custom, name: name.isEmpty ? (URL(string: base)?.host() ?? base) : name, vendor: VendorCompany.custom, baseURL: base)
        } else {
            guard let found = VendorCatalog.bundled.vendors.first(where: { $0.id == key.vendor }) else {
                throw Self.error("models.error.unknownVendor")
            }
            vendor = found
        }
        guard let base = URL(string: vendor.baseURL) else { throw Self.error("models.error.url") }
        var models = try await Self.listModels(base: base, apiKey: apiKey)
        if models.isEmpty { models = vendor.models }
        let id = UUID().uuidString.lowercased()
        let hint = apiKey.count > 8 ? "****" + apiKey.suffix(4) : "****"
        saveSecret(apiKey, id)
        stored.append(StoredKey(id: id, vendor: vendor.id, name: vendor.name, baseURL: vendor.baseURL, hint: hint, models: models))
        save()
        return keys.last!
    }

    func remove(_ id: String) async throws {
        stored.removeAll { $0.id == id }
        saveSecret(nil, id)
        if selection?.source == .key && selection?.id == id { setSelection(nil) }
        save()
    }

    func use(_ id: String, model: String) async throws -> OwnKeyList {
        guard keys.contains(where: { $0.id == id }) else { throw APIError(kind: .rejected, status: 404, message: nil) }
        setSelection(PhoneSelection(source: .key, id: id, model: model))
        return snapshot
    }

    /// Back to Lynxce's models (signed in to Lynxce), or no model.
    func useLynxce() { setSelection(nil) }

    func useLocal(_ id: String, model: String) {
        setSelection(PhoneSelection(source: .local, id: id, model: model))
    }

    /// Find the models of an Ollama / LM Studio server at this address and keep it.
    func addLocal(address: String) async throws -> LocalServer {
        guard let base = Self.localBase(address) else { throw Self.error("models.error.url") }
        let models: [KeyModel]
        do {
            models = try await Self.listModels(base: base, apiKey: nil, timeout: 8)
        } catch let error as APIError where error.kind == .network {
            throw Self.error("models.local.unreachable")
        }
        guard !models.isEmpty else { throw Self.error("models.local.noModels") }
        let port = base.port
        let name = port == 1234 ? "LM Studio" : (port == 11434 ? "Ollama" : (base.host() ?? address))
        let server = LocalServer(id: UUID().uuidString.lowercased(), name: name, baseURL: base.absoluteString, models: models)
        local.removeAll { $0.baseURL == server.baseURL }
        local.append(server)
        save()
        return server
    }

    func removeLocal(_ id: String) {
        local.removeAll { $0.id == id }
        if selection?.source == .local && selection?.id == id { setSelection(nil) }
        save()
    }

    /// Where the phone sends a chat when it calls the model itself; nil means Lynxce (or nothing).
    func endpoint() -> ModelEndpoint? {
        guard let selection else { return nil }
        switch selection.source {
        case .key:
            guard let key = stored.first(where: { $0.id == selection.id }), let base = URL(string: key.baseURL),
                  let secret = secrets(key.id) else { return nil }
            return ModelEndpoint(baseURL: base, apiKey: secret, model: selection.model)
        case .local:
            guard let server = local.first(where: { $0.id == selection.id }), let base = URL(string: server.baseURL) else { return nil }
            return ModelEndpoint(baseURL: base, apiKey: nil, model: selection.model)
        }
    }

    private func setSelection(_ next: PhoneSelection?) {
        selection = next
        defaults.set(next.flatMap { try? JSONEncoder().encode($0) }, forKey: Self.selectionKey)
    }

    private func save() {
        defaults.set(try? JSONEncoder().encode(stored), forKey: Self.keysKey)
        defaults.set(try? JSONEncoder().encode(local), forKey: Self.localKey)
    }

    private static func error(_ key: String) -> APIError {
        APIError(kind: .rejected, status: 400, message: L(key))
    }

    /// A custom OpenAI-compatible base: http(s), no trailing slash, no `/chat/completions`.
    static func normalizedBase(_ text: String) -> String? {
        var value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        for suffix in ["/chat/completions", "/"] where value.hasSuffix(suffix) { value.removeLast(suffix.count) }
        guard let url = URL(string: value), let scheme = url.scheme?.lowercased(), ["http", "https"].contains(scheme),
              url.host() != nil else { return nil }
        return value
    }

    /// "192.168.1.8" → "http://192.168.1.8:11434/v1"; a typed port or `/v1` is kept.
    static func localBase(_ text: String) -> URL? {
        var value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return nil }
        if !value.contains("://") { value = "http://" + value }
        while value.hasSuffix("/") { value.removeLast() }
        guard var components = URLComponents(string: value), components.host?.isEmpty == false else { return nil }
        if components.port == nil { components.port = 11434 }
        if !components.path.hasSuffix("/v1") { components.path += "/v1" }
        return components.url
    }

    /// `GET {base}/models`. A vendor that refuses the key (401/403) means the key is wrong.
    static func listModels(base: URL, apiKey: String?, timeout: TimeInterval = 20) async throws -> [KeyModel] {
        var request = try HTTP.request(base.appending(path: "models"), headers: apiKey.map { ["Authorization": "Bearer \($0)"] } ?? [:])
        request.timeoutInterval = timeout
        let (data, response) = try await HTTP.data(for: request)
        switch response.statusCode {
        case 200..<300: return parseModels(data)
        case 401, 403: throw APIError(kind: .rejected, status: response.statusCode, message: L("models.error.invalidKey"), code: "BOT_MODEL_KEY_INVALID")
        // Some vendors have no model list; the catalog's suggestions stand in.
        case 404, 405: return []
        default:
            throw APIError(kind: .rejected, status: response.statusCode, message: L("models.error.vendor %lld", response.statusCode))
        }
    }

    static func parseModels(_ data: Data) -> [KeyModel] {
        guard let body = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [] }
        let rows = body["data"] as? [[String: Any]] ?? body["models"] as? [[String: Any]] ?? []
        var seen = Set<String>()
        return rows.compactMap { row in
            guard let id = (row["id"] ?? row["name"] ?? row["model"]) as? String, seen.insert(id).inserted else { return nil }
            return KeyModel(id: id, name: id)
        }
    }
}
