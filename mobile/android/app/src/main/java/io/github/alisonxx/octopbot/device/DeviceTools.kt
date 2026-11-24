package io.github.alisonxx.octopbot.device

import io.github.alisonxx.octopbot.model.HitlAction
import io.github.alisonxx.octopbot.model.HitlDecision
import io.github.alisonxx.octopbot.model.HitlRequest
import io.github.alisonxx.octopbot.net.Http
import io.github.alisonxx.octopbot.net.arr
import io.github.alisonxx.octopbot.net.asObject
import io.github.alisonxx.octopbot.net.asString
import io.github.alisonxx.octopbot.net.bool
import io.github.alisonxx.octopbot.net.obj
import io.github.alisonxx.octopbot.net.objects
import io.github.alisonxx.octopbot.net.str
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.addJsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonObject

/** A system data source the phone can open to its Bots (mobile/PROTOCOL.md §C). */
enum class DeviceCapability(val key: String) {
    Health("health"),
    Calendar("calendar"),
    Reminders("reminders"),
    ;

    companion object {
        fun of(key: String?): DeviceCapability? = entries.firstOrNull { it.key == key }
    }
}

/** One entry of `device_tools.json`. */
data class DeviceTool(
    val name: String,
    val capability: DeviceCapability,
    val writes: Boolean,
    val description: String,
    /** JSON Schema of the arguments. */
    val parameters: JsonObject,
)

/** The tools of the connectors that are on, and how to run them on this phone. */
interface DeviceToolbox {
    /** Tools offered to the Bot right now: their connector is on and the system permission granted. */
    suspend fun offered(): List<DeviceTool>
    /** A tool this platform knows, on or off. */
    fun tool(name: String): DeviceTool?
    /** The tool chip label in the app language. */
    fun label(name: String): String
    /** Runs one call; the result is a JSON object or `{"error": …}`, never an exception. */
    suspend fun run(name: String, args: JsonObject): JsonObject

    companion object {
        val None: DeviceToolbox = object : DeviceToolbox {
            override suspend fun offered() = emptyList<DeviceTool>()
            override fun tool(name: String): DeviceTool? = null
            override fun label(name: String) = name
            override suspend fun run(name: String, args: JsonObject) = DeviceCatalog.error("This tool is not available on this phone.")
        }
    }
}

/** Pure handling of `device_tools.json` and its tool calls (no Android APIs). */
object DeviceCatalog {
    const val PREFIX = "device_"

    /** Android has no system to-do store, so Reminders never appears here. */
    val ANDROID = setOf(DeviceCapability.Health, DeviceCapability.Calendar)

    fun isDevice(name: String) = name.startsWith(PREFIX)

    /** The tools of `device_tools.json` whose capability this platform supports. */
    fun parse(text: String, supported: Set<DeviceCapability> = ANDROID): List<DeviceTool> =
        Http.parse(text).asObject()?.arr("tools")?.objects().orEmpty().mapNotNull { row ->
            val name = row.str("name")?.takeIf(::isDevice) ?: return@mapNotNull null
            val capability = DeviceCapability.of(row.str("capability"))?.takeIf { it in supported } ?: return@mapNotNull null
            DeviceTool(
                name = name,
                capability = capability,
                writes = row.bool("writes") == true,
                description = row.str("description").orEmpty(),
                parameters = row.obj("parameters") ?: JsonObject(emptyMap()),
            )
        }

    /** Tools whose capability is on (and permitted). */
    fun offered(tools: List<DeviceTool>, on: Set<DeviceCapability>): List<DeviceTool> = tools.filter { it.capability in on }

    /** OpenAI function-calling `tools`. */
    fun openAiTools(tools: List<DeviceTool>): JsonArray = buildJsonArray {
        for (tool in tools) addJsonObject {
            put("type", "function")
            putJsonObject("function") {
                put("name", tool.name)
                put("description", tool.description)
                put("parameters", tool.parameters)
            }
        }
    }

    fun error(reason: String): JsonObject = buildJsonObject { put("error", reason) }

    /** Arguments arrive as an object or as a JSON string; anything unreadable is no arguments. */
    fun args(raw: String?): JsonObject =
        raw?.takeIf { it.isNotBlank() }?.let { runCatching { Http.parse(it).asObject() }.getOrNull() } ?: JsonObject(emptyMap())
}

/** Decisions for a paused turn whose actions include device tools. */
object DeviceDecisions {
    /** The reject message for a declined device write, and its tool result in Lynxce mode. */
    const val DECLINED = "The user declined."

    fun isDevice(action: HitlAction) = DeviceCatalog.isDevice(action.name)

    /**
     * Only device reads: run them and resume right away, without a card. A device tool this phone doesn't know
     * counts as a read (it answers with an error at once).
     */
    fun runsAlone(request: HitlRequest, writes: (String) -> Boolean): Boolean =
        request.actions.isNotEmpty() && request.actions.all { isDevice(it) && !writes(it.name) }

    /**
     * One decision per action, in order. Approve: device actions are run ([run] returns the result JSON) and
     * answered with `respond`, questions with [questionReply], other tools with `approve`. Reject: every action
     * is rejected (a question mixed in gets [questionReply]).
     */
    suspend fun review(
        request: HitlRequest,
        approve: Boolean,
        questionReply: String,
        run: suspend (HitlAction) -> String,
    ): List<HitlDecision> = request.actions.map { action ->
        when {
            action.questions != null -> HitlDecision.Respond(questionReply)
            isDevice(action) -> if (approve) HitlDecision.Respond(run(action)) else HitlDecision.Reject(DECLINED)
            approve -> HitlDecision.Approve
            else -> HitlDecision.Reject()
        }
    }
}

/**
 * Joins streamed OpenAI `delta.tool_calls` pieces by `index`: the id and name come once, the arguments
 * arrive in fragments.
 */
class ToolCallAccumulator {
    data class Call(val id: String, val name: String, val arguments: String)

    private class Part(var id: String? = null, var name: String = "", val arguments: StringBuilder = StringBuilder())

    private val parts = sortedMapOf<Int, Part>()

    val isEmpty: Boolean get() = parts.isEmpty()

    fun add(toolCalls: JsonArray) {
        toolCalls.forEachIndexed { position, raw ->
            val row = raw.asObject() ?: return@forEachIndexed
            val index = (row["index"] as? kotlinx.serialization.json.JsonPrimitive)?.content?.toIntOrNull() ?: position
            val part = parts.getOrPut(index) { Part() }
            row.str("id")?.takeIf { it.isNotEmpty() }?.let { part.id = it }
            row.obj("function")?.let { function ->
                function.str("name")?.takeIf { it.isNotEmpty() }?.let { part.name = if (part.name.isEmpty()) it else part.name }
                function["arguments"]?.let { part.arguments.append(it.asString() ?: it.toString()) }
            }
        }
    }

    /** Calls in index order; a call without an id gets `call_<index>`. Calls without a name are dropped. */
    fun calls(): List<Call> = parts.mapNotNull { (index, part) ->
        if (part.name.isEmpty()) null else Call(part.id ?: "call_$index", part.name, part.arguments.toString())
    }
}
