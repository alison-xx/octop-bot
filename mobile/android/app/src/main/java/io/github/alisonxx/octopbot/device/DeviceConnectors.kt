package io.github.alisonxx.octopbot.device

import android.content.Context
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.app.AppLocale
import io.github.alisonxx.octopbot.store.AppStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import java.time.ZoneId

/** Settings → Device connectors on Android: Health Connect and the system calendar, run for the Bots. */
class DeviceConnectors(private val context: Context, private val store: AppStore) : DeviceToolbox {
    val health = HealthConnector(context)
    val calendar = CalendarConnector(context)

    private val catalog: List<DeviceTool> by lazy {
        runCatching { DeviceCatalog.parse(context.assets.open("device_tools.json").bufferedReader().use { it.readText() }) }
            .getOrDefault(emptyList())
    }

    /** Connectors whose switch is on and whose system permission is granted. */
    suspend fun active(): Set<DeviceCapability> {
        val settings = store.settings.first()
        return buildSet {
            if (settings.deviceHealth && health.permitted()) add(DeviceCapability.Health)
            if (settings.deviceCalendar && calendar.permitted()) add(DeviceCapability.Calendar)
        }
    }

    override suspend fun offered(): List<DeviceTool> = DeviceCatalog.offered(catalog, active())

    override fun tool(name: String): DeviceTool? = catalog.firstOrNull { it.name == name }

    override fun label(name: String): String {
        val res = AppLocale.resources(context)
        return when (name) {
            "device_health_summary" -> res.getString(R.string.device_tool_health_summary)
            "device_calendar_events" -> res.getString(R.string.device_tool_calendar_events)
            "device_calendar_create_event" -> res.getString(R.string.device_tool_calendar_create)
            "device_calendar_update_event" -> res.getString(R.string.device_tool_calendar_update)
            else -> name
        }
    }

    override suspend fun run(name: String, args: JsonObject): JsonObject {
        val tool = tool(name) ?: return DeviceCatalog.error("$name is not available on this phone.")
        if (tool.capability !in active()) return DeviceCatalog.error("The user has turned this connector off on the phone.")
        val zone = ZoneId.systemDefault()
        return try {
            withContext(Dispatchers.IO) {
                when (name) {
                    "device_health_summary" -> health.summary(args, zone)
                    "device_calendar_events" -> calendar.events(args, zone)
                    "device_calendar_create_event" -> calendar.create(args, zone)
                    "device_calendar_update_event" -> calendar.update(args, zone)
                    else -> DeviceCatalog.error("$name is not available on this phone.")
                }
            }
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: Throwable) {
            DeviceCatalog.error(error.message ?: error.javaClass.simpleName)
        }
    }
}
