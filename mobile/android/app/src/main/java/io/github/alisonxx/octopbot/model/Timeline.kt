package io.github.alisonxx.octopbot.model

import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import java.util.Locale

/** Time captions between messages and the date groups of the history sheet. */
object Timeline {
    /** A caption goes before the first message and before any message this long after the previous one. */
    const val GAP_MILLIS = 10 * 60_000L

    /** [previous] is the timestamp of the message before, or null for the first one. Unknown times (≤ 0) get none. */
    fun needsSeparator(previous: Long?, current: Long): Boolean {
        if (current <= 0) return false
        if (previous == null || previous <= 0) return true
        return current - previous > GAP_MILLIS
    }

    /** For each timestamp (in order), whether a caption goes before it. */
    fun separators(times: List<Long>): List<Boolean> = times.mapIndexed { index, at ->
        needsSeparator(times.getOrNull(index - 1), at)
    }

    /**
     * Today "14:05", yesterday "Yesterday 14:05" ([yesterday] formats the time into the localized phrase),
     * this year "Nov 20 14:05" / "11月20日 14:05", older with the year.
     */
    fun label(at: Long, now: Long, zone: ZoneId, locale: Locale, yesterday: (String) -> String): String {
        val time = Instant.ofEpochMilli(at).atZone(zone)
        val today = Instant.ofEpochMilli(now).atZone(zone).toLocalDate()
        val clock = time.format(DateTimeFormatter.ofPattern("HH:mm", locale))
        val date = time.toLocalDate()
        val chinese = locale.language == "zh"
        return when {
            date == today -> clock
            date == today.minusDays(1) -> yesterday(clock)
            date.year == today.year -> time.format(DateTimeFormatter.ofPattern(if (chinese) "M月d日" else "MMM d", locale)) + " " + clock
            else -> time.format(DateTimeFormatter.ofPattern(if (chinese) "y年M月d日" else "MMM d, y", locale)) + " " + clock
        }
    }

    enum class Section { Today, Yesterday, Previous7Days, Earlier }

    fun section(at: Long?, now: Long, zone: ZoneId): Section {
        if (at == null || at <= 0) return Section.Earlier
        val today = Instant.ofEpochMilli(now).atZone(zone).toLocalDate()
        val date: LocalDate = Instant.ofEpochMilli(at).atZone(zone).toLocalDate()
        val days = ChronoUnit.DAYS.between(date, today)
        return when {
            days <= 0 -> Section.Today
            days == 1L -> Section.Yesterday
            days <= 7 -> Section.Previous7Days
            else -> Section.Earlier
        }
    }

    /** Conversations whose title matches [query], grouped by section in [Section] order; empty sections are left out. */
    fun group(
        conversations: List<ConversationSummary>,
        query: String,
        now: Long,
        zone: ZoneId,
    ): List<Pair<Section, List<ConversationSummary>>> {
        val needle = query.trim()
        val matching = conversations.filter { needle.isEmpty() || it.title.contains(needle, ignoreCase = true) }
        val bySection = matching.groupBy { section(it.updatedAt, now, zone) }
        return Section.entries.mapNotNull { section -> bySection[section]?.let { section to it } }
    }
}
