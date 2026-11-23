package io.github.alisonxx.octopbot.net

import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.ChatMessage
import io.github.alisonxx.octopbot.model.ConversationSummary
import io.github.alisonxx.octopbot.model.GroupDraft
import io.github.alisonxx.octopbot.model.GroupGoal
import io.github.alisonxx.octopbot.model.GroupMessage
import io.github.alisonxx.octopbot.model.GroupSummary
import io.github.alisonxx.octopbot.model.HitlDecision
import io.github.alisonxx.octopbot.model.ImageAttachment
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.model.ModelOption
import io.github.alisonxx.octopbot.model.StreamEvent
import io.github.alisonxx.octopbot.model.VoiceSupport
import io.github.alisonxx.octopbot.store.AppStore
import io.github.alisonxx.octopbot.store.ServerSession
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.channelFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.RequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.net.URLEncoder
import java.util.concurrent.ConcurrentHashMap

/** A self-hosted Octop Bot server (NAS / Docker web build): its Bots, tools, memory and groups. */
class ServerBackend(
    session: ServerSession,
    private val store: AppStore,
) : ChatBackend, CreditAccount {
    @Volatile private var session = session
    private val background = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val sockets = ConcurrentHashMap<String, WebSocket>()
    private var voice: VoiceSupport? = null
    @Volatile private var labelCache: Map<String, String>? = null
    private var directory: List<BotProfile> = emptyList()

    override val definesBotsLocally = false
    override val supportsGroups = true
    override val accountName get() = session.displayName
    /** The full server address, e.g. `http://10.0.2.2:18790`. */
    val baseUrl: String get() = session.baseUrl
    /** Octop Bot cloud: Lynxce sign-in, and the server keeps the Lynxce wallet. */
    val isCloud: Boolean get() = session.cloud
    /** host, plus the port when it isn't the scheme's default (e.g. `10.0.2.2:18790`). */
    override val connectionLabel: String
        get() = session.baseUrl.toHttpUrl().let { url ->
            if (url.port == HttpUrl.defaultPort(url.scheme)) url.host else "${url.host}:${url.port}"
        }

    /** Sends the bearer token and adopts renewed tokens (there is no refresh endpoint). */
    private val client: OkHttpClient = Http.client.newBuilder().addInterceptor(Interceptor { chain ->
        val response = chain.proceed(chain.request().newBuilder().header("Authorization", "Bearer ${session.token}").build())
        adoptRenewedToken(response)
        response
    }).build()
    private val slowClient = client.withReadTimeout(900)

    private fun adoptRenewedToken(response: Response) {
        val renewed = response.header("X-Octop-Access-Token")?.takeIf { it.isNotBlank() } ?: return
        if (renewed == session.token) return
        session = session.copy(token = renewed)
        val saved = session
        background.launch { store.setServerSession(saved) }
    }

    companion object {
        /** How this server wants its owner to sign in, mirroring the dashboard's login route. */
        sealed interface SignInMode {
            /** Bot web build owned (or about to be claimed) by a Lynxce account. */
            data class Lynxce(val claimed: Boolean) : SignInMode
            /** Bot web build whose owner chose a local password (username `local`). */
            data object LocalPassword : SignInMode
            /** A regular Octop server: username and password. */
            data object Password : SignInMode
        }

        class Probe(val base: String, val mode: SignInMode)

        sealed interface SignIn {
            data class Done(val backend: ServerBackend) : SignIn
            data class NeedsMfa(val mfaToken: String) : SignIn
        }

        private suspend fun anonymous(base: String, method: String, path: String, body: JsonObject? = null): JsonObject {
            val request = Http.request(base + path).method(method, body?.let(Http::body)).build()
            return Http.client.newCall(request).await().use { response ->
                val text = withContext(Dispatchers.IO) { response.body.string() }
                if (!response.isSuccessful) throw ApiException.from(response.code, Http.errorMessage(text))
                Http.parse(text).asObject() ?: JsonObject(emptyMap())
            }
        }

        /** Without a typed scheme, try https first and fall back to http (LAN NAS boxes often lack TLS). */
        suspend fun probe(typed: String): Probe {
            val base = ServerProtocol.normalizeUrl(typed) ?: throw IllegalArgumentException(typed)
            return try {
                Probe(base, mode(base))
            } catch (error: ApiException) {
                if (error.kind != ApiException.Kind.Network || "://" in typed) throw error
                val plain = base.replaceFirst("https://", "http://")
                Probe(plain, mode(plain))
            }
        }

        private suspend fun mode(base: String): SignInMode {
            val status = anonymous(base, "GET", "/api/setup/status")
            if (status.bool("lynxce_login") != true) return SignInMode.Password
            val setupRequired = status.bool("setup_required") == true
            val identity = runCatching { anonymous(base, "GET", "/api/auth/lynxce/status") }.getOrNull()
            // Octop Bot cloud: every Lynxce account signs in to its own account, nothing to claim.
            if (identity?.bool("cloud") == true) return SignInMode.Lynxce(claimed = true)
            val claimed = identity?.bool("claimed") == true
            return if (setupRequired || claimed) SignInMode.Lynxce(claimed) else SignInMode.LocalPassword
        }

        suspend fun signInWithLynxce(base: String, account: String, password: String, store: AppStore): ServerBackend {
            val body = buildJsonObject {
                put("account", account)
                put("password", password)
                put("locale", if (Http.isChinese()) "zh" else "en")
            }
            return finish(base, anonymous(base, "POST", "/api/auth/lynxce/login", body), store)
        }

        /** Ask the server to send its Lynxce owner a sign-in code (it relays to Lynxce and rate-limits). */
        suspend fun requestLynxceCode(base: String, target: String) {
            anonymous(base, "POST", "/api/auth/lynxce/code", ServerProtocol.lynxceCodeBody(target, Http.isChinese()))
        }

        /** Owner sign-in with a Lynxce code; works for Lynxce accounts that never set a password. */
        suspend fun signInWithLynxceCode(base: String, target: String, code: String, store: AppStore): ServerBackend {
            val body = ServerProtocol.lynxceCodeLoginBody(target, code, Http.isChinese())
            return finish(base, anonymous(base, "POST", "/api/auth/lynxce/code-login", body), store)
        }

        /** Password sign-in; the Bot web build's local account is always `local`. */
        suspend fun signIn(base: String, username: String, password: String, store: AppStore): SignIn {
            val body = anonymous(base, "POST", "/api/auth/login", buildJsonObject {
                put("username", username)
                put("password", password)
            })
            if (body.bool("mfa_required") == true) {
                return SignIn.NeedsMfa(body.str("mfa_token") ?: throw ApiException.badResponse())
            }
            return SignIn.Done(finish(base, body, store))
        }

        suspend fun verifyMfa(base: String, mfaToken: String, code: String, store: AppStore): ServerBackend {
            val body = anonymous(base, "POST", "/api/auth/mfa/verify", buildJsonObject {
                put("mfa_token", mfaToken)
                put("method", "totp")
                put("code", code)
            })
            return finish(base, body, store)
        }

        /** Is Octop Bot cloud up? Until it is, a Lynxce sign-in talks to Lynxce directly. */
        suspend fun lynxceCloudAvailable(): Boolean = runCatching {
            val request = Http.request(ServerProtocol.LYNXCE_CLOUD + "/api/octop-bot/server-info").get().build()
            Http.client.withReadTimeout(4).newCall(request).await().use { response ->
                response.isSuccessful &&
                    ServerProtocol.isCloudInfo(Http.parse(withContext(Dispatchers.IO) { response.body.string() }))
            }
        }.getOrDefault(false)

        private suspend fun finish(base: String, body: JsonObject, store: AppStore): ServerBackend {
            val token = body.str("access_token") ?: throw ApiException.badResponse()
            val user = body.obj("user")
            val name = user?.str("display_name")?.takeIf { it.isNotBlank() } ?: user?.str("username") ?: "Octop"
            // Octop Bot cloud says so in its sign-in response.
            val session = ServerSession(base, token, name, cloud = body.bool("cloud") == true)
            store.setServerSession(session)
            return ServerBackend(session, store)
        }
    }

    // Transport

    private fun url(path: String, query: Map<String, String> = emptyMap()): String =
        (session.baseUrl + path).toHttpUrl().newBuilder().apply {
            query.toSortedMap().forEach { (key, value) -> addQueryParameter(key, value) }
        }.build().toString()

    private suspend fun raw(
        method: String,
        path: String,
        query: Map<String, String> = emptyMap(),
        body: RequestBody? = null,
        http: OkHttpClient = client,
    ): ByteArray {
        // OkHttp requires a body for POST/PUT; endpoints without one take an empty JSON object.
        val payload = body ?: if (method == "POST" || method == "PUT") Http.body(JsonObject(emptyMap())) else null
        val request = Http.request(url(path, query)).method(method, payload).build()
        return http.newCall(request).await().use { response ->
            val bytes = withContext(Dispatchers.IO) { response.body.bytes() }
            if (!response.isSuccessful) throw ApiException.from(response.code, Http.errorMessage(bytes.decodeToString()))
            bytes
        }
    }

    private suspend fun json(
        method: String,
        path: String,
        query: Map<String, String> = emptyMap(),
        body: RequestBody? = null,
        http: OkHttpClient = client,
    ): JsonElement = Http.parse(raw(method, path, query, body, http).decodeToString())

    // Lynxce wallet (Octop Bot cloud only)

    @Volatile private var walletAccount: String? = null

    override suspend fun balance(): String? {
        if (!isCloud) return null
        return runCatching {
            val wallet = json("GET", "/api/octop-bot/wallet", mapOf("source" to "cloud")).asObject()
            walletAccount = wallet?.str("account_id")
            wallet?.double("credits")?.let(LynxceProtocol::formatCredits)
        }.getOrNull()
    }

    override suspend fun checkoutUrl(): String {
        if (!isCloud) throw ApiException.badResponse()
        val account = walletAccount ?: balance().let { walletAccount } ?: throw ApiException.badResponse()
        val link = json("POST", "/api/octop-bot/wallet/recharge", body = Http.body(buildJsonObject {
            put("source", "cloud")
            put("expected_account_id", account)
        })).asObject()
        // The server checked the ticket; only ever open Lynxce's own recharge page.
        return link?.str("url")?.takeIf { it.startsWith(LynxceProtocol.CHECKOUT_PORTAL) } ?: throw ApiException.badResponse()
    }

    override suspend fun requestDeletion() {
        if (!isCloud) throw ApiException.badResponse()
        json("POST", "/api/octop-bot/account/delete")
    }

    /** Octop Bot cloud: a Bot's cloud computer. */
    suspend fun computerStatus(botId: String): ServerProtocol.ComputerStatus =
        ServerProtocol.computerStatus(json("GET", "/api/octop-bot/computers/" + segment(botId))) ?: throw ApiException.badResponse()

    suspend fun pauseComputer(botId: String): ServerProtocol.ComputerStatus =
        ServerProtocol.computerStatus(json("POST", "/api/octop-bot/computers/" + segment(botId) + "/pause"))
            ?: throw ApiException.badResponse()

    suspend fun setTakeover(botId: String, active: Boolean): ServerProtocol.ComputerStatus =
        ServerProtocol.computerStatus(
            json("POST", "/api/octop-bot/computers/" + segment(botId) + "/takeover", body = Http.body(buildJsonObject { put("active", active) })),
        ) ?: throw ApiException.badResponse()

    /** The screen page for a Bot's computer, with a fresh one-time ticket. */
    suspend fun screenUrl(botId: String, control: Boolean): String {
        val ticket = json("POST", "/api/octop-bot/computers/" + segment(botId) + "/screen").asObject()
        val wsPath = ticket?.str("ws_path")
        return wsPath?.let { ServerProtocol.screenPage(baseUrl, botId, it, ticket?.str("session"), control) }
            ?: throw ApiException.badResponse()
    }

    /** Octop Bot cloud: a short-lived object-store link for a file a Bot linked to. */
    suspend fun downloadLink(uri: String): String {
        val parsed = (session.baseUrl + uri).toHttpUrl()
        val query = (0 until parsed.querySize).associate { parsed.queryParameterName(it) to parsed.queryParameterValue(it).orEmpty() }
        val link = json("POST", parsed.encodedPath + "-link", query).asObject()?.str("url")
        return link?.takeIf { it.startsWith("https://") } ?: throw ApiException.badResponse()
    }

    private fun segment(value: String): String = URLEncoder.encode(value, "UTF-8").replace("+", "%20")

    private fun agent(bot: BotProfile) = "/api/agents/" + segment(bot.id)

    private fun group(id: String) = "/api/octop-bot/groups/" + segment(id)

    // Directory

    override suspend fun bots(): List<BotProfile> {
        val (bots, _) = ServerProtocol.workspace(json("GET", "/api/octop-bot/workspace"))
        directory = bots
        return bots
    }

    override suspend fun setLook(bot: BotProfile, look: Look) {
        json("PUT", "/api/octop-bot/bots/${segment(bot.id)}/appearance", body = Http.body(buildJsonObject {
            put("shape", look.shape)
            put("color", look.color)
        }))
    }

    /** A new teammate Bot with a role prompt and look, like the dashboard's quick create. Returns its id. */
    suspend fun createBot(name: String, role: String, look: Look): String {
        val created = json("POST", "/api/agents", body = Http.body(buildJsonObject {
            put("name", name)
            put("description", role)
            put("system_prompt", role)
        }), http = slowClient)
        val id = created.asObject()?.str("agent_id") ?: throw ApiException.badResponse()
        runCatching { setLook(BotProfile(id, name, look = look), look) }
        return id
    }

    /** Model choice is per Bot on a server (its `default_model`); the phone does not override it. */
    override suspend fun models(): List<ModelOption> = emptyList()

    /** Localized tool names, fetched once per app language; failures fall back to raw names. */
    private suspend fun toolLabels(): Map<String, String> = labelCache ?: runCatching {
        ServerProtocol.toolLabels(json("GET", "/api/i18n/tools"))
    }.onSuccess { labelCache = it }.getOrDefault(emptyMap())

    /** The app language changed: fetch tool labels again on next use. */
    fun forgetToolLabels() {
        labelCache = null
    }

    // Threads

    override suspend fun conversations(bot: BotProfile): List<ConversationSummary> =
        ServerProtocol.conversations(json("GET", agent(bot) + "/threads", mapOf("limit" to "50")), bot.id)

    override suspend fun messages(conversation: ConversationSummary, bot: BotProfile): List<ChatMessage> =
        transcript(conversation, bot).messages

    override suspend fun transcript(conversation: ConversationSummary, bot: BotProfile): Transcript {
        repeat(20) {
            val page = ServerProtocol.historyPage(
                json("GET", agent(bot) + "/threads/${segment(conversation.id)}/history", mapOf("limit" to "50")),
                toolLabels(),
            )
            if (!page.loading) return Transcript(page.messages, page.pending)
            delay(page.retryAfterMs.coerceIn(300, 3000))
        }
        return Transcript(emptyList(), pending = null)
    }

    override suspend fun deleteConversation(conversation: ConversationSummary, bot: BotProfile) {
        raw("DELETE", agent(bot) + "/threads/${segment(conversation.id)}")
    }

    // Chat over WebSocket

    override fun send(
        text: String,
        images: List<ImageAttachment>,
        bot: BotProfile,
        conversation: String?,
        history: List<ChatMessage>,
        model: String?,
    ): Flow<StreamEvent> = channelFlow {
        val threadId = conversation ?: run {
            val created = json("POST", agent(bot) + "/threads").asObject()?.str("thread_id") ?: throw ApiException.badResponse()
            send(StreamEvent.Conversation(created))
            created
        }
        val content = if (images.isEmpty()) JsonPrimitive(text) else {
            ServerProtocol.imageContent(text, images.mapIndexed { index, image -> upload(image, index, bot) })
        }
        val frames = Channel<String>(Channel.UNLIMITED)
        val wsUrl = url(agent(bot) + "/chat/ws", mapOf("token" to session.token))
            .replaceFirst("https://", "wss://").replaceFirst("http://", "ws://")
        val socket = Http.client.newWebSocket(
            Http.request(wsUrl).build(),
            object : WebSocketListener() {
                override fun onMessage(webSocket: WebSocket, text: String) {
                    frames.trySend(text)
                }

                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                    frames.close(ServerProtocol.closeError(code, reason))
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    frames.close(
                        if (response?.code == 401) ApiException(ApiException.Kind.Unauthorized, 401) else ApiException.network(),
                    )
                }
            },
        )
        sockets[threadId] = socket
        val pinger = launch {
            while (true) {
                delay(25_000)
                socket.send(ServerProtocol.ping.toString())
            }
        }
        try {
            socket.send(ServerProtocol.userTurn(threadId, text, content, model).toString())
            val mapper = ServerProtocol.FrameMapper(toolLabels())
            for (raw in frames) {
                val frame = Http.parse(raw).asObject() ?: continue
                when (val outcome = mapper.map(frame, threadId)) {
                    is ServerProtocol.FrameMapper.Outcome.Events -> outcome.events.forEach { send(it) }
                    ServerProtocol.FrameMapper.Outcome.Finished -> return@channelFlow
                }
            }
        } finally {
            pinger.cancel()
            sockets.remove(threadId)
            socket.close(1000, null)
        }
    }

    private suspend fun upload(image: ImageAttachment, index: Int, bot: BotProfile): JsonObject {
        val name = "photo-${System.currentTimeMillis() / 1000}-${index + 1}.jpg"
        val form = Http.form(listOf(FormPart.File("file", image.jpeg, name, "image/jpeg")))
        return json("POST", agent(bot) + "/upload", body = form, http = slowClient).asObject() ?: throw ApiException.badResponse()
    }

    /** `POST chat/hitl/resume`; its SSE `chunk` frames have the socket's shapes and end with `done`. */
    override fun resumeHitl(
        bot: BotProfile,
        conversation: String,
        pendingId: String?,
        decisions: List<HitlDecision>,
    ): Flow<StreamEvent> = channelFlow {
        val request = Http.request(url(agent(bot) + "/chat/hitl/resume"))
            .header("Accept", "text/event-stream")
            .post(Http.body(ServerProtocol.hitlResume(conversation, pendingId, decisions)))
            .build()
        val call = slowClient.newCall(request)
        val mapper = ServerProtocol.FrameMapper(toolLabels(), endsOnDone = true)
        try {
            // Reading and closing both stay off the main thread: closing a body that still has bytes drains it.
            withContext(Dispatchers.IO) {
                call.await().use { response ->
                    if (!response.isSuccessful) throw ApiException.from(response.code, Http.errorMessage(response.body.string()))
                    response.body.source().forEachSseEvent { event ->
                        val frame = Http.parse(event.data).asObject() ?: return@forEachSseEvent true
                        when (val outcome = mapper.map(frame, conversation)) {
                            is ServerProtocol.FrameMapper.Outcome.Events -> {
                                outcome.events.forEach { send(it) }
                                true
                            }
                            ServerProtocol.FrameMapper.Outcome.Finished -> false
                        }
                    }
                    // `done` ends the reply; whatever follows is dropped, not drained.
                    call.cancel()
                }
            }
        } finally {
            call.cancel()
        }
    }

    override suspend fun stop(conversation: String, bot: BotProfile) {
        sockets[conversation]?.send(ServerProtocol.cancel(conversation).toString())
    }

    // Groups

    suspend fun groups(): List<GroupSummary> {
        if (directory.isEmpty()) bots()
        return ServerProtocol.groups(json("GET", "/api/octop-bot/groups"))
    }

    suspend fun createGroup(name: String, members: List<BotProfile>) {
        json("POST", "/api/octop-bot/groups", body = Http.body(ServerProtocol.groupCreate(name, members)))
    }

    suspend fun groupMessages(groupId: String, afterId: String?): List<GroupMessage> =
        ServerProtocol.groupMessages(json("GET", group(groupId) + "/messages", afterId?.let { mapOf("after_id" to it) }.orEmpty()))

    suspend fun groupDrafts(groupId: String): List<GroupDraft> = ServerProtocol.groupDrafts(json("GET", group(groupId) + "/drafts"))

    /** Blocks until every addressed Bot finished; idempotent per [requestId]. */
    suspend fun postGroupMessage(groupId: String, requestId: String, text: String, mentionIds: List<String>) {
        raw(
            "POST",
            group(groupId) + "/messages",
            body = Http.body(ServerProtocol.groupPost(requestId, text, mentionIds)),
            http = slowClient,
        )
    }

    suspend fun groupMemory(groupId: String): String = json("GET", group(groupId) + "/memory").asObject()?.str("text").orEmpty()

    suspend fun groupGoal(groupId: String): GroupGoal? = ServerProtocol.groupGoal(json("GET", group(groupId) + "/goal"))

    // Voice and account

    override suspend fun voiceSupport(): VoiceSupport = voice ?: runCatching {
        ServerProtocol.voiceSupport(json("GET", "/api/voice/active"))
    }.getOrDefault(VoiceSupport(stt = false, tts = false)).also { voice = it }

    override suspend fun transcribe(audio: ByteArray): String {
        val form = Http.form(
            listOf(
                FormPart.File("audio", audio, "voice.m4a", "audio/mp4"),
                FormPart.Field("language", if (Http.isChinese()) "zh-CN" else "en-US"),
            ),
        )
        return json("POST", "/api/voice/stt", body = form, http = slowClient).asObject()?.str("text").orEmpty()
    }

    override suspend fun speech(text: String): ByteArray =
        raw("POST", "/api/voice/tts", body = Http.body(buildJsonObject { put("text", text.take(4000)) }), http = slowClient)

    override suspend fun signOut() {
        sockets.values.forEach { it.cancel() }
        background.cancel()
        store.setServerSession(null)
    }
}
