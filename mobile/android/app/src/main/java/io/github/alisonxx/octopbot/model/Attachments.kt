package io.github.alisonxx.octopbot.model

import java.net.URLDecoder
import java.util.Locale

/** A file a Bot sent or linked to. [url] is server-relative (`/api/agents/{id}/workspace/download?path=…`). */
data class FileAttachment(
    val url: String,
    val name: String,
    val mime: String? = null,
    val size: Long? = null,
) {
    val isImage: Boolean get() = FileCards.preview(name, mime) == FilePreview.Image
}

/** The colored band of a file card's document glyph. */
enum class FileKind(val argb: Long) {
    Pdf(0xFFE5484D),
    Word(0xFF2F6FEB),
    Excel(0xFF1F9D55),
    PowerPoint(0xFFF2711C),
    Archive(0xFF8E4EC6),
    Other(0xFF8B8D98),
}

/** What a card can show above the name: the image itself, a PDF's first page, or a text excerpt. */
enum class FilePreview { Image, Pdf, Text, None }

/** Pure helpers for file cards (no Android), shared by the UI and unit tests. */
object FileCards {
    private val word = setOf("doc", "docx", "odt", "rtf", "pages")
    private val excel = setOf("xls", "xlsx", "csv", "tsv", "ods", "numbers")
    private val powerPoint = setOf("ppt", "pptx", "odp", "key")
    private val archive = setOf("zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz")
    private val image = setOf("png", "jpg", "jpeg", "gif", "webp", "bmp", "heic", "heif")
    private val text = setOf("csv", "tsv", "txt", "md", "markdown", "log", "json")

    /** Lowercased extension without the dot, or null ("README", ".env", "a."). */
    fun extension(name: String): String? {
        val dot = name.lastIndexOf('.')
        if (dot <= 0 || dot == name.length - 1) return null
        val ext = name.substring(dot + 1)
        return ext.lowercase(Locale.ROOT).takeIf { it.length <= 10 && it.none(Char::isWhitespace) }
    }

    fun kind(name: String, mime: String? = null): FileKind {
        when (extension(name)) {
            "pdf" -> return FileKind.Pdf
            in word -> return FileKind.Word
            in excel -> return FileKind.Excel
            in powerPoint -> return FileKind.PowerPoint
            in archive -> return FileKind.Archive
        }
        val type = mime?.lowercase(Locale.ROOT).orEmpty()
        return when {
            type == "application/pdf" -> FileKind.Pdf
            "wordprocessing" in type || type == "application/msword" -> FileKind.Word
            "spreadsheet" in type || "excel" in type || type == "text/csv" -> FileKind.Excel
            "presentation" in type || "powerpoint" in type -> FileKind.PowerPoint
            "zip" in type || "compressed" in type || "x-tar" in type || "x-7z" in type || "x-rar" in type -> FileKind.Archive
            else -> FileKind.Other
        }
    }

    /** The band label: the extension in capitals (at most 4 letters), or null for "File". */
    fun typeLabel(name: String): String? = extension(name)?.takeIf { it.length <= 4 }?.uppercase(Locale.ROOT)

    fun preview(name: String, mime: String? = null): FilePreview {
        val ext = extension(name)
        val type = mime?.lowercase(Locale.ROOT).orEmpty()
        return when {
            ext in image || (ext == null && type.startsWith("image/") && type != "image/svg+xml") -> FilePreview.Image
            ext == "pdf" || (ext == null && type == "application/pdf") -> FilePreview.Pdf
            ext in text || (ext == null && type.startsWith("text/")) -> FilePreview.Text
            else -> FilePreview.None
        }
    }

    /** "Quarterly-report-final-v2.pdf" → "Quarterly-report-…l-v2.pdf": head, "…", up to 4 last stem characters, extension. */
    fun middleEllipsis(name: String, max: Int = 26): String {
        val points = name.codePoints().toArray()
        if (points.size <= max) return name
        val ext = extension(name)?.let { "." + name.substring(name.lastIndexOf('.') + 1) }.orEmpty()
        val extPoints = ext.codePointCount(0, ext.length)
        val stem = points.copyOfRange(0, points.size - extPoints)
        val budget = max - extPoints - 1
        if (budget < 2) return String(points, 0, max - 1) + "…"
        val tail = minOf(4, budget / 3)
        val head = budget - tail
        return String(stem, 0, head) + "…" + String(stem, stem.size - tail, tail) + ext
    }

    /** 1024-based, one decimal under 10: "512 B", "1.5 KB", "2 MB", "12 MB". */
    fun formatFileSize(bytes: Long): String {
        if (bytes < 1024) return "${bytes.coerceAtLeast(0)} B"
        val units = listOf("KB", "MB", "GB", "TB")
        var value = bytes / 1024.0
        var unit = 0
        while (value >= 1024 && unit < units.lastIndex) {
            value /= 1024
            unit++
        }
        val number = if (value < 10) {
            String.format(Locale.ROOT, "%.1f", value).removeSuffix(".0")
        } else {
            String.format(Locale.ROOT, "%.0f", value)
        }
        // 1023.6 KB rounds to "1024 KB"; say "1 MB" instead.
        if (number == "1024" && unit < units.lastIndex) return "1 ${units[unit + 1]}"
        return "$number ${units[unit]}"
    }

    /** `/api/agents/{id}/workspace/download?path=…` (server-relative), the link Octop puts in a reply. */
    fun isWorkspaceDownload(uri: String): Boolean {
        if (uri.contains("://")) return false
        val parts = uri.substringBefore('?').trim('/').split('/')
        return parts.size == 5 && parts[0] == "api" && parts[1] == "agents" && parts[3] == "workspace" && parts[4] == "download"
    }

    /** The decoded `path` (or `source`) query value of a server URL, or null. */
    fun queryValue(url: String, key: String): String? {
        val query = url.substringAfter('?', "").substringBefore('#')
        if (query.isEmpty()) return null
        for (pair in query.split('&')) {
            val name = pair.substringBefore('=')
            if (name == key) return runCatching { URLDecoder.decode(pair.substringAfter('=', ""), "UTF-8") }.getOrNull()
        }
        return null
    }

    /** The last component of a path ("a/b/report.pdf" → "report.pdf"; also strips `file://` and backslashes). */
    fun baseName(path: String): String =
        path.removePrefix("file://").replace('\\', '/').trimEnd('/').substringAfterLast('/')

    private val markdownLink = Regex("""\[([^\]]*)]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)""")

    /** Workspace-download links in a reply's Markdown, one card each (deduplicated by URL). */
    fun linksIn(markdown: String): List<FileAttachment> {
        if ("/workspace/download" !in markdown) return emptyList()
        val seen = mutableSetOf<String>()
        return markdownLink.findAll(markdown).mapNotNull { match ->
            val url = match.groupValues[2]
            if (!isWorkspaceDownload(url) || !seen.add(url)) return@mapNotNull null
            val name = queryValue(url, "path")?.let(::baseName)?.takeIf { it.isNotEmpty() }
                ?: match.groupValues[1].trim().takeIf { it.isNotEmpty() }
                ?: "file"
            FileAttachment(url, name)
        }.toList()
    }

    /** [first] then the ones from [more] whose URL is new. */
    fun merge(first: List<FileAttachment>, more: List<FileAttachment>): List<FileAttachment> {
        if (more.isEmpty()) return first
        val urls = first.mapTo(mutableSetOf()) { it.url }
        return first + more.filter { urls.add(it.url) }
    }
}
