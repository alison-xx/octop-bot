package io.github.alisonxx.octopbot.net

import io.github.alisonxx.octopbot.device.DeviceCatalog
import io.github.alisonxx.octopbot.device.DeviceDecisions
import io.github.alisonxx.octopbot.device.DeviceTool
import io.github.alisonxx.octopbot.device.ToolCallAccumulator
import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.ChatMessage
import io.github.alisonxx.octopbot.model.ConversationSummary
import io.github.alisonxx.octopbot.model.HitlAction
import io.github.alisonxx.octopbot.model.HitlDecision
import io.github.alisonxx.octopbot.model.HitlRequest
import io.github.alisonxx.octopbot.model.MessageRole
import io.github.alisonxx.octopbot.model.MessageStatus
import io.github.alisonxx.octopbot.model.ModelOption
import io.github.alisonxx.octopbot.model.StreamEvent
import io.github.alisonxx.octopbot.model.Times
import io.github.alisonxx.octopbot.store.LynxceGrant
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
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import java.util.Base64
import java.util.UUID

/** Pure Lynxce wire mapping (no I/O), shared by [LynxceBackend] and unit tests. */
object LynxceProtocol {
    const val ORIGIN = "https://api.lynxce.cn"

    /** Headers on every call to Lynxce, sign-in and sign-up included. */
    fun headers(bearer: String?): Map<String, String> = buildMap {
        // 'web' is Lynxce's multi-session channel; signing in here never signs other devices out.
        put("X-Lynxce-Client", "web")
        // Lynxce serves Octop Bot only the Tencent Cloud TokenHub models and records sign-ups made here.
        put("X-Lynxce-App", "octopbot")
        // An account created here shows Octop Bot as its source (Lynxce admin, sign-up notice);
        // Lynxce reads it only when the account is created.
        put("X-Lynxce-Signup-Site", "octop-bot")
        bearer?.let { put("Authorization", "Bearer $it") }
    }
    /** Lynxce's Octop Bot line: every model it offers Octop Bot is named `tencent/…`. */
    const val MODEL_PREFIX = "tencent/"
    /** Same prefix the desktop client uses, so desktop and phone list each other's conversations. */
    const val SESSION_PREFIX = "octop-bot-v1-"
    private const val ROLE_MARKER = "\n\n[Octop Bot role/v1] "

    fun newSessionId(): String = SESSION_PREFIX + UUID.randomUUID().toString().lowercase()

    /** Lynxce wraps results as `{code: 0, data}`; anything else is a failure. */
    fun unwrap(status: Int, body: String): JsonElement {
        if (status !in 200..299) throw ApiException.fromBody(status, body)
        val envelope = Http.parse(body) as? JsonObject ?: throw ApiException.badResponse()
        val code = envelope.long("code")
            ?: throw if (ApiException.isDailyLimit(body)) ApiException.fromBody(429, body) else ApiException.badResponse()
        if (code != 0L) {
            if (ApiException.isDailyLimit(body)) throw ApiException.fromBody(429, body)
            val mapped = when (code) { 401L -> 401; 402L -> 402; else -> 400 }
            throw ApiException.from(mapped, envelope.str("message"))
        }
        return envelope["data"] ?: JsonNull
    }

    /** One OpenAI-style chunk → text / thinking deltas; `delta.tool_calls` pieces go to [toolCalls]. Error chunks throw. */
    fun parseChunk(data: String, toolCalls: ToolCallAccumulator? = null): List<StreamEvent> {
        val obj = Http.parse(data) as? JsonObject ?: return emptyList()
        obj["error"]?.takeIf { it !is JsonNull }?.let { error ->
            val message = (error as? JsonObject)?.str("message") ?: error.asString()
            if (ApiException.isDailyLimit(error.toString())) {
                throw ApiException(ApiException.Kind.DailyLimit, 429, message, ApiException.DAILY_LIMIT)
            }
            if (outOfCredits(error as? JsonObject, message)) {
                val tags = error as? JsonObject
                val code = listOf(tags?.str("code"), tags?.str("type")).firstOrNull { it == "insufficient_balance" } ?: tags?.str("code")
                throw ApiException(ApiException.Kind.Credits, 402, message, code)
            }
            throw ApiException(ApiException.Kind.Server, 500, message)
        }
        val delta = obj.arr("choices")?.firstOrNull().asObject()?.obj("delta") ?: return emptyList()
        delta.arr("tool_calls")?.let { toolCalls?.add(it) }
        return buildList {
            (delta.str("reasoning_content") ?: delta.str("reasoning"))?.takeIf { it.isNotEmpty() }?.let { add(StreamEvent.Thinking(it)) }
            delta.str("content")?.takeIf { it.isNotEmpty() }?.let { add(StreamEvent.Text(it)) }
        }
    }

    /** A mid-stream gateway error that means the wallet ran out (402 / insufficient credits or quota). */
    private fun outOfCredits(error: JsonObject?, message: String?): Boolean {
        val code = error?.idString("code")?.lowercase().orEmpty()
        val type = error?.str("type")?.lowercase().orEmpty()
        val text = message?.lowercase().orEmpty()
        return code == "402" || error?.long("status") == 402L ||
            listOf(code, type).any { it.startsWith("insufficient_") } ||
            "insufficient credit" in text || "insufficient balance" in text || "insufficient_quota" in text
    }

    /**
     * The first request of a turn. With device [tools] on (PROTOCOL §C) it adds `tools`, `tool_choice` and a
     * system line with the phone's time ([now]).
     */
    fun chatBody(
        text: String,
        images: List<ByteArray>,
        bot: BotProfile,
        history: List<ChatMessage>,
        sessionId: String,
        model: String?,
        turnId: String = UUID.randomUUID().toString().lowercase(),
        tools: List<DeviceTool> = emptyList(),
        now: ZonedDateTime = ZonedDateTime.now(),
    ): JsonObject = buildJsonObject {
        putJsonArray("messages") {
            val system = listOfNotNull(
                bot.systemPrompt?.takeIf { it.isNotBlank() },
                if (tools.isEmpty()) null else nowLine(now),
            )
            if (system.isNotEmpty()) addJsonObject { put("role", "system"); put("content", system.joinToString("\n\n")) }
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
        // A choice saved before Lynxce moved Octop Bot to its Tencent line falls back to the default.
        model?.takeIf { it.startsWith(MODEL_PREFIX) }?.let { put("model", it) }
        putJsonObject("metadata") {
            put("client", "octop-bot-android")
            put("turnId", turnId)
        }
        if (tools.isNotEmpty()) {
            put("tools", DeviceCatalog.openAiTools(tools))
            put("tool_choice", "auto")
        }
    }

    /** `Now: 2026-11-24T15:00:00+08:00 (Asia/Shanghai).` */
    fun nowLine(now: ZonedDateTime): String =
        "Now: ${now.truncatedTo(ChronoUnit.SECONDS).format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)} (${now.zone.id})."

    /**
     * A later request of the tool loop: [first] plus the loop's assistant/tool messages; without `tools` and
     * `tool_choice` when [withTools] is false (the gateway refused them).
     */
    fun roundBody(first: JsonObject, loop: List<JsonObject>, withTools: Boolean): JsonObject = JsonObject(
        first.toMutableMap().apply {
            put("messages", JsonArray(first.arr("messages").orEmpty() + loop))
            if (!withTools) {
                remove("tools")
                remove("tool_choice")
            }
        },
    )

    /** The assistant turn that asked for tools: its text so far (or null) and the calls. */
    fun assistantToolCalls(text: String, calls: List<ToolCallAccumulator.Call>): JsonObject = buildJsonObject {
        put("role", "assistant")
        put("content", text.takeIf { it.isNotEmpty() }?.let(::JsonPrimitive) ?: JsonNull)
        putJsonArray("tool_calls") {
            for (call in calls) addJsonObject {
                put("id", call.id)
                put("type", "function")
                putJsonObject("function") {
                    put("name", call.name)
                    put("arguments", call.arguments.ifBlank { "{}" })
                }
            }
        }
    }

    /** The tool result of a declined device write; text the user typed instead goes along. */
    fun declined(message: String?): JsonObject = buildJsonObject {
        put("error", DeviceDecisions.DECLINED)
        message?.takeIf { it.isNotBlank() && it != DeviceDecisions.DECLINED && it != HitlDecision.REJECTED }?.let { put("user_message", it) }
    }

    /** Device writes waiting for the user, shaped like a server HITL pause so the same card answers them. */
    fun devicePause(pendingId: String, writes: List<ToolCallAccumulator.Call>, label: (String) -> String): HitlRequest =
        HitlRequest(
            pendingId,
            writes.map { call ->
                HitlAction(
                    name = call.name,
                    label = label(call.name),
                    description = null,
                    details = emptyList(),
                    questions = null,
                    allowedDecisions = setOf("respond", "reject"),
                    args = DeviceCatalog.args(call.arguments),
                )
            },
        )

    fun toolResult(callId: String, content: String): JsonObject = buildJsonObject {
        put("role", "tool")
        put("tool_call_id", callId)
        put("content", content)
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

    /**
     * The wallet balance from `/api/user/quota`, the figure a recharge adds to. (`effectiveCreditsRemaining`
     * can instead be an enterprise member's monthly allowance, so it is not shown next to "Recharge".)
     */
    fun balance(data: JsonElement): Double? = data.asObject()?.double("creditsRemaining")

    /**
     * Credits as every client shows them: grouped integers ("4,454,029"), and two decimals only below 1,000
     * when there is a fraction ("12.50"). Never rounds up.
     */
    fun formatCredits(value: Double): String {
        val symbols = java.text.DecimalFormatSymbols(java.util.Locale.US)
        val cents = java.math.BigDecimal.valueOf(value).setScale(2, java.math.RoundingMode.DOWN)
        val fractional = cents.remainder(java.math.BigDecimal.ONE).signum() != 0
        val pattern = if (cents.abs() < java.math.BigDecimal(1000) && fractional) "#,##0.00" else "#,##0"
        return java.text.DecimalFormat(pattern, symbols).apply { roundingMode = java.math.RoundingMode.DOWN }.format(cents)
    }

    /** Below this the balance shows in the warning colour and chat offers a recharge banner. */
    const val LOW_BALANCE = 1000.0

    /** Lynxce's recharge site, for signing in there by hand (the out-of-credits card links it). */
    const val RECHARGE_SITE = "https://admin.lynxce.cn/recharge"
    /** Lynxce's account centre, where the daily cap for Octop Bot can be raised. */
    const val ACCOUNT_CENTRE = "https://admin.lynxce.cn"
    const val CHECKOUT_PORTAL = "https://admin.lynxce.cn/recharge?token="
    private val CHECKOUT_TICKET = Regex("(?!mcrt1\\.)[A-Za-z0-9_-]{1,4096}\\.[A-Za-z0-9_-]{43}")

    /**
     * The hosted checkout Lynxce minted for this account (`POST /api/billing/recharge/checkout-link`).
     * Only the official recharge page with a well-formed 15-minute ticket is opened, as on the desktop.
     */
    fun checkoutUrl(data: JsonElement, now: java.time.Instant = java.time.Instant.now()): String? {
        val obj = data.asObject() ?: return null
        val url = obj.str("url") ?: return null
        if (!url.startsWith(CHECKOUT_PORTAL)) return null
        val ticket = url.removePrefix(CHECKOUT_PORTAL).removeSuffix("&tab=boost")
        if (!CHECKOUT_TICKET.matches(ticket) || (obj.str("token") ?: ticket) != ticket) return null
        val expires = obj.str("expiresAt")?.let { runCatching { java.time.Instant.parse(it) }.getOrNull() } ?: return null
        val left = java.time.Duration.between(now, expires)
        return url.takeIf { !left.isNegative && !left.isZero && left <= java.time.Duration.ofMinutes(16) }
    }

    /** Add the top-up tab only after validating the checkout URL. */
    fun boostTab(url: String): String {
        val parsed = url.toHttpUrlOrNull() ?: return url
        if (parsed.queryParameterNames.contains("tab")) return url
        return "$url${if (parsed.querySize > 0) "&" else "?"}tab=boost"
    }

    /** App Store-style self-service deletion; Lynxce asks for this exact confirmation text. */
    fun deletionBody() = buildJsonObject { put("confirm", "注销账号") }

    fun loginBody(account: String, password: String) = buildJsonObject {
        put("account", account)
        put("password", password)
    }

    /** Where a verification code goes: an email when the text has "@", otherwise a phone (Lynxce normalizes numbers). */
    sealed interface Target {
        val value: String

        data class Phone(override val value: String) : Target
        data class Email(override val value: String) : Target

        companion object {
            fun of(typed: String): Target? {
                val value = typed.trim()
                return when {
                    value.isEmpty() -> null
                    "@" in value -> Email(value)
                    else -> Phone(value)
                }
            }
        }
    }

    const val CODE_LENGTH = 6

    fun isValidCode(code: String) = code.length == CODE_LENGTH && code.all { it in '0'..'9' }

    fun codeRequestPath(target: Target) = when (target) {
        is Target.Phone -> "/api/auth/phone-code"
        is Target.Email -> "/api/auth/email-code"
    }

    /** The email follows the app language; the response may carry a dev code that must never be shown. */
    fun codeRequestBody(target: Target, chinese: Boolean) = buildJsonObject {
        when (target) {
            is Target.Phone -> put("phone", target.value)
            is Target.Email -> {
                put("email", target.value)
                put("locale", if (chinese) "zh-CN" else "en")
            }
        }
    }

    fun codeLoginPath(target: Target) = when (target) {
        is Target.Phone -> "/api/auth/phone-login"
        is Target.Email -> "/api/auth/email-login"
    }

    fun codeLoginBody(target: Target, code: String) = buildJsonObject {
        put(if (target is Target.Phone) "phone" else "email", target.value)
        put("code", code)
    }

    /** Verification-code failures that get their own wording; others use the server's message or generic text. */
    enum class CodeFailure { InvalidCode, TooFrequent }

    fun codeFailure(error: Throwable): CodeFailure? = when ((error as? ApiException)?.status) {
        401 -> CodeFailure.InvalidCode
        429 -> CodeFailure.TooFrequent
        else -> null
    }

    /** The account from a password or code sign-in (`{accessToken, refreshToken, user}`). */
    fun grant(data: JsonElement): LynxceGrant {
        val body = data.asObject() ?: throw ApiException.badResponse()
        val user = body.obj("user")
        return LynxceGrant(
            accountId = user?.idString("id") ?: throw ApiException.badResponse(),
            displayName = user.str("displayName")?.takeIf { it.isNotBlank() },
            accessToken = body.str("accessToken") ?: throw ApiException.badResponse(),
            refreshToken = body.str("refreshToken") ?: throw ApiException.badResponse(),
            signupExpiryDay = signupExpiryDayUTC(body),
        )
    }

    fun refreshBody(refreshToken: String) = buildJsonObject { put("refreshToken", refreshToken) }

    fun speechBody(text: String) = buildJsonObject {
        put("text", text.take(600))
        put("format", "mp3")
    }
}
