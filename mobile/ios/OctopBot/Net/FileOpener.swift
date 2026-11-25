import CryptoKit
import QuickLook
import QuickLookThumbnailing
import UIKit

@MainActor
protocol AttachmentSource: AnyObject {
    var attachmentOrigin: URL { get }
    var attachmentLoginIsCurrent: Bool { get }
    func attachmentOwner() async throws -> String
    func fileData(for url: URL) async throws -> Data
    func fileSize(for url: URL) async -> Int64?
}

extension ServerBackend: AttachmentSource {
    var attachmentOrigin: URL { session.baseURL }

    /// `/api/agents/{id}/workspace/download?path=…`, the link Octop puts in a reply for a file.
    nonisolated static func isWorkspaceDownload(_ url: URL) -> Bool {
        guard url.host() == nil || url.scheme == nil else { return false }
        let parts = url.path().split(separator: "/")
        return parts.count == 5 && parts[0] == "api" && parts[1] == "agents" && parts[3] == "workspace" && parts[4] == "download"
    }

    /// Path and query of a server-relative link.
    private static func parts(_ url: URL) -> (path: String, query: [String: String]) {
        let query = (URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? [])
            .reduce(into: [String: String]()) { $0[$1.name] = $1.value }
        return (url.path(), query)
    }

    /// Octop Bot cloud: a short-lived link to the file in the object store.
    func downloadLink(for url: URL) async throws -> URL {
        let (path, query) = Self.parts(url)
        let body = try await json(.post, path + "-link", query: query) as? [String: Any]
        // https, or plain http only when this server is itself http (no downgrade).
        guard let link = (body?["url"] as? String).flatMap(URL.init(string:)),
              link.scheme == "https" || link.scheme == session.baseURL.scheme else {
            throw APIError(kind: .server, status: 502, message: nil)
        }
        return link
    }

    /// The file's bytes: on Octop Bot cloud a workspace file comes from the object store, anything else
    /// (and every other server) with this session.
    func fileData(for url: URL) async throws -> Data {
        if isCloud, Self.isWorkspaceDownload(url) {
            let request = URLRequest(url: try await downloadLink(for: url), timeoutInterval: 300)
            let (data, response) = try await HTTP.data(for: request)
            guard (200..<300).contains(response.statusCode) else { throw APIError.from(status: response.statusCode, message: nil) }
            return data
        }
        let (path, query) = Self.parts(url)
        return try await raw(.get, path, query: query, timeout: 300)
    }

    /// `HEAD` on a workspace download: the file's size without its bytes (nil on older servers).
    func fileSize(for url: URL) async -> Int64? {
        let (path, query) = Self.parts(url)
        guard var request = try? HTTP.request(self.url(path, query: query), method: .head, headers: authHeaders) else { return nil }
        request.timeoutInterval = 20
        guard let response = try? await HTTP.data(for: request).1, response.statusCode == 200 else { return nil }
        if let header = response.value(forHTTPHeaderField: "Content-Length"), let size = Int64(header) { return size }
        return response.expectedContentLength >= 0 ? response.expectedContentLength : nil
    }
}

/// One signed-in session owns its in-flight work and presentations. Disk reuse requires
/// the same verified login record and server, including when restarting offline.
@MainActor @Observable
final class AttachmentStore {
    static let thumbnailLimit: Int64 = 20 * 1024 * 1024
    private(set) var isActive = true
    var canAccess: Bool { isActive && source?.attachmentLoginIsCurrent == true }
    @ObservationIgnored private weak var source: (any AttachmentSource)?
    private let cacheRoot: URL
    @ObservationIgnored private var owner: Task<String, Error>?
    @ObservationIgnored private var sizes: [String: Task<Int64?, Never>] = [:]
    @ObservationIgnored private var files: [String: Task<URL, Error>] = [:]
    @ObservationIgnored private var thumbnails: [String: Task<UIImage?, Never>] = [:]
    private let presentations = NSHashTable<UIViewController>.weakObjects()

    init(source: any AttachmentSource, cacheRoot: URL = .cachesDirectory) {
        self.source = source
        self.cacheRoot = cacheRoot
    }

    func invalidate() {
        guard isActive else { return }
        isActive = false
        owner?.cancel()
        for task in sizes.values { task.cancel() }
        for task in files.values { task.cancel() }
        for task in thumbnails.values { task.cancel() }
        sizes.removeAll()
        files.removeAll()
        thumbnails.removeAll()
        for controller in presentations.allObjects { controller.dismiss(animated: false) }
        presentations.removeAllObjects()
    }

    func present(_ controller: UIViewController) {
        guard canAccess else { return }
        presentations.add(controller)
        FileOpener.present(controller)
    }

    private func key(_ file: FileAttachment) async throws -> String {
        guard canAccess, let source else { throw CancellationError() }
        let task = owner ?? Task { try await source.attachmentOwner() }
        owner = task
        let id: String
        do { id = try await task.value } catch { owner = nil; throw error }
        guard canAccess else { throw CancellationError() }
        let data = try JSONEncoder().encode([source.attachmentOrigin.absoluteString, id, file.url])
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private func cachedFile(_ file: FileAttachment, key: String) -> URL {
        cacheRoot.appending(path: "attachments-v2", directoryHint: .isDirectory)
            .appending(path: key, directoryHint: .isDirectory)
            .appending(path: Self.safeName(file.name))
    }

    func size(of file: FileAttachment) async -> Int64? {
        guard let key = try? await key(file), let source else { return nil }
        if let size = file.size { return size }
        if let bytes = try? cachedFile(file, key: key).resourceValues(forKeys: [.fileSizeKey]).fileSize {
            return Int64(bytes)
        }
        guard file.isWorkspaceDownload, let url = URL(string: file.url) else { return nil }
        let task = sizes[key] ?? Task { await source.fileSize(for: url) }
        sizes[key] = task
        let value = await task.value
        return canAccess ? value : nil
    }

    func localFile(_ file: FileAttachment) async throws -> URL {
        let key = try await key(file)
        guard canAccess, let source, let url = URL(string: file.url) else { throw CancellationError() }
        let target = cachedFile(file, key: key)
        if FileManager.default.fileExists(atPath: target.path()) { return target }
        let task = files[key] ?? Task<URL, Error> {
            let data = try await source.fileData(for: url)
            try Task.checkCancellation()
            guard self.canAccess else { throw CancellationError() }
            try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: target, options: .atomic)
            return target
        }
        files[key] = task
        defer { files[key] = nil }
        let result = try await task.value
        guard canAccess else { throw CancellationError() }
        return result
    }

    func thumbnail(_ file: FileAttachment, size: CGSize, scale: CGFloat) async -> UIImage? {
        guard let key = try? await key(file) else { return nil }
        let task = thumbnails[key] ?? Task<UIImage?, Never> {
            if !file.isImage {
                guard file.kind.hasThumbnail else { return nil }
                if let bytes = await self.size(of: file), bytes > Self.thumbnailLimit { return nil }
            }
            guard let local = try? await self.localFile(file), self.canAccess else { return nil }
            if file.isImage, let image = UIImage(contentsOfFile: local.path()) { return image }
            let request = QLThumbnailGenerator.Request(fileAt: local, size: size, scale: scale, representationTypes: .thumbnail)
            return try? await QLThumbnailGenerator.shared.generateBestRepresentation(for: request).uiImage
        }
        thumbnails[key] = task
        let value = await task.value
        return canAccess ? value : nil
    }

    nonisolated static func safeName(_ name: String) -> String {
        let cleaned = name.replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: ":", with: "_")
        return cleaned.isEmpty || cleaned == "." || cleaned == ".." ? "download" : cleaned
    }
}

/// Opens a file a Bot sent or linked to: downloads it once (through the object store on Octop Bot
/// cloud), then Quick Look, whose share button also saves to Files or Photos.
enum FileOpener {
    static func open(_ url: URL, from server: ServerBackend) async {
        guard let file = FileAttachment.fromLink(url) else { return }
        await open(file, from: server)
    }

    static func open(_ file: FileAttachment, from server: ServerBackend) async {
        guard let local = await fetch(file, from: server) else { return }
        let preview = QLPreviewController()
        let source = PreviewSource(url: local)
        preview.dataSource = source
        objc_setAssociatedObject(preview, &PreviewSource.key, source, .OBJC_ASSOCIATION_RETAIN_NONATOMIC)
        server.attachments.present(preview)
    }

    static func share(_ file: FileAttachment, from server: ServerBackend) async {
        guard let local = await fetch(file, from: server) else { return }
        let sheet = UIActivityViewController(activityItems: [local], applicationActivities: nil)
        server.attachments.present(sheet)
    }

    static func saveToFiles(_ file: FileAttachment, from server: ServerBackend) async {
        guard let local = await fetch(file, from: server) else { return }
        server.attachments.present(UIDocumentPickerViewController(forExporting: [local], asCopy: true))
    }

    private static func fetch(_ file: FileAttachment, from server: ServerBackend) async -> URL? {
        do {
            return try await server.attachments.localFile(file)
        } catch {
            guard server.attachments.canAccess, !Task.isCancelled else { return nil }
            Haptics.error()
            let alert = UIAlertController(title: L("file.openFailed"), message: error.localizedDescription, preferredStyle: .alert)
            alert.addAction(UIAlertAction(title: L("common.done"), style: .default))
            server.attachments.present(alert)
            return nil
        }
    }

    /// Presents on top of whatever is showing, sheets included.
    static func present(_ controller: UIViewController) {
        let scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first { $0.activationState == .foregroundActive }
        guard var top = scene?.keyWindow?.rootViewController else { return }
        while let next = top.presentedViewController { top = next }
        controller.popoverPresentationController?.sourceView = top.view
        controller.popoverPresentationController?.sourceRect = CGRect(x: top.view.bounds.midX, y: top.view.bounds.midY, width: 0, height: 0)
        top.present(controller, animated: true)
    }
}

nonisolated private final class PreviewSource: NSObject, QLPreviewControllerDataSource {
    nonisolated(unsafe) static var key: UInt8 = 0
    let url: URL
    init(url: URL) { self.url = url }

    nonisolated func numberOfPreviewItems(in controller: QLPreviewController) -> Int { 1 }

    nonisolated func previewController(_ controller: QLPreviewController, previewItemAt index: Int) -> any QLPreviewItem {
        url as NSURL
    }
}
