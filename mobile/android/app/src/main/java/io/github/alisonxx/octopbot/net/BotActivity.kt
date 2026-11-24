package io.github.alisonxx.octopbot.net

import kotlinx.serialization.json.JsonElement

/** A server Bot's profile: upcoming scheduled tasks and the files it made (pure mapping, no I/O). */
object BotActivity {
    /** The card shows this many tasks until "Show more". */
    const val FIRST_SHOWN = 5

    /** One task from `GET /api/octop-bot/bots/{id}/upcoming`; [schedule] is the server's localized line. */
    data class UpcomingJob(
        val id: String,
        val name: String,
        val enabled: Boolean,
        val schedule: String,
        val canToggle: Boolean,
    )

    enum class Period { Today, Week, Older }

    enum class FileKind { Image, Video, Audio, Sheet, Slides, Archive, Document, Other }

    /** One file from `GET /api/octop-bot/bots/{id}/library`; [url] is a `…/workspace/download?path=…` link. */
    data class LibraryFile(
        val name: String,
        val path: String,
        val mime: String?,
        val period: Period,
        val url: String,
    )

    /** In the server's order: enabled tasks soonest first, paused ones last. */
    fun upcoming(body: JsonElement): List<UpcomingJob> =
        body.asObject()?.arr("jobs").orEmpty().mapNotNull { item ->
            val row = item.asObject() ?: return@mapNotNull null
            val id = row.str("id") ?: return@mapNotNull null
            UpcomingJob(
                id = id,
                name = row.str("name") ?: id,
                enabled = row.bool("enabled") == true,
                schedule = row.str("schedule").orEmpty(),
                canToggle = row.bool("can_toggle") == true,
            )
        }

    fun library(body: JsonElement): List<LibraryFile> =
        body.asObject()?.arr("files").orEmpty().mapNotNull { item ->
            val row = item.asObject() ?: return@mapNotNull null
            val path = row.str("path") ?: return@mapNotNull null
            val url = row.str("url") ?: return@mapNotNull null
            LibraryFile(
                name = row.str("name") ?: path.substringAfterLast('/'),
                path = path,
                mime = row.str("mime"),
                period = when (row.str("period")) {
                    "today" -> Period.Today
                    "week" -> Period.Week
                    else -> Period.Older
                },
                url = url,
            )
        }

    /** Today, this week, older — newest first inside each, empty groups left out. */
    fun grouped(files: List<LibraryFile>): List<Pair<Period, List<LibraryFile>>> =
        Period.entries.mapNotNull { period ->
            files.filter { it.period == period }.takeIf { it.isNotEmpty() }?.let { period to it }
        }

    fun kind(file: LibraryFile): FileKind {
        val mime = file.mime.orEmpty()
        return when {
            mime.startsWith("image/") -> FileKind.Image
            mime.startsWith("video/") -> FileKind.Video
            mime.startsWith("audio/") -> FileKind.Audio
            else -> when (file.name.substringAfterLast('.', "").lowercase()) {
                "xls", "xlsx", "csv", "numbers" -> FileKind.Sheet
                "ppt", "pptx", "key" -> FileKind.Slides
                "zip", "gz", "tgz", "tar", "7z", "rar" -> FileKind.Archive
                "pdf", "doc", "docx", "md", "txt", "rtf", "pages" -> FileKind.Document
                else -> if (mime.startsWith("text/")) FileKind.Document else FileKind.Other
            }
        }
    }
}
