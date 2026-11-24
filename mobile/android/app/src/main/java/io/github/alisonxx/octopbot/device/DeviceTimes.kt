package io.github.alisonxx.octopbot.device

import io.github.alisonxx.octopbot.net.bool
import io.github.alisonxx.octopbot.net.long
import io.github.alisonxx.octopbot.net.str
import kotlinx.serialization.json.JsonObject
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.time.temporal.ChronoUnit
import java.util.Locale

/** A time argument: a whole day, or a moment. */
sealed interface DeviceTime {
    data class Day(val date: LocalDate) : DeviceTime
    data class Moment(val time: ZonedDateTime) : DeviceTime
}

/** ISO 8601 for device tools: no offset means the phone's time zone; a bare date is a whole day. */
object DeviceTimes {
    fun parse(text: String?, zone: ZoneId): DeviceTime? {
        val value = text?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        runCatching { return DeviceTime.Moment(ZonedDateTime.parse(value).withZoneSameInstant(zone)) }
        runCatching { return DeviceTime.Moment(LocalDateTime.parse(value.replace(' ', 'T')).atZone(zone)) }
        runCatching { return DeviceTime.Day(LocalDate.parse(value)) }
        return null
    }

    /** Where [time] begins: the moment, or the day's first instant. */
    fun start(time: DeviceTime, zone: ZoneId): ZonedDateTime = when (time) {
        is DeviceTime.Moment -> time.time
        is DeviceTime.Day -> time.date.atStartOfDay(zone)
    }

    /** Where [time] ends as a range end: the moment, or the start of the next day (the whole day counts). */
    fun end(time: DeviceTime, zone: ZoneId): ZonedDateTime = when (time) {
        is DeviceTime.Moment -> time.time
        is DeviceTime.Day -> time.date.plusDays(1).atStartOfDay(zone)
    }

    /** `2026-11-24T15:00:00+08:00`, whole seconds. */
    fun format(time: ZonedDateTime): String = time.truncatedTo(ChronoUnit.SECONDS).format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)

    fun format(date: LocalDate): String = date.toString()
}

/** The rows the approval card shows for a device write: what, when, where, notes, alert. */
object DevicePreview {
    enum class Field { Title, Time, Location, Notes, Alert }

    fun rows(args: JsonObject?, zone: ZoneId, locale: Locale): List<Pair<Field, String>> {
        args ?: return emptyList()
        val start = DeviceTimes.parse(args.str("start"), zone)
        val end = DeviceTimes.parse(args.str("end"), zone)
        val allDay = args.bool("all_day") ?: (start is DeviceTime.Day)
        val time = listOfNotNull(start, end).map { describe(it, allDay, zone, locale) }.distinct().joinToString(" – ")
        return listOfNotNull(
            args.str("title")?.trim()?.takeIf { it.isNotEmpty() }?.let { Field.Title to it },
            time.takeIf { it.isNotEmpty() }?.let { Field.Time to it },
            args.str("location")?.trim()?.takeIf { it.isNotEmpty() }?.let { Field.Location to it },
            args.str("notes")?.trim()?.takeIf { it.isNotEmpty() }?.let { Field.Notes to it },
            args.long("alarm_minutes")?.let { Field.Alert to it.toString() },
        )
    }

    private fun describe(time: DeviceTime, allDay: Boolean, zone: ZoneId, locale: Locale): String {
        val date = DateTimeFormatter.ofLocalizedDate(FormatStyle.MEDIUM).withLocale(locale)
        return when {
            time is DeviceTime.Day -> time.date.format(date)
            allDay -> (time as DeviceTime.Moment).time.withZoneSameInstant(zone).toLocalDate().format(date)
            else -> (time as DeviceTime.Moment).time.withZoneSameInstant(zone)
                .format(DateTimeFormatter.ofLocalizedDateTime(FormatStyle.MEDIUM, FormatStyle.SHORT).withLocale(locale))
        }
    }
}
