package io.github.alisonxx.octopbot.net

import org.junit.Assert.assertEquals
import org.junit.Test

class GitHubStarsTest {
    @Test
    fun starCountsReadLikeTheWebsite() {
        assertEquals("6", GitHubStars.format(6))
        assertEquals("999", GitHubStars.format(999))
        assertEquals("1k", GitHubStars.format(1000))
        assertEquals("1.23k", GitHubStars.format(1234))
        assertEquals("12.4k", GitHubStars.format(12_400))
        assertEquals("12k", GitHubStars.format(12_000))
    }
}
