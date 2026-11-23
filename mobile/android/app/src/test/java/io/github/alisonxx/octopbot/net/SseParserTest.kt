package io.github.alisonxx.octopbot.net

import okio.Buffer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SseParserTest {
    @Test
    fun joinsDataLinesAndSplitsOnBlankLines() {
        val parser = SseParser()
        assertNull(parser.feed(": keep-alive"))
        assertNull(parser.feed("event: delta"))
        assertNull(parser.feed("data: {\"a\":1}"))
        assertNull(parser.feed("data:second"))
        assertEquals(SseEvent("delta", "{\"a\":1}\nsecond"), parser.feed(""))
        assertNull(parser.feed(""))
    }

    @Test
    fun handlesCrLfAndUnterminatedTail() {
        val parser = SseParser()
        assertNull(parser.feed("data: one\r"))
        assertEquals(SseEvent(null, "one"), parser.feed("\r"))
        assertNull(parser.feed("data: [DONE]"))
        assertEquals(SseEvent(null, "[DONE]"), parser.finish())
    }

    @Test
    fun readsEventsFromAStreamAndStopsWhenAsked() {
        val source = Buffer().writeUtf8("data: a\n\ndata: b\n\ndata: c\n\n")
        val seen = mutableListOf<String>()
        source.forEachSseEvent {
            seen += it.data
            it.data != "b"
        }
        assertEquals(listOf("a", "b"), seen)
    }
}
