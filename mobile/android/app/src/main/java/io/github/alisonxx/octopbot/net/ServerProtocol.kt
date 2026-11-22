package io.github.alisonxx.octopbot.net

import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.ChatMessage
import io.github.alisonxx.octopbot.model.ConversationSummary
import io.github.alisonxx.octopbot.model.GroupDraft
import io.github.alisonxx.octopbot.model.GroupGoal
import io.github.alisonxx.octopbot.model.GroupMessage
import io.github.alisonxx.octopbot.model.GroupSummary
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.model.MessageRole
import io.github.alisonxx.octopbot.model.MessageStatus
import io.github.alisonxx.octopbot.model.StreamEvent
import io.github.alisonxx.octopbot.model.Times
import io.github.alisonxx.octopbot.model.ToolStep
import io.github.alisonxx.octopbot.model.VoiceSupport
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.addJsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.putJsonObject
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import java.util.UUID

/** Pure Octop server wire mapping (no I/O), shared by [ServerBackend] and unit tests. */
object ServerProtocol {
    /** Accepts "nas.local:8080" as well as a full URL; returns the origin without a trailing slash. */
    fun normalizeUrl(text: String): String? {
        var raw = text.trim().trimEnd('/')
        if (raw.isEmpty()) return null
        if ("://" !in raw) raw = "https://$raw"
        val url = raw.toHttpUrlOrNull() ?: return null
        return url.toString().trimEnd('/')
    }

    fun bot(row: JsonObject): BotProfile? {
        val id = row.str("agent_id") ?: return null
        val chief = row.bool("is_main") ?: false
        val avatar = row.obj("avatar")
        return BotProfile(
            id = id,
            name = row.str("name")?.takeIf { it.isNotBlank() } ?: id,
            subtitle = row.str("description")?.takeIf { it.isNotBlank() },
            look = normalizedLook(avatar?.str("shape"), avatar?.str("color"), chief),
            isChief = chief,
        )
    }

    /** Same remapping as the dashboard's `visibleAppearance`. */
    fun normalizedLook(shape: String?, color: String?, chief: Boolean): Look {
        if (shape == null || color == null) return if (chief) Look.chief else Look.fallback
        val ink = if (color == "deepseek") "blue" else color
        if (shape == "whale") return if (chief) Look.chief else Look("gumdrop", ink)
        return Look(shape, ink)
    }

    /** Workspace → enabled Bots (Chief first) and groups. */
    fun workspace(body: JsonElement): Pair<List<BotProfile>, List<GroupSummary>> {
        val obj = body.asObject() ?: return emptyList<BotProfile>() to emptyList()
        val bots = obj.arr("bots")?.objects().orEmpty()
            .filter { it.bool("enabled") != false }
            .mapNotNull(::bot)
            .sortedByDescending { it.isChief }
        return bots to groups(obj["groups"] ?: JsonNull)
    }

    fun groups(body: JsonElement): List<GroupSummary> = body.asArray()?.objects().orEmpty().mapNotNull { row ->
        val id = row.idString("group_id") ?: return@mapNotNull null
        GroupSummary(
            id = id,
            name = row.str("name") ?: id,
            adminId = row.str("admin_id"),
            memberIds = row.arr("member_ids")?.mapNotNull { it.asString() }.orEmpty(),
        )
    }

    /** Threads that have messages, newest first. Empty titles are filled in by the UI. */
    fun conversations(body: JsonElement, botId: String): List<ConversationSummary> =
        body.asArray()?.objects().orEmpty().mapNotNull { row ->
            val id = row.str("thread_id") ?: return@mapNotNull null
            if (row.bool("has_messages") == false) return@mapNotNull null
            val updated = Times.parseIso(row.str("last_active")) ?: row.double("last_active")?.let(Times::epochMillis)
            ConversationSummary(id, row.str("title")?.trim().orEmpty(), updated, botId)
        }.sortedByDescending { it.updatedAt ?: 0L }

    /** `GET /api/i18n/tools` → tool name → label in the request's language. */
    fun toolLabels(body: JsonElement): Map<String, String> =
        body.asObject()?.obj("labels")?.mapNotNull { (name, label) -> label.asString()?.let { name to it } }?.toMap().orEmpty()

    data class HistoryPage(val messages: List<ChatMessage>, val loading: Boolean, val retryAfterMs: Long)

    fun historyPage(body: JsonElement, toolLabels: Map<String, String> = emptyMap()): HistoryPage {
        val obj = body.asObject() ?: return HistoryPage(emptyList(), false, 0)
        return HistoryPage(
            messages = history(obj.arr("messages") ?: JsonArray(emptyList()), toolLabels),
            loading = obj.bool("history_loading") == true,
            retryAfterMs = obj.long("history_retry_after_ms") ?: 800,
        )
    }

    /** History rows → chat messages. Tool rows are skipped; consecutive assistant segments merge into one reply. */
    fun history(rows: JsonArray, toolLabels: Map<String, String> = emptyMap()): List<ChatMessage> {
        val out = mutableListOf<ChatMessage>()
        for (row in rows.objects()) {
            val role = when (row.str("role")) {
                "user" -> MessageRole.User
                "assistant" -> MessageRole.Assistant
                else -> continue
            }
            val text = StringBuilder()
            val thinking = StringBuilder()
            val tools = mutableListOf<ToolStep>()
            val images = mutableListOf<String>()
            when (val content = row["content"]) {
                is JsonPrimitive -> if (content.isString) text.append(content.content)
                is JsonArray -> for (block in content.objects()) when (block.str("type")) {
                    "text" -> text.append(block.str("text").orEmpty())
                    "thinking" -> thinking.append(block.str("thinking").orEmpty())
                    "tool_use" -> {
                        val name = block.str("name") ?: "tool"
                        tools += ToolStep(block.str("id") ?: UUID.randomUUID().toString(), toolLabels[name] ?: name, done = true)
                    }
                    "image" -> block.obj("source")?.str("url")?.let(images::add)
                }
                else -> Unit
            }
            val timestamp = row.double("timestamp")?.let(Times::epochMillis) ?: Times.parseIso(row.str("timestamp"))
            val last = out.lastOrNull()
            if (role == MessageRole.Assistant && last?.role == MessageRole.Assistant) {
                val separator = if (last.text.isEmpty() || text.isEmpty()) "" else "\n\n"
                out[out.lastIndex] = last.copy(
                    text = last.text + separator + text,
                    thinking = last.thinking + thinking,
                    tools = last.tools + tools,
                )
                continue
            }
            if (text.isEmpty() && thinking.isEmpty() && tools.isEmpty() && images.isEmpty()) continue
            out += ChatMessage(
                id = row.idString("id") ?: UUID.randomUUID().toString(),
                role = role,
                text = text.toString(),
                thinking = thinking.toString(),
                images = images,
                tools = tools,
                status = if (row.str("status") == "error") MessageStatus.Failed(null) else MessageStatus.Done,
                createdAt = timestamp ?: System.currentTimeMillis(),
            )
        }
        return out
    }

    fun userTurn(threadId: String, text: String, content: JsonElement, model: String?): JsonObject = buildJsonObject {
        put("type", "user_turn")
        put("thread_id", threadId)
        put("text", text)
        putJsonArray("messages") {
            addJsonObject {
                put("role", "user")
                put("content", content)
                put("id", UUID.randomUUID().toString())
            }
        }
        model?.let { put("model", it) }
    }

    fun cancel(threadId: String) = buildJsonObject {
        put("type", "cancel")
        put("thread_id", threadId)
    }

    val ping = buildJsonObject { put("type", "ping") }

    /** `[{text}, {image…}…]` content after uploading photos. */
    fun imageContent(text: String, uploads: List<JsonObject>): JsonArray = buildJsonArray {
        addJsonObject { put("type", "text"); put("text", text) }
        for (upload in uploads) addJsonObject {
            val mediaType = upload.str("media_type") ?: "image/jpeg"
            put("type", "image")
            putJsonObject("source") {
                put("type", "url")
                put("url", upload.str("url").orEmpty())
                put("media_type", mediaType)
            }
            put("workspace_path", upload.str("workspace_path") ?: throw ApiException.badResponse())
            put("filename", upload.str("filename") ?: "photo.jpg")
        }
    }

    /**
     * Maps chat WebSocket frames to stream events; remembers tool names so results can be labelled.
     * Tools without a `display_name` are named through [toolLabels].
     */
    class FrameMapper(private val toolLabels: Map<String, String> = emptyMap()) {
        sealed interface Outcome {
            data class Events(val events: List<StreamEvent>) : Outcome
            data object Finished : Outcome
        }

        private val toolNames = mutableMapOf<String, String>()

        fun map(frame: JsonObject, threadId: String): Outcome {
            val frameThread = frame.str("thread_id")
            if (frameThread != null && frameThread != threadId) return Outcome.Events(emptyList())
            return when (frame.str("type")) {
                "token" -> text(frame) { StreamEvent.Text(it) }
                "reasoning" -> text(frame) { StreamEvent.Thinking(it) }
                "tool_call_chunk" -> {
                    val id = frame.str("id")?.takeIf { it.isNotEmpty() }
                    val name = (frame.str("display_name") ?: frame.str("name")?.let { toolLabels[it] ?: it })?.takeIf { it.isNotEmpty() }
                    if (id == null || name == null || id in toolNames) return Outcome.Events(emptyList())
                    toolNames[id] = name
                    Outcome.Events(listOf(StreamEvent.Tool(id, name, done = false)))
                }
                "tool_result" -> Outcome.Events(
                    frame.arr("messages")?.objects().orEmpty().mapNotNull { message ->
                        val id = message.str("tool_call_id") ?: message.str("id") ?: return@mapNotNull null
                        toolNames[id]?.let { StreamEvent.Tool(id, it, done = true) }
                    },
                )
                "error" -> throw ApiException(ApiException.Kind.Server, 500, frame.str("message"))
                "turn.ended" -> {
                    if (frame.bool("failed") == true) throw ApiException(ApiException.Kind.Server, 500)
                    Outcome.Finished
                }
                else -> Outcome.Events(emptyList())
            }
        }

        private inline fun text(frame: JsonObject, event: (String) -> StreamEvent): Outcome =
            Outcome.Events(listOfNotNull(frame.str("content")?.takeIf { it.isNotEmpty() }?.let(event)))
    }

    /** WebSocket close codes → user-facing failures. */
    fun closeError(code: Int, reason: String?): ApiException = when (code) {
        4001 -> ApiException(ApiException.Kind.Unauthorized, 401)
        4003 -> ApiException(ApiException.Kind.Rejected, 403, reason?.takeIf { it.isNotBlank() })
        4404 -> ApiException(ApiException.Kind.Rejected, 404, reason?.takeIf { it.isNotBlank() })
        else -> ApiException.network()
    }

    fun groupMessages(body: JsonElement): List<GroupMessage> = body.asArray()?.objects().orEmpty().mapNotNull { row ->
        val id = row.idString("message_id") ?: return@mapNotNull null
        GroupMessage(
            id = id,
            role = row.str("role") ?: "assistant",
            agentId = row.str("agent_id"),
            text = row.str("text").orEmpty(),
            createdAt = row.double("created_at")?.let(Times::epochMillis) ?: Times.parseIso(row.str("created_at")) ?: 0L,
        )
    }

    fun groupDrafts(body: JsonElement): List<GroupDraft> = body.asArray()?.objects().orEmpty().mapNotNull { row ->
        GroupDraft(row.str("agent_id") ?: return@mapNotNull null, row.str("text").orEmpty())
    }

    fun groupGoal(body: JsonElement): GroupGoal? {
        val obj = body.asObject() ?: return null
        val title = obj.str("title")?.takeIf { it.isNotBlank() } ?: return null
        return GroupGoal(title, obj.str("status") ?: "draft")
    }

    /** A new group: Chief administers when picked, else the first member; Bots answer admin-first. */
    fun groupCreate(name: String, members: List<BotProfile>): JsonObject {
        val admin = members.firstOrNull { it.isChief } ?: members.first()
        return buildJsonObject {
            put("name", name.trim())
            put("admin_id", admin.id)
            putJsonArray("member_ids") { members.forEach { add(JsonPrimitive(it.id)) } }
            put("reply_mode", "admin_first")
        }
    }

    fun groupPost(requestId: String, text: String, mentionIds: List<String>) = buildJsonObject {
        put("request_id", requestId)
        put("text", text)
        putJsonArray("mention_ids") { mentionIds.forEach { add(JsonPrimitive(it)) } }
    }

    fun voiceSupport(body: JsonElement): VoiceSupport {
        val obj = body.asObject() ?: return VoiceSupport(stt = false, tts = false)
        fun set(key: String) = when (val value = obj[key]) {
            null, JsonNull -> false
            is JsonPrimitive -> value.isString && value.content.isNotBlank()
            else -> true
        }
        return VoiceSupport(stt = set("stt"), tts = set("tts"))
    }
}
