package io.github.alisonxx.octopbot.net

import io.github.alisonxx.octopbot.device.DeviceCatalog
import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.ChatMessage
import io.github.alisonxx.octopbot.model.ConversationSummary
import io.github.alisonxx.octopbot.model.FileAttachment
import io.github.alisonxx.octopbot.model.FileCards
import io.github.alisonxx.octopbot.model.GroupDraft
import io.github.alisonxx.octopbot.model.GroupGoal
import io.github.alisonxx.octopbot.model.GroupMessage
import io.github.alisonxx.octopbot.model.GroupSummary
import io.github.alisonxx.octopbot.model.HitlAction
import io.github.alisonxx.octopbot.model.HitlDecision
import io.github.alisonxx.octopbot.model.HitlOption
import io.github.alisonxx.octopbot.model.HitlQuestion
import io.github.alisonxx.octopbot.model.HitlRequest
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
    fun rechargeBody(account: String, need: Double? = null, reason: String? = null) = buildJsonObject {
        put("source", "cloud")
        put("expected_account_id", account)
        put("intent", "credits")
        put("from", "android")
        need?.takeIf { it.isFinite() && it > 0 && it <= Int.MAX_VALUE }?.let { put("need", kotlin.math.ceil(it).toInt()) }
        reason?.takeIf { it in setOf("text", "image", "video", "computer", "disk", "plan_limit") }?.let { put("reason", it) }
    }

    /** Octop Bot cloud, run by Lynxce. */
    const val LYNXCE_CLOUD = "https://bot.lynxce.cn"

    fun isCloudInfo(info: JsonElement): Boolean {
        val obj = info.asObject() ?: return false
        return obj.str("product") == "octop-bot" && obj.str("edition") == "cloud"
    }

    /** A Bot's cloud computer on Octop Bot cloud (`/api/octop-bot/computers/{id}`). */
    data class ComputerStatus(
        val state: State,
        val runningSinceMillis: Long?,
        val takeover: Boolean = false,
        /** The Bot is working on the computer right now, and its last action (`click`, `type`, …). */
        val busy: Boolean = false,
        val activity: String? = null,
    ) {
        enum class State { None, Running, Paused }
    }

    /** `GET …/computers/{id}/glance`: the front window's title and a small JPEG of the screen. */
    class Glance(val window: String?, val thumbnail: ByteArray?)

    fun glance(data: JsonElement): Glance? {
        val obj = data.asObject() ?: return null
        val thumbnail = obj.str("thumbnail")?.let { runCatching { java.util.Base64.getDecoder().decode(it) }.getOrNull() }
        return Glance(obj.str("window")?.takeIf { it.isNotBlank() }, thumbnail)
    }

    fun computerStatus(data: JsonElement): ComputerStatus? {
        val obj = data.asObject() ?: return null
        val state = when (obj.str("state")) {
            "none" -> ComputerStatus.State.None
            "running" -> ComputerStatus.State.Running
            "paused" -> ComputerStatus.State.Paused
            else -> return null
        }
        return ComputerStatus(
            state,
            obj.double("running_since")?.let { (it * 1000).toLong() },
            obj.bool("takeover") == true,
            busy = obj.bool("busy") == true,
            activity = obj.str("activity"),
        )
    }

    /**
     * The server's screen page for a Bot's computer, opened in the browser with a one-time ticket and the
     * screen session that lets the page type Chinese and sync the clipboard while the user has taken over.
     */
    fun screenPage(baseUrl: String, botId: String, wsPath: String, session: String?, control: Boolean): String? {
        val ticket = (baseUrl.trimEnd('/') + wsPath).toHttpUrlOrNull()?.queryParameter("ticket") ?: return null
        val page = (baseUrl.trimEnd('/') + "/octop-bot/screen/").toHttpUrlOrNull()?.newBuilder()
            ?.addPathSegment(botId)
            ?.addQueryParameter("ticket", ticket) ?: return null
        if (!session.isNullOrEmpty()) page.addQueryParameter("session", session)
        return page.addQueryParameter("control", if (control) "1" else "0").build().toString()
    }

    /** `/api/agents/{id}/workspace/download?path=…`, the link Octop puts in a reply for a file. */
    fun isWorkspaceDownload(uri: String): Boolean = FileCards.isWorkspaceDownload(uri)

    /** `POST /api/auth/lynxce/code`: the server tells phone from email itself and texts or emails the owner. */
    fun lynxceCodeBody(target: String, chinese: Boolean) = buildJsonObject {
        put("target", target.trim())
        put("locale", if (chinese) "zh" else "en")
    }

    /** `POST /api/auth/lynxce/code-login`: answers like `/api/auth/lynxce/login`. */
    fun lynxceCodeLoginBody(target: String, code: String, chinese: Boolean, localPassword: String? = null) = buildJsonObject {
        put("target", target.trim())
        put("code", code)
        put("locale", if (chinese) "zh" else "en")
        if (!localPassword.isNullOrEmpty()) put("local_password", localPassword)
    }

    /** Accepts "nas.local:8080" as well as a full URL; returns the origin without a trailing slash. */
    fun normalizeUrl(text: String): String? {
        var raw = text.trim().trimEnd('/')
        if (raw.isEmpty()) return null
        if ("://" !in raw) raw = "https://$raw"
        val url = raw.toHttpUrlOrNull() ?: return null
        return url.toString().trimEnd('/')
    }

    /** Usernames that are ids, not names: Octop's SSO accounts and the Bot web build's built-in users. */
    private val INTERNAL_NAME = Regex("^sso_[A-Za-z0-9_-]+$")

    /** A display name fit to show, or null for the generic "Lynxce user" (sessions saved before display names). */
    fun personName(name: String?): String? {
        val trimmed = name?.trim().orEmpty()
        if (trimmed.isEmpty() || trimmed == "owner" || trimmed == "local" || trimmed == "Octop" || INTERNAL_NAME.matches(trimmed)) return null
        return trimmed
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
            state = row.str("state"),
            preparing = row.bool("preparing") ?: false,
            lastError = row.str("last_error"),
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
            ConversationSummary(id, row.str("title")?.trim().orEmpty(), updated, botId, row.bool("owned"), row.bool("is_active") == true)
        }.sortedByDescending { it.updatedAt ?: 0L }

    /** `GET /api/i18n/tools` → tool name → label in the request's language. */
    fun toolLabels(body: JsonElement): Map<String, String> =
        body.asObject()?.obj("labels")?.mapNotNull { (name, label) -> label.asString()?.let { name to it } }?.toMap().orEmpty()

    data class HistoryPage(
        val messages: List<ChatMessage>,
        val loading: Boolean,
        val retryAfterMs: Long,
        /** `hitl_pending`: a question or approval still open in this thread. */
        val pending: HitlRequest? = null,
    )

    fun historyKey(row: JsonElement): String? = row.asObject()?.let { obj ->
        obj.long("history_seq")?.let { "seq:$it" } ?: obj.idString("id")
    }

    fun joinHistory(earlier: JsonArray, later: JsonArray): JsonArray {
        val ids = later.mapNotNull(::historyKey).toSet()
        val overlap = earlier.indexOfFirst { historyKey(it) in ids }
        return JsonArray((if (overlap < 0) earlier else earlier.take(overlap)) + later)
    }

    fun historyPage(body: JsonElement, toolLabels: Map<String, String> = emptyMap(), agentId: String? = null): HistoryPage {
        val obj = body.asObject() ?: return HistoryPage(emptyList(), false, 0)
        return HistoryPage(
            messages = history(obj.arr("messages") ?: JsonArray(emptyList()), toolLabels, agentId),
            loading = obj.bool("history_loading") == true,
            retryAfterMs = obj.long("history_retry_after_ms") ?: 800,
            pending = hitlRequest(obj["hitl_pending"], toolLabels),
        )
    }

    /**
     * History rows → chat messages. Consecutive assistant segments merge into one reply. Tool rows only
     * contribute the files that `send_file_to_user` delivered, which join the reply of that turn.
     */
    fun history(rows: JsonArray, toolLabels: Map<String, String> = emptyMap(), agentId: String? = null): List<ChatMessage> {
        val out = mutableListOf<ChatMessage>()
        val sent = mutableListOf<FileAttachment>()
        // Files from tool rows with no reply after them in their turn go on the last reply (or a reply of their own).
        fun flushSent() {
            if (sent.isEmpty()) return
            val last = out.lastOrNull()
            if (last?.role == MessageRole.Assistant) {
                out[out.lastIndex] = last.copy(attachments = FileCards.merge(last.attachments, sent))
            } else {
                out += ChatMessage(role = MessageRole.Assistant, text = "", attachments = sent.toList(), createdAt = last?.createdAt ?: System.currentTimeMillis())
            }
            sent.clear()
        }
        for (row in rows.objects()) {
            val role = when (row.str("role")) {
                "user" -> MessageRole.User
                "assistant" -> MessageRole.Assistant
                "tool" -> {
                    val owner = row.str("agent_id")?.takeIf { it.isNotBlank() } ?: agentId
                    val merged = FileCards.merge(sent.toList(), sentFiles(row, owner))
                    sent.clear()
                    sent += merged
                    continue
                }
                else -> continue
            }
            if (role == MessageRole.User) flushSent()
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
            val files = if (role == MessageRole.Assistant) sent.toList().also { sent.clear() } else emptyList()
            val last = out.lastOrNull()
            if (role == MessageRole.Assistant && last?.role == MessageRole.Assistant) {
                val separator = if (last.text.isEmpty() || text.isEmpty()) "" else "\n\n"
                out[out.lastIndex] = last.copy(
                    text = last.text + separator + text,
                    thinking = last.thinking + thinking,
                    tools = last.tools + tools,
                    attachments = FileCards.merge(last.attachments, files),
                )
                continue
            }
            if (text.isEmpty() && thinking.isEmpty() && tools.isEmpty() && images.isEmpty() && files.isEmpty()) continue
            out += ChatMessage(
                id = row.idString("id") ?: row.long("history_seq")?.let { "history-$it" } ?: UUID.randomUUID().toString(),
                role = role,
                text = text.toString(),
                thinking = thinking.toString(),
                images = images,
                tools = tools,
                attachments = files,
                status = if (row.str("status") == "error") {
                    MessageStatus.Failed(
                        null,
                        credits = ApiException.isCreditsRequired(row.str("error_code")),
                        dailyLimit = row.str("error_code") == ApiException.DAILY_LIMIT,
                    )
                } else {
                    MessageStatus.Done
                },
                createdAt = timestamp ?: System.currentTimeMillis(),
            )
        }
        flushSent()
        return out
    }

    private val fileDeliveryTools = setOf("send_file", "send_file_to_user", "generate_image", "generate_video")

    /** Files in a history `role:"tool"` row of `send_file_to_user` (its `output` is a JSON block or a list of them). */
    fun sentFiles(row: JsonObject, agentId: String?): List<FileAttachment> =
        (row["content"] as? JsonArray)?.objects().orEmpty().flatMap { block ->
            if (block.str("type") != "tool_result") return@flatMap emptyList()
            val name = block.str("name").orEmpty().substringAfterLast('/')
            if (name !in fileDeliveryTools) return@flatMap emptyList()
            val output = block.str("output")?.trim().orEmpty()
            if (output.isEmpty() || output[0] !in "{[") return@flatMap emptyList()
            when (val parsed = Http.parse(output)) {
                is JsonObject -> generatedFiles(parsed, agentId) ?: listOfNotNull(sentFile(parsed, agentId))
                is JsonArray -> parsed.objects().mapNotNull { sentFile(it, agentId) }
                else -> emptyList()
            }
        }

    /** A `generate_image` / `generate_video` result: its `images` / `videos` rows, or null for other blocks. */
    private fun generatedFiles(result: JsonObject, agentId: String?): List<FileAttachment>? {
        val field = when (result.str("type")) {
            "image_gen_tool_result" -> "images"
            "video_gen_tool_result" -> "videos"
            else -> return null
        }
        return result.arr(field)?.objects().orEmpty().mapNotNull { row ->
            val path = row.str("path")?.takeIf { it.isNotBlank() } ?: return@mapNotNull null
            val url = agentId?.let { workspaceDownloadPath(it, path) } ?: return@mapNotNull null
            FileAttachment(url, FileCards.baseName(path), row.str("mediaType"))
        }
    }

    private fun sentFile(block: JsonObject, agentId: String?): FileAttachment? {
        val type = block.str("type")
        if (type != "file" && type != "image") return null
        val path = block.str("path")?.takeIf { it.isNotBlank() }
        val mime = block.str("media_type") ?: block.str("mime_type") ?: block.obj("source")?.str("media_type")
        val preview = (block.str("preview_url") ?: block.obj("source")?.str("url"))?.takeIf { type == "image" && it.startsWith("/api/") }
        val url = preview ?: path?.let { p -> agentId?.let { workspaceDownloadPath(it, p) } } ?: return null
        val name = block.str("filename")?.takeIf { it.isNotBlank() }
            ?: path?.let(FileCards::baseName)?.takeIf { it.isNotEmpty() }
            ?: return null
        return FileAttachment(url, name, mime)
    }

    /** `/api/agents/{id}/workspace/download?path=…` for a workspace (or tool-output) path. */
    fun workspaceDownloadPath(agentId: String, path: String): String =
        "/api/agents/" + encode(agentId) + "/workspace/download?path=" + encode(path)

    private fun encode(value: String): String = java.net.URLEncoder.encode(value, "UTF-8").replace("+", "%20")

    /** A live `attachment` frame: `{kind, url, filename?, path?, mime_type?}` with a server-relative URL. */
    fun attachmentFrame(frame: JsonObject): FileAttachment? {
        val url = frame.str("url")?.takeIf { it.startsWith("/api/") } ?: return null
        val name = frame.str("filename")?.takeIf { it.isNotBlank() }
            ?: frame.str("path")?.let(FileCards::baseName)?.takeIf { it.isNotEmpty() }
            ?: FileCards.queryValue(url, "path")?.let(FileCards::baseName)?.takeIf { it.isNotEmpty() }
            ?: FileCards.queryValue(url, "source")?.let(FileCards::baseName)?.takeIf { it.isNotEmpty() }
            ?: return null
        return FileAttachment(url, name, frame.str("mime_type"))
    }

    /** [deviceTools]: the phone's tools that are on (PROTOCOL §C); sent on every turn so the server can drop them. */
    fun userTurn(threadId: String, text: String, content: JsonElement, model: String?, deviceTools: List<String> = emptyList()): JsonObject = buildJsonObject {
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
        putJsonArray("device_tools") { deviceTools.forEach { add(JsonPrimitive(it)) } }
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
     * A HITL request (`hitl_required.request` or `history.hitl_pending`). The payload may be wrapped in
     * `value` up to three times. Returns null when there is nothing to answer.
     */
    fun hitlRequest(raw: JsonElement?, toolLabels: Map<String, String> = emptyMap()): HitlRequest? {
        var obj = raw.asObject() ?: return null
        repeat(3) {
            if (obj["action_requests"] == null) obj = obj.obj("value") ?: return@repeat
        }
        val allowed = obj.arr("review_configs")?.objects().orEmpty().mapNotNull { config ->
            val name = config.str("action_name") ?: return@mapNotNull null
            name to config.arr("allowed_decisions")?.mapNotNull { it.asString() }.orEmpty().toSet()
        }.toMap()
        val actions = obj.arr("action_requests")?.objects().orEmpty().mapNotNull { action ->
            val name = action.str("name") ?: return@mapNotNull null
            val args = argsObject(action["args"])
            val device = DeviceCatalog.isDevice(name)
            HitlAction(
                name = name,
                label = toolLabels[name] ?: name,
                // Device tools show a preview of their arguments instead (the server's text is for the model).
                description = action.str("description")?.takeIf { it.isNotBlank() && !device },
                details = if (name == ASK_USER_QUESTION || device) emptyList() else keyArgs(args),
                questions = if (name == ASK_USER_QUESTION) questions(args) else null,
                allowedDecisions = allowed[name]?.takeIf { it.isNotEmpty() },
                args = if (device) args ?: JsonObject(emptyMap()) else null,
            )
        }
        if (actions.isEmpty()) return null
        return HitlRequest(obj.idString("pending_id"), actions)
    }

    const val ASK_USER_QUESTION = "ask_user_question"

    /** `args` comes as an object or as a JSON string. */
    private fun argsObject(raw: JsonElement?): JsonObject? = raw.asObject()
        ?: raw.asString()?.let { text -> runCatching { Http.parse(text).asObject() }.getOrNull() }

    private fun questions(args: JsonObject?): List<HitlQuestion> {
        args ?: return emptyList()
        val list = when (val raw = args["questions"]) {
            is JsonArray -> raw.objects()
            is JsonPrimitive -> raw.asString()?.let { text -> runCatching { Http.parse(text).asArray()?.objects() }.getOrNull() }.orEmpty()
            else -> listOf(args)
        }
        return list.mapNotNull { row ->
            val text = (row.str("question") ?: row.str("prompt") ?: row.str("text"))?.trim()?.takeIf { it.isNotEmpty() }
                ?: return@mapNotNull null
            HitlQuestion(
                text = text,
                header = row.str("header")?.trim()?.takeIf { it.isNotEmpty() },
                options = row.arr("options").orEmpty().mapNotNull { option ->
                    when (option) {
                        is JsonObject -> option.str("label")?.takeIf { it.isNotBlank() }?.let {
                            HitlOption(it, option.str("description")?.takeIf { d -> d.isNotBlank() })
                        }
                        else -> option.asString()?.takeIf { it.isNotBlank() }?.let { HitlOption(it, null) }
                    }
                },
                multiSelect = row.bool("multi_select") == true || row.bool("multiSelect") == true,
            )
        }
    }

    private fun keyArgs(args: JsonObject?): List<Pair<String, String>> {
        args ?: return emptyList()
        return listOf(listOf("command", "cmd"), listOf("url"), listOf("path", "file_path"), listOf("query")).mapNotNull { keys ->
            keys.firstNotNullOfOrNull { key ->
                when (val value = args[key]) {
                    is JsonPrimitive -> value.content.takeIf { it.isNotBlank() && value !is JsonNull }?.let { key to it }
                    is JsonArray -> value.mapNotNull { it.asString() }.joinToString(" ").takeIf { it.isNotBlank() }?.let { key to it }
                    else -> null
                }
            }
        }
    }

    /** `POST chat/hitl/resume` body: one decision per action. */
    fun hitlResume(threadId: String, pendingId: String?, decisions: List<HitlDecision>): JsonObject = buildJsonObject {
        put("thread_id", threadId)
        pendingId?.let { put("pending_id", it) }
        putJsonArray("decisions") {
            for (decision in decisions) addJsonObject {
                when (decision) {
                    is HitlDecision.Respond -> {
                        put("type", "respond")
                        put("message", decision.message)
                    }
                    HitlDecision.Approve -> put("type", "approve")
                    is HitlDecision.Reject -> {
                        put("type", "reject")
                        put("message", decision.message)
                    }
                }
            }
        }
    }

    /**
     * Maps chat WebSocket frames to stream events; remembers tool names so results can be labelled.
     * Tools without a `display_name` are named through [toolLabels].
     */
    class FrameMapper(
        private val toolLabels: Map<String, String> = emptyMap(),
        /** The `hitl/resume` SSE stream ends with `{"type":"done"}` instead of `turn.ended`. */
        private val endsOnDone: Boolean = false,
    ) {
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
                "attachment" -> Outcome.Events(listOfNotNull(attachmentFrame(frame)?.let { StreamEvent.Attachment(it) }))
                // A pause for the user is not a failure: the reply ends normally and the card opens.
                "hitl_required" -> Outcome.Events(listOfNotNull(hitlRequest(frame["request"], toolLabels)?.let { StreamEvent.Hitl(it) }))
                "error" -> throw streamError(frame, frame.str("message"))
                "done" -> if (endsOnDone) Outcome.Finished else Outcome.Events(emptyList())
                "turn.ended" -> {
                    if (frame.bool("failed") == true) throw streamError(frame, null)
                    Outcome.Finished
                }
                else -> Outcome.Events(emptyList())
            }
        }

        private inline fun text(frame: JsonObject, event: (String) -> StreamEvent): Outcome =
            Outcome.Events(listOfNotNull(frame.str("content")?.takeIf { it.isNotEmpty() }?.let(event)))
    }

    /** A failed turn; out of Lynxce credits keeps its code so the chat shows the recharge card. */
    fun streamError(frame: JsonObject, message: String?): ApiException {
        val code = frame.str("error_code")
        if (code == ApiException.DAILY_LIMIT) return ApiException(ApiException.Kind.DailyLimit, 429, message, code)
        return if (ApiException.isCreditsRequired(code)) {
            ApiException(ApiException.Kind.Credits, 402, message, code, creditDetails(frame.obj("error_details") ?: frame.obj("details")))
        } else if (code == "insufficient_balance" || message == "octop:stream_errors.insufficient_balance" || message == "The model provider rejected this request due to insufficient balance or quota. Top up or upgrade the plan for this API key, then try again." || message == "模型服务返回余额或额度不足。请为该 API Key 对应的账户充值或升级套餐后再试。") {
            ApiException(ApiException.Kind.Server, 500, code = "insufficient_balance")
        } else {
            ApiException(ApiException.Kind.Server, 500, message, code)
        }
    }

    /** A failed socket handshake: 401 signs out, 402 is out of credits, anything else is the network. */
    fun handshakeError(status: Int?): ApiException = when (status) {
        401 -> ApiException(ApiException.Kind.Unauthorized, 401)
        402 -> ApiException(ApiException.Kind.Credits, 402, code = ApiException.CREDITS_REQUIRED)
        else -> ApiException.network()
    }

    /** `GET /api/usage/summary` over the last 30 days, by Bot or by model. */
    data class UsageSummary(val totalTokens: Long, val modelCalls: Long, val buckets: List<UsageBucket>)

    data class UsageBucket(val key: String, val label: String, val totalTokens: Long)

    fun usage(body: JsonElement): UsageSummary? {
        val obj = body.asObject() ?: return null
        val buckets = obj.arr("buckets")?.objects().orEmpty().mapNotNull { row ->
            val key = row.idString("key")?.takeIf { it.isNotBlank() } ?: return@mapNotNull null
            UsageBucket(key, row.str("label")?.takeIf { it.isNotBlank() } ?: key, row.long("total_tokens") ?: 0L)
        }.filter { it.totalTokens > 0 }.sortedByDescending { it.totalTokens }
        return UsageSummary(obj.long("total_tokens") ?: 0L, obj.long("model_calls") ?: 0L, buckets)
    }

    private val CLOUD_TICKET = Regex("(?!mcrt1\\.)[A-Za-z0-9_-]{1,4096}\\.[A-Za-z0-9_-]{43}")

    /**
     * `POST /api/octop-bot/wallet/recharge` → the checkout to open, or null. Only Lynxce's own recharge page
     * (`https://admin.lynxce.cn/recharge?token=…`, nothing else in the URL) with a ticket expiring within 16 minutes.
     */
    fun cloudCheckoutUrl(data: JsonElement, now: java.time.Instant = java.time.Instant.now()): String? {
        val obj = data.asObject() ?: return null
        val raw = obj.str("url") ?: return null
        val url = raw.toHttpUrlOrNull() ?: return null
        if (url.scheme != "https" || url.host != "admin.lynxce.cn" || url.port != 443) return null
        if ("@" in raw || "#" in raw || url.username.isNotEmpty() || url.password.isNotEmpty() || url.fragment != null) return null
        if (url.encodedPath != "/recharge" || url.querySize == 0 || url.queryParameterName(0) != "token") return null
        if (url.querySize != 1 && !(url.querySize == 2 && url.queryParameterName(1) == "tab" && url.queryParameterValue(1) == "boost")) return null
        val ticket = url.queryParameterValue(0) ?: return null
        if (!CLOUD_TICKET.matches(ticket)) return null
        if (!raw.startsWith("https://admin.lynxce.cn/recharge?token=")) return null
        val expires = obj.str("expires_at")?.let { runCatching { java.time.OffsetDateTime.parse(it).toInstant() }.getOrNull() }
            ?: return null
        val left = java.time.Duration.between(now, expires)
        return raw.takeIf { !left.isNegative && !left.isZero && left <= java.time.Duration.ofMinutes(16) }
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
            requestId = row.str("request_id")?.takeIf { it.isNotBlank() },
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
