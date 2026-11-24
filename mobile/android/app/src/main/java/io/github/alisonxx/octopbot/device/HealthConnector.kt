package io.github.alisonxx.octopbot.device

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.aggregate.AggregateMetric
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ActiveCaloriesBurnedRecord
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.RestingHeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.WeightRecord
import androidx.health.connect.client.request.AggregateGroupByPeriodRequest
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import io.github.alisonxx.octopbot.net.arr
import io.github.alisonxx.octopbot.net.asString
import io.github.alisonxx.octopbot.net.long
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.addJsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.putJsonObject
import java.time.Duration
import java.time.LocalDate
import java.time.Period
import java.time.ZoneId
import java.time.ZonedDateTime
import kotlin.math.roundToLong
import kotlin.reflect.KClass

/** Health Connect, read only: daily values for `device_health_summary`, never raw samples. */
class HealthConnector(private val context: Context) {
    /** A metric of `device_health_summary`, its record type and unit. */
    private enum class Metric(val key: String, val record: KClass<out Record>, val unit: String) {
        Steps("steps", StepsRecord::class, "count"),
        ActiveEnergy("active_energy", ActiveCaloriesBurnedRecord::class, "kcal"),
        ExerciseMinutes("exercise_minutes", ExerciseSessionRecord::class, "min"),
        SleepHours("sleep_hours", SleepSessionRecord::class, "h"),
        HeartRate("heart_rate", HeartRateRecord::class, "bpm"),
        RestingHeartRate("resting_heart_rate", RestingHeartRateRecord::class, "bpm"),
        Weight("weight", WeightRecord::class, "kg"),
        ;

        val permission: String get() = HealthPermission.getReadPermission(record)
    }

    /** Every read permission the switch asks for. */
    val permissions: Set<String> = Metric.entries.map { it.permission }.toSet()

    /** `HealthConnectClient.SDK_AVAILABLE`, `SDK_UNAVAILABLE` or `SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED`. */
    fun status(): Int = HealthConnectClient.getSdkStatus(context)

    val available: Boolean get() = status() == HealthConnectClient.SDK_AVAILABLE

    private val client by lazy { HealthConnectClient.getOrCreate(context) }

    suspend fun granted(): Set<String> =
        if (available) runCatching { client.permissionController.getGrantedPermissions() }.getOrDefault(emptySet()) else emptySet()

    /** At least one metric may be read. */
    suspend fun permitted(): Boolean = granted().any { it in permissions }

    suspend fun summary(args: JsonObject, zone: ZoneId): JsonObject {
        if (!available) return DeviceCatalog.error("Health Connect is not available on this phone.")
        val asked = args.arr("metrics")?.mapNotNull { it.asString() }.orEmpty()
            .mapNotNull { key -> Metric.entries.firstOrNull { it.key == key } }.distinct()
        if (asked.isEmpty()) return DeviceCatalog.error("Pass at least one known metric.")
        val granted = granted()
        val metrics = asked.filter { it.permission in granted }
        if (metrics.isEmpty()) return DeviceCatalog.error("The user has not allowed reading these health metrics.")
        val days = (args.long("days") ?: 7L).coerceIn(1L, 30L).toInt()
        val today = LocalDate.now(zone)
        val from = today.minusDays(days - 1L)
        val values = sortedMapOf<LocalDate, MutableMap<String, JsonPrimitive>>()
        for (day in 0 until days) values[from.plusDays(day.toLong())] = mutableMapOf()

        val aggregated = buildMap<Metric, AggregateMetric<*>> {
            if (Metric.Steps in metrics) put(Metric.Steps, StepsRecord.COUNT_TOTAL)
            if (Metric.ActiveEnergy in metrics) put(Metric.ActiveEnergy, ActiveCaloriesBurnedRecord.ACTIVE_CALORIES_TOTAL)
            if (Metric.ExerciseMinutes in metrics) put(Metric.ExerciseMinutes, ExerciseSessionRecord.EXERCISE_DURATION_TOTAL)
            if (Metric.HeartRate in metrics) put(Metric.HeartRate, HeartRateRecord.BPM_AVG)
            if (Metric.RestingHeartRate in metrics) put(Metric.RestingHeartRate, RestingHeartRateRecord.BPM_AVG)
        }
        if (aggregated.isNotEmpty()) {
            val groups = client.aggregateGroupByPeriod(
                AggregateGroupByPeriodRequest(
                    metrics = aggregated.values.toSet(),
                    timeRangeFilter = TimeRangeFilter.between(from.atStartOfDay(), today.plusDays(1).atStartOfDay()),
                    timeRangeSlicer = Period.ofDays(1),
                ),
            )
            for (group in groups) {
                val day = values[group.startTime.toLocalDate()] ?: continue
                for ((metric, aggregate) in aggregated) {
                    val value = when (val raw = group.result[aggregate]) {
                        is Long -> raw
                        is Duration -> raw.toMinutes()
                        is androidx.health.connect.client.units.Energy -> raw.inKilocalories.roundToLong()
                        else -> null
                    } ?: continue
                    day[metric.key] = JsonPrimitive(value)
                }
            }
        }
        if (Metric.SleepHours in metrics) {
            // A night belongs to the day it ends on.
            val sleep = mutableMapOf<LocalDate, Duration>()
            read(SleepSessionRecord::class, from.minusDays(1).atStartOfDay(zone), today.plusDays(1).atStartOfDay(zone)).forEach { record ->
                val day = record.endTime.atZone(zone).toLocalDate()
                sleep[day] = (sleep[day] ?: Duration.ZERO) + Duration.between(record.startTime, record.endTime)
            }
            for ((day, total) in sleep) values[day]?.put(Metric.SleepHours.key, JsonPrimitive(rounded(total.toMinutes() / 60.0)))
        }
        if (Metric.Weight in metrics) {
            read(WeightRecord::class, from.atStartOfDay(zone), today.plusDays(1).atStartOfDay(zone))
                .groupBy { it.time.atZone(zone).toLocalDate() }
                .forEach { (day, records) ->
                    val latest = records.maxBy { it.time }
                    values[day]?.put(Metric.Weight.key, JsonPrimitive(rounded(latest.weight.inKilograms)))
                }
        }
        return buildJsonObject {
            put("from", from.toString())
            put("to", today.toString())
            putJsonObject("units") { metrics.forEach { put(it.key, it.unit) } }
            putJsonArray("days") {
                for ((day, row) in values) addJsonObject {
                    put("date", day.toString())
                    // Keep the requested metric order.
                    metrics.forEach { metric -> row[metric.key]?.let { put(metric.key, it) } }
                }
            }
        }
    }

    private suspend fun <T : Record> read(type: KClass<T>, start: ZonedDateTime, end: ZonedDateTime): List<T> {
        val out = mutableListOf<T>()
        var token: String? = null
        do {
            val page = client.readRecords(
                ReadRecordsRequest(type, TimeRangeFilter.between(start.toInstant(), end.toInstant()), pageToken = token),
            )
            out += page.records
            token = page.pageToken
        } while (token != null && out.size < 5000)
        return out
    }

    private fun rounded(value: Double): Double = Math.round(value * 10) / 10.0
}
