package io.github.alisonxx.octopbot.net

import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.ChatMessage
import io.github.alisonxx.octopbot.model.ConversationSummary
import io.github.alisonxx.octopbot.model.MessageRole
import io.github.alisonxx.octopbot.model.MessageStatus
import io.github.alisonxx.octopbot.model.ModelOption
import io.github.alisonxx.octopbot.model.StreamEvent
import io.github.alisonxx.octopbot.model.Times
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.addJsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.putJsonObject
import java.util.Base64
import java.util.UUID

/** Pure Lynxce wire mapping (no I/O), shared by [LynxceBackend] and unit tests. */
object LynxceProtocol {
    const val ORIGIN = "https://api.lynxce.cn"
    /** Same prefix the desktop client uses, so desktop and phone list each other's conversations. */
    const val SESSION_PREFIX = "octop-bot-v1-"
    private const val ROLE_MARKER = "\n\n[Octop Bot role/v1] "

    fun newSessionId(): String = SESSION_PREFIX + UUID.randomUUID().toString().lowercase()

    /** Lynxce wraps results as `{code: 0, data}`; anything else is a failure. */
    fun unwrap(status: Int, body: String): JsonElement {
        if (status !in 200..299) throw ApiException.from(status, Http.errorMessage(body))
        val envelope = Http.parse(body) as? JsonObject ?: throw ApiException.badResponse()
        val code = envelope.long("code") ?: throw ApiException.badResponse()
        if (code != 0L) {
            val mapped = when (code) { 401L -> 401; 402L -> 402; else -> 400 }
            throw ApiException.from(mapped, envelope.str("message"))
        }
        return envelope["data"] ?: JsonNull
    }

    /** One OpenAI-style chunk → text / thinking deltas. Error chunks throw. */
    fun parseChunk(data: String): List<StreamEvent> {
        val obj = Http.parse(data) as? JsonObject ?: return emptyList()
        obj["error"]?.takeIf { it !is JsonNull }?.let { error ->
            val message = (error as? JsonObject)?.str("message") ?: error.asString()
            throw ApiException(ApiException.Kind.Server, 500, message)
        }
        val delta = obj.arr("choices")?.firstOrNull().asObject()?.obj("delta") ?: return emptyList()
        return buildList {
            (delta.str("reasoning_content") ?: delta.str("reasoning"))?.takeIf { it.isNotEmpty() }?.let { add(StreamEvent.Thinking(it)) }
            delta.str("content")?.takeIf { it.isNotEmpty() }?.let { add(StreamEvent.Text(it)) }
        }
    }

    fun chatBody(
        text: String,
        images: List<ByteArray>,
        bot: BotProfile,
        history: List<ChatMessage>,
        sessionId: String,
        model: String?,
        turnId: String = UUID.randomUUID().toString().lowercase(),
    ): JsonObject = buildJsonObject {
        putJsonArray("messages") {
            bot.systemPrompt?.takeIf { it.isNotBlank() }?.let { prompt ->
                addJsonObject { put("role", "system"); put("content", prompt) }
            }
            history.filter { it.status == MessageStatus.Done && it.text.isNotEmpty() && it.role != MessageRole.Note }.takeLast(20).forEach { message ->
                addJsonObject {
                    put("role", if (message.role == MessageRole.User) "user" else "assistant")
                    put("content", message.text)
                }
            }
            addJsonObject {
                put("role", "user")
                if (images.isEmpty()) {
                    put("content", text)
                } else {
                    putJsonArray("content") {
                        addJsonObject { put("type", "text"); put("text", text) }
                        for (image in images) addJsonObject {
                            put("type", "image_url")
                            putJsonObject("image_url") {
                                put("url", "data:image/jpeg;base64," + Base64.getEncoder().encodeToString(image))
                            }
                        }
                    }
                }
            }
        }
        put("stream", true)
        putJsonObject("stream_options") { put("include_usage", true) }
        put("sessionId", sessionId)
        model?.let { put("model", it) }
        putJsonObject("metadata") {
            put("client", "octop-bot-android")
            put("turnId", turnId)
        }
    }

    /** The body for `POST /web-chat-sessions/{id}/items` after a turn finishes. */
    fun syncBody(user: String, startedAt: Long, answer: String, thinking: String, model: String?, now: Long): JsonObject {
        val trimmed = answer.trim()
        val title = user.trim().take(40).ifEmpty { "Octop Bot" }
        return buildJsonObject {
            put("title", title)
            put("model", model ?: "auto")
            putJsonArray("items") {
                addJsonObject {
                    put("role", "user")
                    put("content", user.take(20_000))
                    put("createdAt", Times.iso(startedAt))
                }
                if (trimmed.isNotEmpty()) addJsonObject {
                    put("role", "assistant")
                    put("content", trimmed.take(40_000))
                    put("createdAt", Times.iso(now))
                    if (thinking.isNotEmpty()) put("thinking", thinking.take(20_000))
                    model?.let { put("model", it) }
                }
            }
        }
    }

    /** The desktop Bot tags the user's first message with a role block; hide it on the phone too. */
    fun stripRole(text: String): String {
        val index = text.lastIndexOf(ROLE_MARKER)
        return if (index >= 0) text.substring(0, index) else text
    }

    /** Sessions with our prefix that belong to [botId]; unknown ids belong to Chief. */
    fun conversations(data: JsonElement, owners: Map<String, String>, botId: String, chiefId: String): List<ConversationSummary> =
        data.asObject()?.arr("items")?.objects().orEmpty().mapNotNull { item ->
            val id = item.str("id")?.takeIf { it.startsWith(SESSION_PREFIX) } ?: return@mapNotNull null
            val owner = owners[id] ?: chiefId
            if (owner != botId) return@mapNotNull null
            ConversationSummary(
                id = id,
                title = item.str("title").orEmpty().lineSequence().first(),
                updatedAt = Times.parseIso(item.str("updatedAt")),
                botId = owner,
            )
        }

    fun messages(data: JsonElement): List<ChatMessage> =
        data.asObject()?.arr("items")?.objects().orEmpty().mapNotNull { item ->
            val role = when (item.str("role")) {
                "user" -> MessageRole.User
                "assistant" -> MessageRole.Assistant
                else -> return@mapNotNull null
            }
            ChatMessage(
                role = role,
                text = stripRole(item.str("content").orEmpty()),
                thinking = item.str("thinking").orEmpty(),
                createdAt = Times.parseIso(item.str("createdAt")) ?: System.currentTimeMillis(),
                status = if (item.str("status") == "failed") MessageStatus.Failed(null) else MessageStatus.Done,
            )
        }

    fun models(data: JsonElement): List<ModelOption> {
        val rows = (data as? JsonArray) ?: data.asObject()?.arr("items") ?: data.asObject()?.arr("models") ?: JsonArray(emptyList())
        return rows.objects().mapNotNull { row ->
            val id = row.str("modelId") ?: return@mapNotNull null
            ModelOption(id, row.str("modelName") ?: id, row.bool("supportsImage") ?: false)
        }
    }

    /** The first numeric of `balance`/`credits`/`remaining`/`points`. */
    fun balance(data: JsonElement): String? {
        val obj = data.asObject() ?: return null
        for (key in listOf("balance", "credits", "remaining", "points")) {
            val value = obj[key] as? JsonPrimitive ?: continue
            if (value is JsonNull) continue
            if (!value.isString || value.content.toDoubleOrNull() != null) return value.content
        }
        return null
    }

    fun loginBody(account: String, password: String) = buildJsonObject {
        put("account", account)
        put("password", password)
    }

    fun refreshBody(refreshToken: String) = buildJsonObject { put("refreshToken", refreshToken) }

    fun speechBody(text: String) = buildJsonObject {
        put("text", text.take(600))
        put("format", "mp3")
    }
}
