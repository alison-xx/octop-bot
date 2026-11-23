import CryptoKit
import QuickLook
import QuickLookThumbnailing
import UIKit

extension ServerBackend {
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

/// Sizes, downloaded copies and thumbnails of the files Bots send, fetched once per link.
@MainActor
final class AttachmentStore {
    static let shared = AttachmentStore()

    /// Thumbnails are only drawn for files up to this size.
    static let thumbnailLimit: Int64 = 20 * 1024 * 1024

    private var sizes: [String: Task<Int64?, Never>] = [:]
    private var files: [String: Task<URL, Error>] = [:]
    private var thumbnails: [String: Task<UIImage?, Never>] = [:]

    private func key(_ file: FileAttachment, _ server: ServerBackend) -> String { server.session.baseURL.absoluteString + file.url }

    func size(of file: FileAttachment, on server: ServerBackend) async -> Int64? {
        if let size = file.size { return size }
        guard file.isWorkspaceDownload, let url = URL(string: file.url) else { return nil }
        let key = key(file, server)
        if let task = sizes[key] { return await task.value }
        let task = Task { await server.fileSize(for: url) }
        sizes[key] = task
        return await task.value
    }

    /// A local copy under Caches, named like the file so Quick Look and the share sheet show its name.
    func localFile(_ file: FileAttachment, on server: ServerBackend) async throws -> URL {
        let key = key(file, server)
        if let task = files[key] {
            if let url = try? await task.value, FileManager.default.fileExists(atPath: url.path()) { return url }
            files[key] = nil
        }
        let folder = Self.folder(for: key)
        let target = folder.appending(path: Self.safeName(file.name))
        let task = Task<URL, Error> {
            if FileManager.default.fileExists(atPath: target.path()) { return target }
            guard let url = URL(string: file.url) else { throw APIError.network }
            let data = try await server.fileData(for: url)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            try data.write(to: target, options: .atomic)
            return target
        }
        files[key] = task
        do {
            return try await task.value
        } catch {
            files[key] = nil
            throw error
        }
    }

    /// The first page (or the picture itself) drawn by Quick Look.
    func thumbnail(_ file: FileAttachment, on server: ServerBackend, size: CGSize, scale: CGFloat) async -> UIImage? {
        let key = key(file, server)
        if let task = thumbnails[key] { return await task.value }
        let task = Task<UIImage?, Never> {
            if !file.isImage {
                guard file.kind.hasThumbnail else { return nil }
                if let bytes = await self.size(of: file, on: server), bytes > Self.thumbnailLimit { return nil }
            }
            guard let local = try? await self.localFile(file, on: server) else { return nil }
            if file.isImage, let image = UIImage(contentsOfFile: local.path()) { return image }
            let request = QLThumbnailGenerator.Request(fileAt: local, size: size, scale: scale, representationTypes: .thumbnail)
            return try? await QLThumbnailGenerator.shared.generateBestRepresentation(for: request).uiImage
        }
        thumbnails[key] = task
        return await task.value
    }

    private static func folder(for key: String) -> URL {
        let digest = SHA256.hash(data: Data(key.utf8)).prefix(12).map { String(format: "%02x", $0) }.joined()
        return FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appending(path: "attachments", directoryHint: .isDirectory)
            .appending(path: digest, directoryHint: .isDirectory)
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
        present(preview)
    }

    static func share(_ file: FileAttachment, from server: ServerBackend) async {
        guard let local = await fetch(file, from: server) else { return }
        let sheet = UIActivityViewController(activityItems: [local], applicationActivities: nil)
        present(sheet)
    }

    static func saveToFiles(_ file: FileAttachment, from server: ServerBackend) async {
        guard let local = await fetch(file, from: server) else { return }
        present(UIDocumentPickerViewController(forExporting: [local], asCopy: true))
    }

    private static func fetch(_ file: FileAttachment, from server: ServerBackend) async -> URL? {
        do {
            return try await AttachmentStore.shared.localFile(file, on: server)
        } catch {
            Haptics.error()
            let alert = UIAlertController(title: L("file.openFailed"), message: error.localizedDescription, preferredStyle: .alert)
            alert.addAction(UIAlertAction(title: L("common.done"), style: .default))
            present(alert)
            return nil
        }
    }

    private static func present(_ controller: UIViewController) {
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
