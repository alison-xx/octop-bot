import UIKit

extension ServerBackend {
    /// `/api/agents/{id}/workspace/download?path=…`, the link Octop puts in a reply for a file.
    nonisolated static func isWorkspaceDownload(_ url: URL) -> Bool {
        guard url.host() == nil || url.scheme == nil else { return false }
        let parts = url.path().split(separator: "/")
        return parts.count == 5 && parts[0] == "api" && parts[1] == "agents" && parts[3] == "workspace" && parts[4] == "download"
    }

    /// Octop Bot cloud: a short-lived link to the file in the object store.
    func downloadLink(for url: URL) async throws -> URL {
        let query = Dictionary(
            (URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []).compactMap { item in
                item.value.map { (item.name, $0) }
            },
            uniquingKeysWith: { first, _ in first }
        )
        let body = try await json(.post, url.path() + "-link", query: query) as? [String: Any]
        guard let link = (body?["url"] as? String).flatMap(URL.init(string:)), link.scheme == "https" else {
            throw APIError(kind: .server, status: 502, message: nil)
        }
        return link
    }

    /// Any server: fetch the file with this session.
    func downloadFile(for url: URL) async throws -> URL {
        let query = (URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? [])
            .reduce(into: [String: String]()) { $0[$1.name] = $1.value }
        let data = try await raw(.get, url.path(), query: query, timeout: 300)
        let name = (query["path"] ?? "download").split(separator: "/").last.map(String.init) ?? "download"
        let folder = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let file = folder.appending(path: name.isEmpty ? "download" : name)
        try data.write(to: file)
        return file
    }
}

/// Opens a file a Bot linked to: through the object store on Octop Bot cloud, otherwise by
/// downloading it with this session and offering the share sheet.
enum FileOpener {
    static func open(_ url: URL, from server: ServerBackend) async {
        do {
            if server.isCloud {
                await UIApplication.shared.open(try await server.downloadLink(for: url))
            } else {
                present(try await server.downloadFile(for: url))
            }
        } catch {
            Haptics.error()
        }
    }

    private static func present(_ file: URL) {
        let scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first { $0.activationState == .foregroundActive }
        guard var top = scene?.keyWindow?.rootViewController else { return }
        while let next = top.presentedViewController { top = next }
        let sheet = UIActivityViewController(activityItems: [file], applicationActivities: nil)
        sheet.popoverPresentationController?.sourceView = top.view
        sheet.popoverPresentationController?.sourceRect = CGRect(x: top.view.bounds.midX, y: top.view.bounds.midY, width: 0, height: 0)
        top.present(sheet, animated: true)
    }
}
