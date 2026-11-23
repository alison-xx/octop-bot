package io.github.alisonxx.octopbot.net

import okio.BufferedSource

/** One Server-Sent Event: its `event` name and joined `data` lines. */
data class SseEvent(val event: String?, val data: String)

/** Line-oriented SSE parser, kept free of I/O so it can be unit tested. */
class SseParser {
    private var name: String? = null
    private val data = mutableListOf<String>()

    /** Feed one line without its trailing `\n`; returns an event when a blank line ends one. */
    fun feed(rawLine: String): SseEvent? {
        val line = rawLine.removeSuffix("\r")
        if (line.isEmpty()) return flush()
        if (line.startsWith(":")) return null
        val colon = line.indexOf(':')
        val field = if (colon >= 0) line.substring(0, colon) else line
        val value = if (colon >= 0) line.substring(colon + 1).removePrefix(" ") else ""
        when (field) {
            "event" -> name = value
            "data" -> data += value
        }
        return null
    }

    /** End of stream: emit any event that was not terminated by a blank line. */
    fun finish(): SseEvent? = flush()

    private fun flush(): SseEvent? {
        val event = if (data.isEmpty() && name == null) null else SseEvent(name, data.joinToString("\n"))
        name = null
        data.clear()
        return event
    }
}

/** Read events from a streaming body until it ends or [onEvent] returns false. Blocking; call on Dispatchers.IO. */
inline fun BufferedSource.forEachSseEvent(onEvent: (SseEvent) -> Boolean) {
    val parser = SseParser()
    while (true) {
        val line = readUtf8Line() ?: break
        val event = parser.feed(line) ?: continue
        if (!onEvent(event)) return
    }
    parser.finish()?.let(onEvent)
}
