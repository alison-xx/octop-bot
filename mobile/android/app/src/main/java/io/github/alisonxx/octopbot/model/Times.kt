package io.github.alisonxx.octopbot.model

import java.time.Instant
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneOffset

object Times {
    /** ISO-8601 with or without zone; Octop stores some timestamps without a zone, and those are UTC. */
    fun parseIso(text: String?): Long? {
        if (text.isNullOrBlank()) return null
        runCatching { return OffsetDateTime.parse(text).toInstant().toEpochMilli() }
        runCatching { return LocalDateTime.parse(text.replace(' ', 'T')).toInstant(ZoneOffset.UTC).toEpochMilli() }
        return null
    }

    fun iso(millis: Long): String = Instant.ofEpochMilli(millis).toString()

    /** Server epoch values come as seconds or milliseconds. */
    fun epochMillis(value: Double): Long = if (value > 1e12) value.toLong() else (value * 1000).toLong()
}
