package io.github.alisonxx.octopbot.net

import io.github.alisonxx.octopbot.device.DeviceCatalog
import io.github.alisonxx.octopbot.device.DeviceToolbox
import io.github.alisonxx.octopbot.device.ToolCallAccumulator
import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.ChatMessage
import io.github.alisonxx.octopbot.model.ConversationSummary
import io.github.alisonxx.octopbot.model.HitlDecision
import io.github.alisonxx.octopbot.model.ImageAttachment
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.model.ModelOption
import io.github.alisonxx.octopbot.model.StreamEvent
import io.github.alisonxx.octopbot.model.VoiceSupport
import io.github.alisonxx.octopbot.store.AppStore
import io.github.alisonxx.octopbot.store.LocalBots
import io.github.alisonxx.octopbot.store.LynxceGrant
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.ProducerScope
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.channelFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import okhttp3.Call
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.RequestBody
import okhttp3.Response
import java.util.Base64
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/**
 * Signed in with a personal Lynxce (灵策智算) account: chat goes straight to the Lynxce model gateway and
 * conversations sync through Lynxce web-chat sessions, so they also appear in Octop Bot on the desktop.
 */
class LynxceBackend(
    private var grant: LynxceGrant,
    private val store: AppStore,
    private val localBots: LocalBots,
) : ChatBackend, CreditAccount {
    override val definesBotsLocally = true
    override val supportsGroups = false
    override val accountName get() = grant.displayName ?: grant.accountId
    override val connectionLabel = "api.lynxce.cn"

    private val refreshLock = Mutex()
    private val background = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val running = ConcurrentHashMap<String, RunningStream>()
    private val streamClient = Http.client.withReadTimeout(300)

    private class RunningStream(val call: Call) {
        @Volatile var stopped = false
    }

    companion object {
        /** Requests per turn in the device tool loop. */
        private const val MAX_ROUNDS = 6

        private fun headers(bearer: String?) = buildMap {
            // 'web' is Lynxce's multi-session channel; signing in here never signs other devices out.
            put("X-Lynxce-Client", "web")
            bearer?.let { put("Authorization", "Bearer $it") }
        }

        private fun url(path: String, query: Map<String, String> = emptyMap()): String =
            (LynxceProtocol.ORIGIN + path).toHttpUrl().newBuilder().apply {
                query.forEach { (key, value) -> addQueryParameter(key, value) }
            }.build().toString()

        private suspend fun call(method: String, path: String, bearer: String?, query: Map<String, String>, body: RequestBody?): JsonElement {
            val request = Http.request(url(path, query), headers(bearer)).method(method, body).build()
            return Http.client.newCall(request).await().use { response ->
                val text = withContext(Dispatchers.IO) { response.body.string() }
                LynxceProtocol.unwrap(response.code, text)
            }
        }

        suspend fun signIn(account: String, password: String, store: AppStore, localBots: LocalBots): LynxceBackend =
            enter(call("POST", "/api/auth/password-login", null, emptyMap(), Http.body(LynxceProtocol.loginBody(account, password))), store, localBots)

        /** Send a sign-in code by SMS or email. The response's dev code is ignored on purpose. */
        suspend fun requestCode(target: LynxceProtocol.Target) {
            val body = LynxceProtocol.codeRequestBody(target, Http.isChinese())
            call("POST", LynxceProtocol.codeRequestPath(target), null, emptyMap(), Http.body(body))
        }

        /** Sign in (or sign up: Lynxce creates new accounts automatically) with a 6-digit code. */
        suspend fun signIn(target: LynxceProtocol.Target, code: String, store: AppStore, localBots: LocalBots): LynxceBackend {
            require(LynxceProtocol.isValidCode(code))
            val body = LynxceProtocol.codeLoginBody(target, code)
            return enter(call("POST", LynxceProtocol.codeLoginPath(target), null, emptyMap(), Http.body(body)), store, localBots)
        }

        private suspend fun enter(data: JsonElement, store: AppStore, localBots: LocalBots): LynxceBackend {
            val grant = LynxceProtocol.grant(data)
            store.setLynxceGrant(grant)
            return LynxceBackend(grant, store, localBots)
        }
    }

    // Transport

    /** Authenticated call that rotates the access token once on 401. */
    private suspend fun call(
        method: String,
        path: String,
        query: Map<String, String> = emptyMap(),
        body: () -> RequestBody? = { null },
    ): JsonElement = try {
        call(method, path, grant.accessToken, query, body())
    } catch (error: ApiException) {
        if (error.kind != ApiException.Kind.Unauthorized) throw error
        call(method, path, refreshed(grant.accessToken).accessToken, query, body())
    }

    /** Refresh once even when several calls hit 401 together. */
    private suspend fun refreshed(stale: String): LynxceGrant = refreshLock.withLock {
        if (grant.accessToken != stale) return grant
        val data = try {
            call("POST", "/api/auth/refresh", null, emptyMap(), Http.body(LynxceProtocol.refreshBody(grant.refreshToken)))
        } catch (_: ApiException) {
            throw ApiException(ApiException.Kind.Unauthorized, 401)
        }
        val body = data.asObject()
        val access = body?.str("accessToken") ?: throw ApiException(ApiException.Kind.Unauthorized, 401)
        grant = grant.copy(accessToken = access, refreshToken = body.str("refreshToken") ?: grant.refreshToken)
        store.setLynxceGrant(grant)
        grant
    }

    private fun sessionPath(id: String) = "/api/user/web-chat-sessions/" + java.net.URLEncoder.encode(id, "UTF-8")

    // Bots and conversations

    override suspend fun bots() = localBots.all()

    override suspend fun conversations(bot: BotProfile): List<ConversationSummary> {
        val data = call("GET", "/api/user/web-chat-sessions", mapOf("limit" to "50"))
        return LynxceProtocol.conversations(data, store.sessionBots(), bot.id, LocalBots.CHIEF_ID)
    }

    override suspend fun messages(conversation: ConversationSummary, bot: BotProfile): List<ChatMessage> =
        LynxceProtocol.messages(call("GET", sessionPath(conversation.id)))

    override suspend fun deleteConversation(conversation: ConversationSummary, bot: BotProfile) {
        call("DELETE", sessionPath(conversation.id))
        store.updateSessionBots { it.remove(conversation.id) }
    }

    override suspend fun models(): List<ModelOption> = LynxceProtocol.models(call("GET", "/api/models/available"))

    override suspend fun setLook(bot: BotProfile, look: Look) = localBots.save(bot.copy(look = look))

    // Chat

    /** One turn of the local tool loop (PROTOCOL §C): the first request, the loop's messages and what gets synced. */
    private class Turn(
        val sessionId: String,
        val user: String,
        val startedAt: Long,
        val model: String?,
        val first: JsonObject,
        val device: DeviceToolbox,
        /** Names of the device tools offered in [first]. */
        val offered: Set<String>,
    ) {
        val loop = mutableListOf<JsonObject>()
        var rounds = 0
        var withTools = offered.isNotEmpty()
        /** The visible answer across rounds and pauses; synced when the turn ends. */
        val answer = StringBuilder()
        val thinking = StringBuilder()
    }

    /** Device writes waiting for the approval card: that round's calls and the read results already known. */
    private class Pause(
        val turn: Turn,
        val calls: List<ToolCallAccumulator.Call>,
        val results: Map<String, String>,
        val writes: List<ToolCallAccumulator.Call>,
    )

    private val pauses = ConcurrentHashMap<String, Pause>()

    override fun send(
        text: String,
        images: List<ImageAttachment>,
        bot: BotProfile,
        conversation: String?,
        history: List<ChatMessage>,
        model: String?,
        device: DeviceToolbox,
    ): Flow<StreamEvent> = channelFlow {
        val sessionId = conversation ?: LynxceProtocol.newSessionId()
        val startedAt = System.currentTimeMillis()
        if (conversation == null) {
            store.updateSessionBots { it[sessionId] = bot.id }
            send(StreamEvent.Conversation(sessionId))
        }
        val tools = device.offered()
        val body = LynxceProtocol.chatBody(text, images.map { it.jpeg }, bot, history, sessionId, model, tools = tools)
        drive(Turn(sessionId, text, startedAt, model, body, device, tools.map { it.name }.toSet()))
    }

    /** The approval card answered a device write: finish that round's tool results and continue the loop. */
    override fun resumeHitl(
        bot: BotProfile,
        conversation: String,
        pendingId: String?,
        decisions: List<HitlDecision>,
    ): Flow<StreamEvent> = channelFlow {
        val pause = pendingId?.let(pauses::remove) ?: return@channelFlow
        val turn = pause.turn
        val results = pause.results.toMutableMap()
        pause.writes.forEachIndexed { index, call ->
            results[call.id] = when (val decision = decisions.getOrNull(index)) {
                is HitlDecision.Respond -> decision.message
                HitlDecision.Approve -> turn.device.run(call.name, DeviceCatalog.args(call.arguments)).toString()
                is HitlDecision.Reject -> LynxceProtocol.declined(decision.message).toString()
                null -> LynxceProtocol.declined(null).toString()
            }
        }
        pause.calls.forEach { turn.loop += LynxceProtocol.toolResult(it.id, results[it.id] ?: LynxceProtocol.declined(null).toString()) }
        drive(turn)
    }

    /**
     * Run the loop on the IO dispatcher: request, run reads, request again (at most [MAX_ROUNDS]); a device write
     * pauses it with [StreamEvent.Hitl]. Closing the flow cancels the request in flight.
     */
    private suspend fun ProducerScope<StreamEvent>.drive(turn: Turn) {
        val worker = launch(Dispatchers.IO) {
            var stopped = false
            var paused = false
            var shown = false
            val failure = runCatching {
                while (true) {
                    turn.rounds++
                    val calls = ToolCallAccumulator()
                    val round = StringBuilder()
                    if (!request(turn, calls) { event ->
                            if (event is StreamEvent.Text) {
                                // Text of a later round starts a new paragraph.
                                if (round.isEmpty() && shown) {
                                    send(StreamEvent.Text("\n\n"))
                                    turn.answer.append("\n\n")
                                }
                                round.append(event.delta)
                                turn.answer.append(event.delta)
                                shown = true
                            }
                            if (event is StreamEvent.Thinking) turn.thinking.append(event.delta)
                            send(event)
                        }
                    ) {
                        stopped = true
                        break
                    }
                    val asked = calls.calls()
                    if (asked.isEmpty() || turn.rounds >= MAX_ROUNDS) break
                    turn.loop += LynxceProtocol.assistantToolCalls(round.toString(), asked)
                    val writes = asked.filter { it.name in turn.offered && turn.device.tool(it.name)?.writes == true }
                    val results = mutableMapOf<String, String>()
                    for (call in asked - writes.toSet()) {
                        val label = turn.device.label(call.name)
                        send(StreamEvent.Tool(call.id, label, done = false))
                        results[call.id] = if (call.name in turn.offered) {
                            turn.device.run(call.name, DeviceCatalog.args(call.arguments)).toString()
                        } else {
                            DeviceCatalog.error("${call.name} is not available.").toString()
                        }
                        send(StreamEvent.Tool(call.id, label, done = true))
                    }
                    if (writes.isNotEmpty()) {
                        val pendingId = UUID.randomUUID().toString()
                        pauses[pendingId] = Pause(turn, asked, results, writes)
                        writes.forEach { send(StreamEvent.Tool(it.id, turn.device.label(it.name), done = false)) }
                        send(StreamEvent.Hitl(LynxceProtocol.devicePause(pendingId, writes, turn.device::label)))
                        paused = true
                        break
                    }
                    asked.forEach { turn.loop += LynxceProtocol.toolResult(it.id, results.getValue(it.id)) }
                }
            }.exceptionOrNull()
            running.remove(turn.sessionId)
            // Only the user's text and the answer are saved; a paused turn is saved when it ends.
            if (!paused) sync(turn.sessionId, turn.user, turn.startedAt, turn.answer.toString(), turn.thinking.toString(), turn.model)
            close(failure?.takeUnless { stopped })
        }
        awaitClose {
            if (worker.isActive) running[turn.sessionId]?.call?.cancel()
        }
    }

    /**
     * One streamed request of [turn]; tool-call pieces go to [calls], deltas to [onEvent]. Refreshes the token once
     * on 401 and drops `tools` once on 400. Returns false when the user stopped it.
     */
    private suspend fun request(turn: Turn, calls: ToolCallAccumulator, onEvent: suspend (StreamEvent) -> Unit): Boolean {
        fun open(token: String): RunningStream = RunningStream(
            streamClient.newCall(
                Http.request(url("/api/proxy/v1/chat/completions"), headers(token))
                    .header("Accept", "text/event-stream")
                    .post(Http.body(LynxceProtocol.roundBody(turn.first, turn.loop, turn.withTools)))
                    .build(),
            ),
        )

        var stream = open(grant.accessToken)
        // Stopped before the reply started: end quietly instead of reporting the cancelled call.
        suspend fun connect(): Response? = try {
            running[turn.sessionId] = stream
            stream.call.await()
        } catch (error: ApiException) {
            if (stream.stopped) null else throw error
        }
        var response = connect() ?: return false
        if (response.code == 401) {
            response.close()
            stream = open(refreshed(grant.accessToken).accessToken)
            response = connect() ?: return false
        }
        if (response.code == 400 && turn.withTools) {
            // The gateway refused function calling: answer without tools.
            response.close()
            turn.withTools = false
            stream = open(grant.accessToken)
            response = connect() ?: return false
        }
        response.use {
            if (!it.isSuccessful) throw ApiException.from(it.code, Http.errorMessage(it.body.string()))
            var completed = false
            try {
                it.body.source().forEachSseEvent { event ->
                    if (event.data == "[DONE]") {
                        completed = true
                        return@forEachSseEvent false
                    }
                    for (parsed in LynxceProtocol.parseChunk(event.data, calls)) onEvent(parsed)
                    true
                }
            } catch (error: java.io.IOException) {
                if (!stream.stopped) throw error
            }
            if (stream.stopped) return false
            // A stream that ends without [DONE] is an interrupted reply.
            if (!completed) throw ApiException.network()
        }
        return true
    }

    /** Append the finished turn to the synced Lynxce session (idempotent on the server). */
    private fun sync(sessionId: String, user: String, startedAt: Long, answer: String, thinking: String, model: String?) {
        val body = LynxceProtocol.syncBody(user, startedAt, answer, thinking, model, System.currentTimeMillis())
        background.launch {
            runCatching { call("POST", sessionPath(sessionId) + "/items") { Http.body(body) } }
        }
    }

    override suspend fun stop(conversation: String, bot: BotProfile) {
        running[conversation]?.let {
            it.stopped = true
            it.call.cancel()
        }
    }

    // Voice and account

    override suspend fun voiceSupport() = VoiceSupport(stt = true, tts = true)

    override suspend fun transcribe(audio: ByteArray): String {
        val data = call("POST", "/api/asr/recognize") {
            Http.form(
                listOf(
                    // Lynxce reads langType before the file.
                    FormPart.Field("langType", if (Http.isChinese()) "zh" else "en"),
                    FormPart.File("file", audio, "voice.m4a", "audio/mp4"),
                ),
            )
        }
        return data.asObject()?.str("text").orEmpty()
    }

    override suspend fun speech(text: String): ByteArray {
        val data = call("POST", "/api/tts/synthesize") { Http.body(LynxceProtocol.speechBody(text)) }
        val encoded = data.asObject()?.str("audioBase64") ?: throw ApiException.badResponse()
        return Base64.getDecoder().decode(encoded)
    }

    override suspend fun balance(): String? =
        runCatching { LynxceProtocol.balance(call("GET", "/api/user/quota")) }.getOrNull()

    /** A signed-in link to Lynxce's recharge page for this account, valid for 15 minutes. */
    override suspend fun checkoutUrl(): String =
        LynxceProtocol.checkoutUrl(call("POST", "/api/billing/recharge/checkout-link") { Http.body(buildJsonObject {}) })
            ?: throw ApiException.badResponse()

    /** Ask Lynxce to delete this account; it is signed out everywhere and erased after a cooling-off period. */
    override suspend fun requestDeletion() {
        call("POST", "/api/user/account/deletion-request") { Http.body(LynxceProtocol.deletionBody()) }
    }

    override suspend fun signOut() {
        running.values.forEach { it.call.cancel() }
        runCatching { call("POST", "/api/auth/logout", grant.accessToken, emptyMap(), Http.body(buildJsonObject {})) }
        background.cancel()
        store.setLynxceGrant(null)
    }
}
