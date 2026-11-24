package io.github.alisonxx.octopbot.net

import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.ChatMessage
import io.github.alisonxx.octopbot.model.ConversationSummary
import io.github.alisonxx.octopbot.model.ModelOption
import io.github.alisonxx.octopbot.model.VoiceSupport
import io.github.alisonxx.octopbot.store.AppStore
import io.github.alisonxx.octopbot.store.LocalBots
import io.github.alisonxx.octopbot.store.LynxceGrant
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.Request
import okhttp3.RequestBody
import java.util.Base64

/**
 * Signed in with a personal Lynxce (灵策智算) account: chat goes straight to the Lynxce model gateway and
 * conversations sync through Lynxce web-chat sessions, so they also appear in Octop Bot on the desktop.
 */
class LynxceBackend(
    private var grant: LynxceGrant,
    private val store: AppStore,
    localBots: LocalBots,
    phoneModels: PhoneModels,
) : PhoneChat(localBots, phoneModels), CreditAccount {
    /** Lynxce's display name; never the numeric account id. */
    override val accountName: String? get() = grant.displayName?.trim()?.takeIf { it.isNotEmpty() && it != grant.accountId }
    override val connectionLabel = "api.lynxce.cn"

    private val refreshLock = Mutex()

    companion object {
        private fun headers(bearer: String?) = LynxceProtocol.headers(bearer)

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

        suspend fun signIn(account: String, password: String, store: AppStore, localBots: LocalBots, phoneModels: PhoneModels): LynxceBackend =
            enter(call("POST", "/api/auth/password-login", null, emptyMap(), Http.body(LynxceProtocol.loginBody(account, password))), store, localBots, phoneModels)

        /** Send a sign-in code by SMS or email. The response's dev code is ignored on purpose. */
        suspend fun requestCode(target: LynxceProtocol.Target) {
            val body = LynxceProtocol.codeRequestBody(target, Http.isChinese())
            call("POST", LynxceProtocol.codeRequestPath(target), null, emptyMap(), Http.body(body))
        }

        /** Sign in (or sign up: Lynxce creates new accounts automatically) with a 6-digit code. */
        suspend fun signIn(target: LynxceProtocol.Target, code: String, store: AppStore, localBots: LocalBots, phoneModels: PhoneModels): LynxceBackend {
            require(LynxceProtocol.isValidCode(code))
            val body = LynxceProtocol.codeLoginBody(target, code)
            return enter(call("POST", LynxceProtocol.codeLoginPath(target), null, emptyMap(), Http.body(body)), store, localBots, phoneModels)
        }

        private suspend fun enter(data: JsonElement, store: AppStore, localBots: LocalBots, phoneModels: PhoneModels): LynxceBackend {
            val grant = LynxceProtocol.grant(data)
            store.setLynxceGrant(grant)
            return LynxceBackend(grant, store, localBots, phoneModels)
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

    // Chat

    override fun newSessionId(): String = LynxceProtocol.newSessionId()

    override suspend fun started(sessionId: String, bot: BotProfile, text: String) {
        store.updateSessionBots { it[sessionId] = bot.id }
    }

    override fun finished(sessionId: String, user: String, startedAt: Long, answer: String, thinking: String, model: String?) =
        sync(sessionId, user, startedAt, answer, thinking, model)

    override suspend fun gatewayRequest(body: JsonObject, renew: Boolean): Request {
        val token = if (renew) refreshed(grant.accessToken).accessToken else grant.accessToken
        return Http.request(url("/api/proxy/v1/chat/completions"), headers(token))
            .header("Accept", "text/event-stream")
            .post(Http.body(body))
            .build()
    }

    /** Append the finished turn to the synced Lynxce session (idempotent on the server). */
    private fun sync(sessionId: String, user: String, startedAt: Long, answer: String, thinking: String, model: String?) {
        val body = LynxceProtocol.syncBody(user, startedAt, answer, thinking, model, System.currentTimeMillis())
        background.launch {
            runCatching { call("POST", sessionPath(sessionId) + "/items") { Http.body(body) } }
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

    override val walletKey: String get() = "lynxce:" + grant.accountId

    override suspend fun balance(): Double =
        LynxceProtocol.balance(call("GET", "/api/user/quota")) ?: throw ApiException.badResponse()

    /** A signed-in link to Lynxce's recharge page for this account, valid for 15 minutes. */
    override suspend fun checkoutUrl(scenario: CreditScenario?): String =
        (LynxceProtocol.checkoutUrl(call("POST", "/api/billing/recharge/checkout-link") { Http.body(buildJsonObject {}) })
            ?: throw CheckoutRefused()).let(LynxceProtocol::boostTab)

    /** Ask Lynxce to delete this account; it is signed out everywhere and erased after a cooling-off period. */
    override suspend fun requestDeletion() {
        call("POST", "/api/user/account/deletion-request") { Http.body(LynxceProtocol.deletionBody()) }
    }

    override suspend fun signOut() {
        cancelAll()
        runCatching { call("POST", "/api/auth/logout", grant.accessToken, emptyMap(), Http.body(buildJsonObject {})) }
        background.cancel()
        store.setLynxceGrant(null)
    }
}
