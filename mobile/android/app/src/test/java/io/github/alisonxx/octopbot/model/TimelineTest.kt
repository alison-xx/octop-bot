package io.github.alisonxx.octopbot.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId
import java.util.Locale

class TimelineTest {
    private val zone = ZoneId.of("Asia/Shanghai")
    private fun at(text: String) = LocalDateTime.parse(text).atZone(zone).toInstant().toEpochMilli()
    private val now = at("2026-11-23T15:00")

    @Test
    fun separatorBeforeFirstMessageAndAfterTenMinuteGaps() {
        val times = listOf(at("2026-11-23T14:00"), at("2026-11-23T14:05"), at("2026-11-23T14:15"), at("2026-11-23T14:25:01"))
        assertEquals(listOf(true, false, false, true), Timeline.separators(times))
        // Exactly ten minutes is not "more than ten minutes".
        assertFalse(Timeline.needsSeparator(at("2026-11-23T14:00"), at("2026-11-23T14:10")))
        // Unknown times (0) get no caption; the next known one starts fresh.
        assertFalse(Timeline.needsSeparator(null, 0))
        assertTrue(Timeline.needsSeparator(0, at("2026-11-23T14:00")))
    }

    @Test
    fun labelsByDay() {
        val en = Locale.ENGLISH
        val zh = Locale.SIMPLIFIED_CHINESE
        fun label(time: String, locale: Locale) =
            Timeline.label(at(time), now, zone, locale) { if (locale == zh) "昨天 $it" else "Yesterday $it" }
        assertEquals("14:05", label("2026-11-23T14:05", en))
        assertEquals("Yesterday 09:30", label("2026-11-22T09:30", en))
        assertEquals("昨天 09:30", label("2026-11-22T09:30", zh))
        assertEquals("Nov 20 14:05", label("2026-11-20T14:05", en))
        assertEquals("11月20日 14:05", label("2026-11-20T14:05", zh))
        assertEquals("Dec 31, 2025 23:59", label("2025-12-31T23:59", en))
        assertEquals("2025年12月31日 23:59", label("2025-12-31T23:59", zh))
    }

    @Test
    fun historyGroupsAndSearch() {
        fun c(id: String, title: String, time: String?) = ConversationSummary(id, title, time?.let(::at), "bot")
        val list = listOf(
            c("a", "Trip plan", "2026-11-23T08:00"),
            c("b", "Code review", "2026-11-22T23:00"),
            c("c", "Trip budget", "2026-11-17T10:00"),
            c("d", "Old notes", "2026-11-10T10:00"),
            c("e", "No time", null),
        )
        val groups = Timeline.group(list, "", now, zone)
        assertEquals(
            listOf(
                Timeline.Section.Today to listOf("a"),
                Timeline.Section.Yesterday to listOf("b"),
                Timeline.Section.Previous7Days to listOf("c"),
                Timeline.Section.Earlier to listOf("d", "e"),
            ),
            groups.map { (section, items) -> section to items.map { it.id } },
        )
        val trips = Timeline.group(list, "  trip ", now, zone)
        assertEquals(listOf(Timeline.Section.Today, Timeline.Section.Previous7Days), trips.map { it.first })
        assertTrue(Timeline.group(list, "nothing like this", now, zone).isEmpty())
    }
}
