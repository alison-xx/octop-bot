package io.github.alisonxx.octopbot.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class MentionsTest {
    private val members = listOf(
        Mentions.Member("a1", "Chief"),
        Mentions.Member("b2", "Research Lead"),
        Mentions.Member("c3", "Research"),
        Mentions.Member("d4", "Twin"),
        Mentions.Member("e5", "Twin"),
    )

    @Test
    fun resolvesNamesAndIdsLongestFirst() {
        assertEquals(listOf("b2"), Mentions.resolve("@Research Lead please check", members))
        assertEquals(listOf("c3", "a1"), Mentions.resolve("@Research and @Chief", members))
        assertEquals(listOf("a1"), Mentions.resolve("@a1 @Chief", members))
    }

    @Test
    fun ignoresEmailsAmbiguousNamesAndPartialWords() {
        assertEquals(emptyList<String>(), Mentions.resolve("mail me@Chief.com", members))
        assertEquals(emptyList<String>(), Mentions.resolve("@Twin hi", members))
        assertEquals(listOf("d4"), Mentions.resolve("@d4 hi", members))
        assertEquals(emptyList<String>(), Mentions.resolve("@Chiefs", members))
        assertEquals(emptyList<String>(), Mentions.resolve("hi", emptyList()))
    }

    @Test
    fun activeQueryAtTheEnd() {
        assertEquals("Re", Mentions.activeQuery("hello @Re"))
        assertEquals("", Mentions.activeQuery("@"))
        assertNull(Mentions.activeQuery("mail@x"))
        assertNull(Mentions.activeQuery("no mention"))
        assertNull(Mentions.activeQuery("@Chief\nnext"))
    }
}
