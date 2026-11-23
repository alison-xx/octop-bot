package io.github.alisonxx.octopbot.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SpeakerTextTest {
    @Test
    fun markdownBecomesSpeakableText() {
        val text = "# Plan\n- **Buy** milk\n- See [docs](https://x.y)\n```\ncode()\n```\nDone `now`."
        assertEquals("Plan\nBuy milk\nSee docs\n \nDone now.", Speaker.plainText(text))
    }

    @Test
    fun chunksSplitAtSentences() {
        val text = "First sentence. " + "a".repeat(30) + ". Third one here."
        val chunks = Speaker.chunks(text, 40)
        assertTrue(chunks.all { it.length <= 40 })
        assertEquals(text.replace(" ", ""), chunks.joinToString("").replace(" ", ""))
        assertEquals("First sentence.", chunks.first())
    }
}
