package io.github.alisonxx.octopbot.net

import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.ChatMessage
import io.github.alisonxx.octopbot.model.ConversationSummary
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
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.channelFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.buildJsonObject
import okhttp3.Call
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.RequestBody
import okhttp3.Response
import java.util.Base64
import java.util.concurrent.ConcurrentHashMap

/**
 * Signed in with a personal Lynxce (灵策智算) account: chat goes straight to the Lynxce model gateway and
 * conversations sync through Lynxce web-chat sessions, so they also appear in Octop Bot on the desktop.
 */
class LynxceBackend(
    private var grant: LynxceGrant,
    private val store: AppStore,
    private val localBots: LocalBots,
) : ChatBackend {
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

        suspend fun signIn(account: String, password: String, store: AppStore, localBots: LocalBots): LynxceBackend {
            val data = call("POST", "/api/auth/password-login", null, emptyMap(), Http.body(LynxceProtocol.loginBody(account, password)))
            val body = data.asObject() ?: throw ApiException.badResponse()
            val user = body.obj("user")
            val grant = LynxceGrant(
                accountId = user?.idString("id") ?: throw ApiException.badResponse(),
                displayName = user.str("displayName")?.takeIf { it.isNotBlank() },
                accessToken = body.str("accessToken") ?: throw ApiException.badResponse(),
                refreshToken = body.str("refreshToken") ?: throw ApiException.badResponse(),
            )
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

    override fun send(
        text: String,
        images: List<ImageAttachment>,
        bot: BotProfile,
        conversation: String?,
        history: List<ChatMessage>,
        model: String?,
    ): Flow<StreamEvent> = channelFlow {
        val sessionId = conversation ?: LynxceProtocol.newSessionId()
        val startedAt = System.currentTimeMillis()
        if (conversation == null) {
            store.updateSessionBots { it[sessionId] = bot.id }
            send(StreamEvent.Conversation(sessionId))
        }
        val body = LynxceProtocol.chatBody(text, images.map { it.jpeg }, bot, history, sessionId, model)
        val answer = StringBuilder()
        val thinking = StringBuilder()

        fun open(token: String): Call = streamClient.newCall(
            Http.request(url("/api/proxy/v1/chat/completions"), headers(token))
                .header("Accept", "text/event-stream")
                .post(Http.body(body))
                .build(),
        )

        var stream = RunningStream(open(grant.accessToken))
        // Stopped before the reply started: end quietly instead of reporting the cancelled call.
        suspend fun connect(): Response? = try {
            running[sessionId] = stream
            stream.call.await()
        } catch (error: ApiException) {
            if (stream.stopped) null else throw error
        }
        var response = connect() ?: return@channelFlow
        if (response.code == 401) {
            response.close()
            stream = RunningStream(open(refreshed(grant.accessToken).accessToken))
            response = connect() ?: return@channelFlow
        }
        val reader = launch(Dispatchers.IO) {
            val failure = runCatching {
                response.use {
                    if (!it.isSuccessful) throw ApiException.from(it.code, Http.errorMessage(it.body.string()))
                    var completed = false
                    it.body.source().forEachSseEvent { event ->
                        if (event.data == "[DONE]") {
                            completed = true
                            return@forEachSseEvent false
                        }
                        for (parsed in LynxceProtocol.parseChunk(event.data)) {
                            when (parsed) {
                                is StreamEvent.Text -> answer.append(parsed.delta)
                                is StreamEvent.Thinking -> thinking.append(parsed.delta)
                                else -> Unit
                            }
                            send(parsed)
                        }
                        true
                    }
                    // A stream that ends without [DONE] is an interrupted reply.
                    if (!completed && !stream.stopped) throw ApiException.network()
                }
            }.exceptionOrNull()
            running.remove(sessionId)
            sync(sessionId, text, startedAt, answer.toString(), thinking.toString(), model)
            close(failure?.takeUnless { stream.stopped })
        }
        awaitClose {
            if (reader.isActive) stream.call.cancel()
        }
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

    override suspend fun signOut() {
        running.values.forEach { it.call.cancel() }
        runCatching { call("POST", "/api/auth/logout", grant.accessToken, emptyMap(), Http.body(buildJsonObject {})) }
        background.cancel()
        store.setLynxceGrant(null)
    }
}
