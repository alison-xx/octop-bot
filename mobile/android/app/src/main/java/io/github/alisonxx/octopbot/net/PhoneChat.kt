package io.github.alisonxx.octopbot.net

import io.github.alisonxx.octopbot.device.DeviceCatalog
import io.github.alisonxx.octopbot.device.DeviceToolbox
import io.github.alisonxx.octopbot.device.ToolCallAccumulator
import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.ChatMessage
import io.github.alisonxx.octopbot.model.HitlDecision
import io.github.alisonxx.octopbot.model.ImageAttachment
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.model.StreamEvent
import io.github.alisonxx.octopbot.store.LocalBots
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.ProducerScope
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.channelFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import okhttp3.Call
import okhttp3.Request
import okhttp3.Response
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/**
 * The OpenAI-style chat the phone runs itself, with Bots defined on the phone: Lynxce's gateway, or the model the
 * user set up here ([PhoneModels]: their own vendor key or a local server). When the model calls the phone's device
 * tools (PROTOCOL §C) reads run at once and writes pause for the approval card.
 */
abstract class PhoneChat(
    protected val localBots: LocalBots,
    private val phoneModels: PhoneModels,
) : ChatBackend {
    override val definesBotsLocally = true
    override val supportsGroups = false

    protected val background = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val running = ConcurrentHashMap<String, RunningStream>()
    private val streamClient = Http.client.withReadTimeout(300)

    private class RunningStream(val call: Call) {
        @Volatile var stopped = false
    }

    /** A new conversation id. */
    protected abstract fun newSessionId(): String

    /** The first reply of a new conversation is starting. */
    protected abstract suspend fun started(sessionId: String, bot: BotProfile, text: String)

    /** A turn ended (not paused): keep the user's text and the answer. */
    protected abstract fun finished(sessionId: String, user: String, startedAt: Long, answer: String, thinking: String, model: String?)

    /** A request to Lynxce's gateway; [renew] after a 401 asks for a fresh token. */
    protected abstract suspend fun gatewayRequest(body: JsonObject, renew: Boolean): Request

    override suspend fun bots() = localBots.all()

    override suspend fun setLook(bot: BotProfile, look: Look) = localBots.save(bot.copy(look = look))

    /** One turn of the local tool loop: the first request, the loop's messages and what gets kept. */
    private class Turn(
        val sessionId: String,
        val user: String,
        val startedAt: Long,
        val model: String?,
        /** Set when the phone calls the model itself rather than Lynxce's gateway. */
        val endpoint: ModelEndpoint?,
        val first: JsonObject,
        val device: DeviceToolbox,
        /** Names of the device tools offered in [first]. */
        val offered: Set<String>,
    ) {
        val loop = mutableListOf<JsonObject>()
        var rounds = 0
        var withTools = offered.isNotEmpty()
        /** The visible answer across rounds and pauses; kept when the turn ends. */
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

    /** The model the user picked on this phone, which wins over Lynxce's; null means Lynxce's gateway. */
    protected open fun endpoint(): ModelEndpoint? = phoneModels.endpoint()

    override fun send(
        text: String,
        images: List<ImageAttachment>,
        bot: BotProfile,
        conversation: String?,
        history: List<ChatMessage>,
        model: String?,
        device: DeviceToolbox,
    ): Flow<StreamEvent> = channelFlow {
        val sessionId = conversation ?: newSessionId()
        val startedAt = System.currentTimeMillis()
        if (conversation == null) {
            started(sessionId, bot, text)
            send(StreamEvent.Conversation(sessionId))
        }
        val endpoint = endpoint()
        val tools = device.offered()
        val body = LynxceProtocol.chatBody(text, images.map { it.jpeg }, bot, history, sessionId, model, tools = tools)
        drive(Turn(sessionId, text, startedAt, endpoint?.model ?: model, endpoint, body, device, tools.map { it.name }.toSet()))
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
            // Only the user's text and the answer are kept; a paused turn is kept when it ends.
            if (!paused) finished(turn.sessionId, turn.user, turn.startedAt, turn.answer.toString(), turn.thinking.toString(), turn.model)
            close(failure?.takeUnless { stopped })
        }
        awaitClose {
            if (worker.isActive) running[turn.sessionId]?.call?.cancel()
        }
    }

    private suspend fun roundRequest(turn: Turn, renew: Boolean): Request {
        val body = LynxceProtocol.roundBody(turn.first, turn.loop, turn.withTools)
        val endpoint = turn.endpoint ?: return gatewayRequest(body, renew)
        return Http.request(endpoint.completionsUrl, endpoint.headers)
            .header("Accept", "text/event-stream")
            .post(Http.body(ModelSourcesProtocol.vendorBody(body, endpoint.model)))
            .build()
    }

    /**
     * One streamed request of [turn]; tool-call pieces go to [calls], deltas to [onEvent]. Lynxce's gateway gets one
     * token refresh on 401; any model drops `tools` once on 400. Returns false when the user stopped it.
     */
    private suspend fun request(turn: Turn, calls: ToolCallAccumulator, onEvent: suspend (StreamEvent) -> Unit): Boolean {
        val vendor = turn.endpoint != null
        var stream = RunningStream(streamClient.newCall(roundRequest(turn, renew = false)))
        // Stopped before the reply started: end quietly instead of reporting the cancelled call.
        suspend fun connect(): Response? = try {
            running[turn.sessionId] = stream
            stream.call.await()
        } catch (error: ApiException) {
            if (stream.stopped) null else if (vendor) throw ModelSourceException(ModelSourceException.Reason.Unreachable) else throw error
        }
        var response = connect() ?: return false
        if (response.code == 401 && !vendor) {
            response.close()
            stream = RunningStream(streamClient.newCall(roundRequest(turn, renew = true)))
            response = connect() ?: return false
        }
        if (response.code == 400 && turn.withTools) {
            // The model refused function calling: answer without tools.
            response.close()
            turn.withTools = false
            stream = RunningStream(streamClient.newCall(roundRequest(turn, renew = false)))
            response = connect() ?: return false
        }
        response.use {
            if (!it.isSuccessful) {
                val text = it.body.string()
                throw if (vendor) ModelSourcesProtocol.vendorError(it.code, text) else ApiException.fromBody(it.code, text)
            }
            var completed = false
            try {
                it.body.source().forEachSseEvent { event ->
                    if (event.data == "[DONE]") {
                        completed = true
                        return@forEachSseEvent false
                    }
                    val parsed = try {
                        LynxceProtocol.parseChunk(event.data, calls)
                    } catch (error: ApiException) {
                        // A vendor's quota is not the Lynxce wallet: never show the top-up card for it.
                        if (vendor) throw ApiException(ApiException.Kind.Server, error.status, error.message) else throw error
                    }
                    for (item in parsed) onEvent(item)
                    if (vendor && ModelSourcesProtocol.finishReason(event.data) != null) completed = true
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

    override suspend fun stop(conversation: String, bot: BotProfile) {
        running[conversation]?.let {
            it.stopped = true
            it.call.cancel()
        }
    }

    protected fun cancelAll() = running.values.forEach { it.call.cancel() }

    private companion object {
        /** Requests per turn in the device tool loop. */
        const val MAX_ROUNDS = 6
    }
}
