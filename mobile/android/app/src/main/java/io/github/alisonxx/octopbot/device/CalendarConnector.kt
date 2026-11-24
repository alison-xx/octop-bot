package io.github.alisonxx.octopbot.device

import android.Manifest
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.content.pm.PackageManager
import android.provider.CalendarContract
import androidx.core.content.ContextCompat
import io.github.alisonxx.octopbot.net.bool
import io.github.alisonxx.octopbot.net.long
import io.github.alisonxx.octopbot.net.str
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.addJsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.ZonedDateTime

/** The system calendar (CalendarContract): list events, add one to the primary writable calendar, change one. */
class CalendarConnector(private val context: Context) {
    val permissions = arrayOf(Manifest.permission.READ_CALENDAR, Manifest.permission.WRITE_CALENDAR)

    fun permitted(): Boolean = permissions.all { ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED }

    private val resolver get() = context.contentResolver

    /** `device_calendar_events {start, end}`: instances (recurring events expanded), at most 62 days. */
    fun events(args: JsonObject, zone: ZoneId): JsonObject {
        val start = DeviceTimes.parse(args.str("start"), zone)?.let { DeviceTimes.start(it, zone) }
            ?: return DeviceCatalog.error("start must be an ISO 8601 date or date-time.")
        val end = DeviceTimes.parse(args.str("end"), zone)?.let { DeviceTimes.end(it, zone) }
            ?: return DeviceCatalog.error("end must be an ISO 8601 date or date-time.")
        if (!end.isAfter(start)) return DeviceCatalog.error("end must be after start.")
        if (Duration.between(start, end) > Duration.ofDays(62)) return DeviceCatalog.error("start and end may be at most 62 days apart.")
        val uri = CalendarContract.Instances.CONTENT_URI.buildUpon().also {
            ContentUris.appendId(it, start.toInstant().toEpochMilli())
            ContentUris.appendId(it, end.toInstant().toEpochMilli())
        }.build()
        val projection = arrayOf(
            CalendarContract.Instances.EVENT_ID,
            CalendarContract.Instances.TITLE,
            CalendarContract.Instances.BEGIN,
            CalendarContract.Instances.END,
            CalendarContract.Instances.ALL_DAY,
            CalendarContract.Instances.EVENT_LOCATION,
            CalendarContract.Instances.DESCRIPTION,
            CalendarContract.Instances.CALENDAR_DISPLAY_NAME,
        )
        return buildJsonObject {
            putJsonArray("events") {
                resolver.query(uri, projection, "${CalendarContract.Instances.VISIBLE} = 1", null, "${CalendarContract.Instances.BEGIN} ASC")?.use { c ->
                    var count = 0
                    while (c.moveToNext() && count++ < 500) addJsonObject {
                        putEvent(
                            id = c.getLong(0),
                            title = c.getString(1),
                            begin = c.getLong(2),
                            end = c.getLong(3),
                            allDay = c.getInt(4) == 1,
                            location = c.getString(5),
                            notes = c.getString(6),
                            calendar = c.getString(7),
                            zone = zone,
                        )
                    }
                }
            }
        }
    }

    /** `device_calendar_create_event`: into the primary writable calendar, with an alert when asked. */
    fun create(args: JsonObject, zone: ZoneId): JsonObject {
        val title = args.str("title")?.trim()?.takeIf { it.isNotEmpty() } ?: return DeviceCatalog.error("title is required.")
        val start = DeviceTimes.parse(args.str("start"), zone) ?: return DeviceCatalog.error("start must be an ISO 8601 date or date-time.")
        val end = DeviceTimes.parse(args.str("end"), zone) ?: return DeviceCatalog.error("end must be an ISO 8601 date or date-time.")
        val allDay = args.bool("all_day") ?: (start is DeviceTime.Day)
        val (begin, finish) = span(start, end, allDay, zone) ?: return DeviceCatalog.error("end must be after start.")
        val calendar = writableCalendar() ?: return DeviceCatalog.error("There is no writable calendar on this phone.")
        val values = ContentValues().apply {
            put(CalendarContract.Events.CALENDAR_ID, calendar.first)
            put(CalendarContract.Events.TITLE, title)
            put(CalendarContract.Events.DTSTART, begin)
            put(CalendarContract.Events.DTEND, finish)
            put(CalendarContract.Events.ALL_DAY, if (allDay) 1 else 0)
            put(CalendarContract.Events.EVENT_TIMEZONE, if (allDay) "UTC" else zone.id)
            args.str("location")?.let { put(CalendarContract.Events.EVENT_LOCATION, it) }
            args.str("notes")?.let { put(CalendarContract.Events.DESCRIPTION, it) }
        }
        val id = resolver.insert(CalendarContract.Events.CONTENT_URI, values)?.let(ContentUris::parseId)
            ?: return DeviceCatalog.error("The calendar did not accept the event.")
        args.long("alarm_minutes")?.takeIf { it in 0..10080 }?.let { minutes ->
            resolver.insert(
                CalendarContract.Reminders.CONTENT_URI,
                ContentValues().apply {
                    put(CalendarContract.Reminders.EVENT_ID, id)
                    put(CalendarContract.Reminders.MINUTES, minutes)
                    put(CalendarContract.Reminders.METHOD, CalendarContract.Reminders.METHOD_ALERT)
                },
            )
        }
        return buildJsonObject {
            put("id", id.toString())
            put("title", title)
            put("start", stamp(begin, allDay, zone, isEnd = false))
            put("end", stamp(finish, allDay, zone, isEnd = true))
            put("calendar", calendar.second)
        }
    }

    /** `device_calendar_update_event`: only the given fields change. Moving only the start keeps the length. */
    fun update(args: JsonObject, zone: ZoneId): JsonObject {
        val id = args.str("event_id")?.trim()?.toLongOrNull() ?: return DeviceCatalog.error("event_id is not an event from device_calendar_events.")
        val current = event(id) ?: return DeviceCatalog.error("No event with id $id.")
        if (current.recurring) return DeviceCatalog.error("Repeating events can't be changed from the chat; ask the user to edit it in the calendar app.")
        val values = ContentValues()
        args.str("title")?.trim()?.takeIf { it.isNotEmpty() }?.let { values.put(CalendarContract.Events.TITLE, it) }
        args.str("location")?.let { values.put(CalendarContract.Events.EVENT_LOCATION, it) }
        args.str("notes")?.let { values.put(CalendarContract.Events.DESCRIPTION, it) }
        val newStart = args.str("start")?.let {
            DeviceTimes.parse(it, zone) ?: return DeviceCatalog.error("start must be an ISO 8601 date-time.")
        }
        val newEnd = args.str("end")?.let {
            DeviceTimes.parse(it, zone) ?: return DeviceCatalog.error("end must be an ISO 8601 date-time.")
        }
        if (newStart != null || newEnd != null) {
            val begin = newStart?.let { instant(it, current.allDay, zone, isEnd = false) } ?: current.begin
            val finish = newEnd?.let { instant(it, current.allDay, zone, isEnd = true) }
                ?: if (newStart != null) begin + (current.end - current.begin) else current.end
            if (finish <= begin) return DeviceCatalog.error("end must be after start.")
            values.put(CalendarContract.Events.DTSTART, begin)
            values.put(CalendarContract.Events.DTEND, finish)
        }
        if (values.size() > 0) {
            val changed = resolver.update(ContentUris.withAppendedId(CalendarContract.Events.CONTENT_URI, id), values, null, null)
            if (changed < 1) return DeviceCatalog.error("The calendar did not accept the change.")
        }
        val updated = event(id) ?: return DeviceCatalog.error("No event with id $id.")
        return buildJsonObject {
            putEvent(id, updated.title, updated.begin, updated.end, updated.allDay, updated.location, updated.notes, updated.calendar, zone)
        }
    }

    private class Event(
        val title: String?,
        val begin: Long,
        val end: Long,
        val allDay: Boolean,
        val location: String?,
        val notes: String?,
        val calendar: String?,
        val recurring: Boolean,
    )

    private fun event(id: Long): Event? {
        val projection = arrayOf(
            CalendarContract.Events.TITLE,
            CalendarContract.Events.DTSTART,
            CalendarContract.Events.DTEND,
            CalendarContract.Events.ALL_DAY,
            CalendarContract.Events.EVENT_LOCATION,
            CalendarContract.Events.DESCRIPTION,
            CalendarContract.Events.CALENDAR_DISPLAY_NAME,
            CalendarContract.Events.RRULE,
            CalendarContract.Events.DELETED,
        )
        return resolver.query(ContentUris.withAppendedId(CalendarContract.Events.CONTENT_URI, id), projection, null, null, null)?.use { c ->
            if (!c.moveToFirst() || c.getInt(8) == 1) return@use null
            val begin = c.getLong(1)
            Event(
                title = c.getString(0),
                begin = begin,
                end = if (c.isNull(2)) begin else c.getLong(2),
                allDay = c.getInt(3) == 1,
                location = c.getString(4),
                notes = c.getString(5),
                calendar = c.getString(6),
                recurring = !c.getString(7).isNullOrBlank(),
            )
        }
    }

    /** The primary calendar the user can write to (id, name). */
    private fun writableCalendar(): Pair<Long, String>? {
        val projection = arrayOf(
            CalendarContract.Calendars._ID,
            CalendarContract.Calendars.CALENDAR_DISPLAY_NAME,
        )
        val selection = "${CalendarContract.Calendars.CALENDAR_ACCESS_LEVEL} >= ${CalendarContract.Calendars.CAL_ACCESS_CONTRIBUTOR}" +
            " AND ${CalendarContract.Calendars.VISIBLE} = 1"
        val order = "${CalendarContract.Calendars.IS_PRIMARY} DESC, ${CalendarContract.Calendars._ID} ASC"
        return resolver.query(CalendarContract.Calendars.CONTENT_URI, projection, selection, null, order)?.use { c ->
            if (c.moveToFirst()) c.getLong(0) to (c.getString(1) ?: "") else null
        }
    }

    /** Event bounds in epoch ms. All-day events run from UTC midnight of the first day to UTC midnight after the last. */
    private fun span(start: DeviceTime, end: DeviceTime, allDay: Boolean, zone: ZoneId): Pair<Long, Long>? {
        val begin = instant(start, allDay, zone, isEnd = false)
        val finish = instant(end, allDay, zone, isEnd = true)
        return if (finish > begin) begin to finish else null
    }

    private fun instant(time: DeviceTime, allDay: Boolean, zone: ZoneId, isEnd: Boolean): Long {
        if (!allDay) {
            // A bare date as an end means the whole day.
            val at = if (isEnd) DeviceTimes.end(time, zone) else DeviceTimes.start(time, zone)
            return at.toInstant().toEpochMilli()
        }
        val day = when (time) {
            is DeviceTime.Day -> time.date
            is DeviceTime.Moment -> time.time.toLocalDate()
        }
        return (if (isEnd) day.plusDays(1) else day).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()
    }

    /** All-day bounds come back as dates (the end as the last day); other times in the phone's zone. */
    private fun stamp(millis: Long, allDay: Boolean, zone: ZoneId, isEnd: Boolean): String {
        if (!allDay) return DeviceTimes.format(ZonedDateTime.ofInstant(Instant.ofEpochMilli(millis), zone))
        val day = Instant.ofEpochMilli(millis).atZone(ZoneOffset.UTC).toLocalDate()
        return DeviceTimes.format(if (isEnd) day.minusDays(1) else day)
    }

    private fun kotlinx.serialization.json.JsonObjectBuilder.putEvent(
        id: Long,
        title: String?,
        begin: Long,
        end: Long,
        allDay: Boolean,
        location: String?,
        notes: String?,
        calendar: String?,
        zone: ZoneId,
    ) {
        put("id", id.toString())
        put("title", title.orEmpty())
        put("start", stamp(begin, allDay, zone, isEnd = false))
        put("end", stamp(maxOf(end, begin + if (allDay) DAY else 0), allDay, zone, isEnd = true))
        put("all_day", allDay)
        put("location", location.orEmpty())
        put("notes", notes.orEmpty().take(2000))
        put("calendar", calendar.orEmpty())
    }

    private companion object {
        const val DAY = 86_400_000L
    }
}
