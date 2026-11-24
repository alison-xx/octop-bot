import Foundation
import SwiftUI

/// A file a Bot sent or linked to on its server (server mode only).
struct FileAttachment: Hashable, Identifiable {
    /// Server-relative: `/api/agents/{id}/workspace/download?path=…` or `…/media/preview?source=…`.
    var url: String
    var name: String
    var mime: String? = nil
    var size: Int64? = nil

    var id: String { url }
    var kind: FileKind { FileKind.of(name: name, mime: mime) }
    var isImage: Bool { kind == .image }
    /// The workspace download (the only kind the server can size with `HEAD`).
    var isWorkspaceDownload: Bool { URL(string: url).map(ServerBackend.isWorkspaceDownload) ?? false }

    /// `/api/agents/{agent}/workspace/download?path=…` for a workspace path.
    static func download(agent: String, path: String) -> String {
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "&=+?#")
        let value = path.addingPercentEncoding(withAllowedCharacters: allowed) ?? path
        let id = agent.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed.subtracting(CharacterSet(charactersIn: "/"))) ?? agent
        return "/api/agents/\(id)/workspace/download?path=\(value)"
    }

    /// Last component of a path, either separator.
    static func basename(_ path: String) -> String {
        path.split(whereSeparator: { $0 == "/" || $0 == "\\" }).last.map(String.init) ?? path
    }

    /// The file a workspace download link points at, or nil for any other link.
    static func fromLink(_ link: URL) -> FileAttachment? {
        guard ServerBackend.isWorkspaceDownload(link) else { return nil }
        let path = URLComponents(url: link, resolvingAgainstBaseURL: false)?
            .queryItems?.first { $0.name == "path" }?.value ?? ""
        let name = basename(path)
        return FileAttachment(url: link.absoluteString, name: name.isEmpty ? L("file.untitled") : name)
    }

    /// Workspace download links in a reply's Markdown, in order, without repeats.
    static func links(in text: String) -> [FileAttachment] {
        guard text.contains("/workspace/download") else { return [] }
        var out: [FileAttachment] = []
        let pattern = /\((\/api\/agents\/[^\s)]+)\)|<(\/api\/agents\/[^\s>]+)>/
        for match in text.matches(of: pattern) {
            guard let raw = match.output.1 ?? match.output.2, let link = URL(string: String(raw)),
                  let file = fromLink(link), !out.contains(where: { $0.url == file.url }) else { continue }
            out.append(file)
        }
        return out
    }

    /// A live `attachment` frame: `{kind, url, filename?, path?, mime_type?}`.
    static func fromFrame(_ frame: [String: Any]) -> FileAttachment? {
        guard let url = frame["url"] as? String, url.hasPrefix("/api/") else { return nil }
        let path = frame["path"] as? String
        var name = (frame["filename"] as? String).flatMap { $0.isEmpty ? nil : $0 }
            ?? path.map(basename)
            ?? URL(string: url).flatMap(fromLink)?.name
            ?? L("file.untitled")
        if name.isEmpty { name = L("file.untitled") }
        var mime = (frame["mime_type"] as? String).flatMap { $0.isEmpty ? nil : $0 }
        if mime == nil, frame["kind"] as? String == "image" { mime = "image/*" }
        return FileAttachment(url: url, name: name, mime: mime)
    }

    /// Files a `send_file` / `send_file_to_user` result delivered (history `tool_result` output).
    static func fromToolOutput(_ output: Any?, agent: String) -> [FileAttachment] {
        var value = output
        if let text = output as? String {
            let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard let first = trimmed.first, first == "{" || first == "[" else { return [] }
            value = try? JSONSerialization.jsonObject(with: Data(trimmed.utf8))
        }
        let blocks = ((value as? [[String: Any]]) ?? (value as? [String: Any]).map { [$0] } ?? [])
            .flatMap(generatedFiles)
        return blocks.compactMap { block in
            let type = block["type"] as? String
            let path = (block["path"] as? String).flatMap { $0.isEmpty ? nil : $0 }
            let source = block["source"] as? [String: Any]
            let mime = (block["media_type"] as? String) ?? (block["mime_type"] as? String) ?? (source?["media_type"] as? String)
            let name = (block["filename"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? path.map(basename)
            switch type {
            case "file":
                guard let path else { return nil }
                return FileAttachment(url: download(agent: agent, path: path), name: name ?? basename(path), mime: mime)
            case "image":
                let preview = [block["preview_url"] as? String, source?["url"] as? String]
                    .compactMap { $0 }.first { $0.hasPrefix("/api/") }
                guard let url = preview ?? path.map({ download(agent: agent, path: $0) }) else { return nil }
                return FileAttachment(url: url, name: name ?? L("file.untitled"), mime: mime ?? "image/*")
            default:
                return nil
            }
        }
    }

    /// A `generate_image` / `generate_video` result lists its files under `images` / `videos`;
    /// other blocks pass through.
    private static func generatedFiles(_ block: [String: Any]) -> [[String: Any]] {
        let field: String
        switch block["type"] as? String {
        case "image_gen_tool_result": field = "images"
        case "video_gen_tool_result": field = "videos"
        default: return [block]
        }
        return (block[field] as? [[String: Any]] ?? []).compactMap { row in
            guard let path = row["path"] as? String, !path.isEmpty else { return nil }
            var file: [String: Any] = ["type": "file", "path": path]
            file["media_type"] = row["mediaType"] as? String
            return file
        }
    }

    /// Tools whose results are files for the user.
    static func isDeliveryTool(_ name: String?) -> Bool {
        guard let name else { return false }
        let base = name.split(separator: "/").last.map(String.init) ?? name
        return ["send_file", "send_file_to_user", "generate_image", "generate_video"].contains(base)
    }
}

extension ChatMessage {
    /// Cards under an assistant reply: delivered files, then files the text links to.
    var fileCards: [FileAttachment] {
        guard role == .assistant else { return [] }
        var out = attachments
        for link in FileAttachment.links(in: text) where !out.contains(where: { $0.url == link.url }) {
            out.append(link)
        }
        return out
    }
}

/// What a file card's icon says about the file.
enum FileKind: String, CaseIterable {
    case pdf, word, spreadsheet, presentation, archive, image, other

    static func of(name: String, mime: String?) -> FileKind {
        let ext = FileCardText.fileExtension(name)
        switch ext {
        case "pdf": return .pdf
        case "doc", "docx", "odt", "rtf", "pages": return .word
        case "xls", "xlsx", "csv", "tsv", "ods", "numbers": return .spreadsheet
        case "ppt", "pptx", "odp", "key": return .presentation
        case "zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz": return .archive
        case "png", "jpg", "jpeg", "gif", "webp", "heic", "heif", "bmp", "svg": return .image
        default: break
        }
        let type = (mime ?? "").lowercased()
        if type == "application/pdf" { return .pdf }
        if type.hasPrefix("image/") { return .image }
        if type.contains("wordprocessing") || type == "application/msword" { return .word }
        if type.contains("spreadsheet") || type.contains("excel") || type == "text/csv" { return .spreadsheet }
        if type.contains("presentation") || type.contains("powerpoint") { return .presentation }
        if type.contains("zip") || type.contains("compressed") || type.contains("x-tar") { return .archive }
        return .other
    }

    /// The color of the band at the bottom of the document glyph.
    var bandHex: UInt32 {
        switch self {
        case .pdf: 0xE5484D
        case .word: 0x2F6FEB
        case .spreadsheet: 0x1F9D55
        case .presentation: 0xF2711C
        case .archive: 0x8E4EC6
        case .image, .other: 0x8B8D98
        }
    }

    var band: Color {
        Color(red: Double((bandHex >> 16) & 0xFF) / 255, green: Double((bandHex >> 8) & 0xFF) / 255, blue: Double(bandHex & 0xFF) / 255)
    }

    /// Quick Look can draw a first-page thumbnail worth downloading the file for.
    var hasThumbnail: Bool { self != .archive }
}

/// Text on a file card.
enum FileCardText {
    /// Lowercased extension, or "" (no dot, dotfile, or longer than 8 characters).
    static func fileExtension(_ name: String) -> String {
        guard let dot = name.lastIndex(of: "."), dot != name.startIndex else { return "" }
        let ext = name[name.index(after: dot)...]
        guard !ext.isEmpty, ext.count <= 8, !ext.contains(" ") else { return "" }
        return ext.lowercased()
    }

    /// "PDF", "DOCX", or the localized "File" when there is no short extension.
    static func typeLabel(_ name: String) -> String {
        let ext = fileExtension(name)
        return ext.isEmpty || ext.count > 4 ? L("file.generic") : ext.uppercased()
    }

    /// `Quarterly-report-2026-final.pdf` → `Quarterly-repo…inal.pdf`: the extension always stays.
    static func middleEllipsis(_ name: String, max: Int = 26) -> String {
        guard name.count > max else { return name }
        let ext = fileExtension(name)
        let suffix = ext.isEmpty ? "" : "." + String(name.suffix(ext.count))
        let stem = Array(name.dropLast(suffix.count))
        let budget = Swift.max(max - suffix.count - 1, 2)
        let tail = Swift.min(4, budget / 3)
        let head = budget - tail
        guard stem.count > budget else { return name }
        return String(stem.prefix(head)) + "…" + String(stem.suffix(tail)) + suffix
    }

    /// 1024-based: `512 B`, `1.5 KB`, `2 MB`, `12 MB`.
    static func formatFileSize(_ bytes: Int64) -> String {
        if bytes < 1024 { return "\(Swift.max(bytes, 0)) B" }
        var value = Double(bytes)
        var unit = "B"
        for next in ["KB", "MB", "GB", "TB"] {
            guard value >= 1024 else { break }
            value /= 1024
            unit = next
        }
        var text = value < 10 ? String(format: "%.1f", value) : String(format: "%.0f", value)
        if text.hasSuffix(".0") { text.removeLast(2) }
        return "\(text) \(unit)"
    }
}
