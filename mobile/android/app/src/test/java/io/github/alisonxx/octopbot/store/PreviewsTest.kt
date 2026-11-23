package io.github.alisonxx.octopbot.store

import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.Look
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class PreviewsTest {
    private fun bot(id: String, chief: Boolean = false) = BotProfile(id, id, look = Look.fallback, isChief = chief)

    @Test
    fun chiefPinnedThenNewestReplyThenDirectoryOrder() {
        val bots = listOf(bot("chief", chief = true), bot("a"), bot("b"), bot("c"), bot("d"))
        val previews = mapOf(
            "chief" to BotPreview("x", 1),
            "c" to BotPreview("x", 300),
            "a" to BotPreview("x", 200),
        )
        assertEquals(listOf("chief", "c", "a", "b", "d"), Previews.directoryOrder(bots, previews).map { it.id })
        assertEquals(listOf("chief", "a", "b", "c", "d"), Previews.directoryOrder(bots, emptyMap()).map { it.id })
    }

    @Test
    fun replyFinishedOffScreenIsUnreadUntilOpened() {
        var previews = Previews.replyFinished(emptyMap(), "a", "\n  First line  \nsecond", at = 10, onScreen = false)
        assertEquals(BotPreview("First line", 10, unread = true), previews["a"])
        previews = Previews.markRead(previews, "a")
        assertEquals(BotPreview("First line", 10, unread = false), previews["a"])
        // Nothing to clear: the same map comes back (no needless write).
        assertSame(previews, Previews.markRead(previews, "a"))
        assertSame(previews, Previews.markRead(previews, "missing"))
        // A reply finishing while its chat is on screen stays read.
        assertFalse(Previews.replyFinished(previews, "a", "next", at = 20, onScreen = true).getValue("a").unread)
        assertTrue(Previews.replyFinished(previews, "b", "hi", at = 30, onScreen = false).getValue("b").unread)
    }

    @Test
    fun snippetIsTheFirstLineCappedAt200() {
        assertEquals(200, Previews.snippet("x".repeat(500)).length)
        assertEquals("", Previews.snippet("  \n \n"))
        assertEquals("Haiku", Previews.snippet("**Haiku**\n\nWaves fold"))
        assertEquals("Plan for today", Previews.snippet("## Plan for `today`"))
        assertEquals("first step", Previews.snippet("- first step"))
    }
}
