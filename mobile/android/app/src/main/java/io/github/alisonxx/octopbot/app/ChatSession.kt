package io.github.alisonxx.octopbot.app

import io.github.alisonxx.octopbot.model.BotMotion
import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.ChatMessage
import io.github.alisonxx.octopbot.model.ConversationSummary
import io.github.alisonxx.octopbot.model.HitlAnswer
import io.github.alisonxx.octopbot.model.HitlAnswers
import io.github.alisonxx.octopbot.model.HitlDecision
import io.github.alisonxx.octopbot.model.HitlRequest
import io.github.alisonxx.octopbot.model.HitlTexts
import io.github.alisonxx.octopbot.model.ImageAttachment
import io.github.alisonxx.octopbot.model.MessageRole
import io.github.alisonxx.octopbot.model.MessageStatus
import io.github.alisonxx.octopbot.model.StreamEvent
import io.github.alisonxx.octopbot.model.ToolStep
import io.github.alisonxx.octopbot.net.ApiException
import io.github.alisonxx.octopbot.net.ChatBackend
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.util.UUID

data class ChatState(
    val conversationId: String? = null,
    val messages: List<ChatMessage> = emptyList(),
    val streaming: Boolean = false,
    val loading: Boolean = false,
    val conversations: List<ConversationSummary> = emptyList(),
    val motion: BotMotion = BotMotion.Idle,
    /** Server mode: an open question or approval; the card docks above the composer. */
    val hitl: HitlRequest? = null,
    /** Messages written while a reply streamed; sent in order when it ends. */
    val queued: List<QueuedMessage> = emptyList(),
)

data class QueuedMessage(val id: String = UUID.randomUUID().toString(), val text: String, val images: List<ImageAttachment> = emptyList())

/** The send queue: first in, first out; any entry can be cancelled. */
object SendQueue {
    fun enqueue(queue: List<QueuedMessage>, message: QueuedMessage): List<QueuedMessage> = queue + message
    fun cancel(queue: List<QueuedMessage>, id: String): List<QueuedMessage> = queue.filterNot { it.id == id }
    fun next(queue: List<QueuedMessage>): Pair<QueuedMessage?, List<QueuedMessage>> = queue.firstOrNull() to queue.drop(1)
}

/** What a chat needs from the app around it. */
interface ChatHost {
    val backend: ChatBackend
    fun bot(id: String): BotProfile?
    suspend fun model(): String?
    fun replyStarted(botId: String)
    /** [text] is the finished reply [messageId], or null when it failed or produced nothing. */
    fun replyEnded(bot: BotProfile, messageId: String, text: String?)
    fun failed(error: Throwable)
    /** Fixed HITL replies and captions in the app language. */
    val hitlTexts: HitlTexts
}

/**
 * One Bot's chat: its current conversation, messages and the reply being streamed. Lives in the activity
 * ViewModel, so a reply keeps streaming while the user is on another screen or briefly leaves the app.
 */
class ChatSession(private val botId: String, private val scope: CoroutineScope, private val host: ChatHost) {
    private val _state = MutableStateFlow(ChatState())
    val state: StateFlow<ChatState> = _state
    private var job: Job? = null
    private var opened = false
    private var lastAttachments: List<ImageAttachment> = emptyList()
    /** The running reply continues a paused turn (`hitl/resume`). */
    private var resumed = false
    /** Token of the newest reply run. */
    private var run = 0

    private val bot get() = host.bot(botId)

    /** First visit: continue the most recent conversation, like a messenger thread. */
    fun openLatest() {
        if (opened) return
        opened = true
        scope.launch {
            _state.update { it.copy(loading = true) }
            val latest = runCatching { loadConversations() }.getOrNull()?.firstOrNull()
            if (latest != null && _state.value.conversationId == null && _state.value.messages.isEmpty()) {
                loadMessages(latest)
            } else {
                _state.update { it.copy(loading = false) }
            }
        }
    }

    fun refreshConversations() {
        scope.launch { runCatching { loadConversations() }.onFailure(::report) }
    }

    private suspend fun loadConversations(): List<ConversationSummary> {
        val bot = bot ?: return emptyList()
        val list = host.backend.conversations(bot)
        _state.update { it.copy(conversations = list) }
        return list
    }

    fun open(conversation: ConversationSummary) {
        if (_state.value.streaming) return
        scope.launch { loadMessages(conversation) }
    }

    private suspend fun loadMessages(conversation: ConversationSummary) {
        val bot = bot ?: return
        _state.update { it.copy(conversationId = conversation.id, messages = emptyList(), loading = true, hitl = null) }
        val transcript = runCatching { host.backend.transcript(conversation, bot) }.onFailure(::report).getOrNull()
        val messages = transcript?.messages.orEmpty()
        _state.update {
            it.copy(messages = messages, loading = false, motion = restingMotion(messages), hitl = transcript?.pending)
        }
    }

    fun newChat() {
        if (_state.value.streaming) return
        _state.update { it.copy(conversationId = null, messages = emptyList(), loading = false, motion = BotMotion.Idle, hitl = null) }
    }

    fun delete(conversation: ConversationSummary) {
        val bot = bot ?: return
        _state.update { state ->
            state.copy(conversations = state.conversations.filterNot { it.id == conversation.id })
        }
        if (_state.value.conversationId == conversation.id) newChat()
        scope.launch {
            runCatching { host.backend.deleteConversation(conversation, bot) }.onFailure {
                report(it)
                refreshConversations()
            }
        }
    }

    /**
     * The composer's send. Never refused: while a reply streams the message is queued and sent when it ends;
     * with a question open it is the answer ([answers] are the card's picks); with an approval open it declines
     * the approval with this text as the reason.
     */
    fun send(text: String, images: List<ImageAttachment>, answers: List<List<HitlAnswer>> = emptyList()) {
        val body = text.trim()
        if (body.isEmpty() && images.isEmpty()) return
        val state = _state.value
        when {
            state.streaming -> _state.update { it.copy(queued = SendQueue.enqueue(it.queued, QueuedMessage(text = body, images = images))) }
            state.hitl != null && body.isNotEmpty() -> {
                val request = state.hitl
                val decisions = HitlAnswers.fromComposer(request, body, answers)
                if (request.isQuestion) {
                    val shown = (decisions.first() as? HitlDecision.Respond)?.message ?: body
                    resolve(request, decisions, shown, note = null)
                } else {
                    resolve(request, decisions, body, note = host.hitlTexts.declined(approvalLabels(request)))
                }
            }
            else -> startTurn(body, images)
        }
    }

    /** Remove a queued message before it is sent. */
    fun cancelQueued(id: String) {
        _state.update { it.copy(queued = SendQueue.cancel(it.queued, id)) }
    }

    private fun startTurn(text: String, images: List<ImageAttachment>) {
        val bot = bot ?: return
        val state = _state.value
        lastAttachments = images
        val history = state.messages.filter { it.role != MessageRole.Note }
        val user = ChatMessage(role = MessageRole.User, text = text, images = images.map { it.uri })
        stream(bot, listOf(user)) { host.backend.send(user.text, images, bot, state.conversationId, history, host.model()) }
    }

    // Questions and approvals (server mode)

    /** The question card's Send. */
    fun answerQuestions(answers: List<List<HitlAnswer>>) {
        val request = _state.value.hitl ?: return
        val decisions = HitlAnswers.respond(request, answers)
        resolve(request, decisions, decisions.mapNotNull { (it as? HitlDecision.Respond)?.message }.joinToString("\n"), note = null)
    }

    /** "You decide": the Bot picks sensible defaults. */
    fun youDecide() {
        val request = _state.value.hitl ?: return
        resolve(request, HitlAnswers.respondAll(request, host.hitlTexts.youDecide), shown = null, note = null)
    }

    /** Closing the question card: the Bot wraps up without asking again. */
    fun closeQuestions() {
        val request = _state.value.hitl ?: return
        resolve(request, HitlAnswers.respondAll(request, host.hitlTexts.closed), shown = null, note = null)
    }

    fun review(approve: Boolean) {
        val request = _state.value.hitl ?: return
        val texts = host.hitlTexts
        val labels = approvalLabels(request)
        resolve(
            request,
            HitlAnswers.review(request, approve, if (approve) texts.youDecide else texts.closed),
            shown = null,
            note = if (approve) texts.approved(labels) else texts.declined(labels),
        )
    }

    private fun approvalLabels(request: HitlRequest) =
        request.actions.filter { it.questions == null }.joinToString(", ") { it.label }

    /**
     * Answer the open card: the paused turn continues on the server and streams into a new reply. [shown] is
     * echoed as the user's bubble, [note] as a centered caption ("Approved: …" / "Declined: …").
     */
    private fun resolve(request: HitlRequest, decisions: List<HitlDecision>, shown: String?, note: String?) {
        val bot = bot ?: return
        val state = _state.value
        val conversation = state.conversationId ?: return
        if (state.streaming) return
        _state.update { it.copy(hitl = null) }
        val echoes = listOfNotNull(
            shown?.takeIf { it.isNotBlank() }?.let { ChatMessage(role = MessageRole.User, text = it) },
            note?.let { ChatMessage(role = MessageRole.Note, text = it) },
        )
        stream(bot, echoes, resume = true, onFailure = {
            // Still pending on the server: offer the card again.
            _state.update { if (it.hitl == null) it.copy(hitl = request) else it }
        }) { host.backend.resumeHitl(bot, conversation, request.pendingId, decisions) }
    }

    private fun stream(
        bot: BotProfile,
        before: List<ChatMessage>,
        resume: Boolean = false,
        onFailure: () -> Unit = {},
        events: suspend () -> Flow<StreamEvent>,
    ) {
        // Each run has its own token: a cancelled older run can never end a newer one.
        val token = ++run
        resumed = resume
        val reply = ChatMessage(role = MessageRole.Assistant, text = "", status = MessageStatus.Streaming)
        _state.update { it.copy(messages = it.messages + before + reply, streaming = true, motion = BotMotion.Working) }
        host.replyStarted(botId)
        job = scope.launch {
            var status: MessageStatus = MessageStatus.Done
            try {
                events().collect { event -> if (token == run) apply(reply.id, event) }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Throwable) {
                status = MessageStatus.Failed((error as? ApiException)?.message)
                if (token == run) onFailure()
                report(error)
            } finally {
                finish(reply.id, status, bot, token)
            }
        }
    }

    private fun apply(replyId: String, event: StreamEvent) {
        if (event is StreamEvent.Conversation) {
            _state.update { it.copy(conversationId = event.id) }
            return
        }
        if (event is StreamEvent.Hitl) {
            _state.update { it.copy(hitl = event.request) }
            return
        }
        _state.update { state ->
            var motion = state.motion
            val messages = state.messages.map { message ->
                if (message.id != replyId) return@map message
                when (event) {
                    is StreamEvent.Text -> message.copy(text = message.text + event.delta).also { motion = BotMotion.Working }
                    is StreamEvent.Thinking -> message.copy(thinking = message.thinking + event.delta).also { motion = BotMotion.Thinking }
                    is StreamEvent.Tool -> message.copy(tools = upsert(message.tools, event))
                    is StreamEvent.Conversation, is StreamEvent.Hitl -> message
                }
            }
            state.copy(messages = messages, motion = motion)
        }
    }

    private fun upsert(tools: List<ToolStep>, event: StreamEvent.Tool): List<ToolStep> {
        val index = tools.indexOfFirst { it.id == event.id }
        if (index < 0) return tools + ToolStep(event.id, event.name, event.done)
        return tools.toMutableList().also { it[index] = it[index].copy(done = it[index].done || event.done) }
    }

    private fun finish(replyId: String, status: MessageStatus, bot: BotProfile, token: Int) {
        val current = token == run
        var finalText = ""
        _state.update { state ->
            val messages = state.messages.mapNotNull { message ->
                if (message.id != replyId) return@mapNotNull message
                finalText = message.text
                // A stopped reply with no output leaves nothing behind.
                if (status == MessageStatus.Done && message.text.isEmpty() && message.tools.isEmpty() && message.thinking.isEmpty()) {
                    null
                } else {
                    // Finished, failed or stopped: no tool step keeps spinning.
                    message.copy(status = status, tools = message.tools.map { it.copy(done = true) })
                }
            }
            if (current) state.copy(messages = messages, streaming = false, motion = restingMotion(messages)) else state.copy(messages = messages)
        }
        if (!current) return
        job = null
        host.replyEnded(bot, replyId, finalText.takeIf { status == MessageStatus.Done && it.isNotBlank() })
        refreshConversations()
        // Success, failure or stop: the next queued message goes now.
        val (next, rest) = SendQueue.next(_state.value.queued)
        if (next != null) {
            _state.update { it.copy(queued = rest) }
            send(next.text, next.images)
        }
    }

    fun stop() {
        val running = job ?: return
        val bot = bot
        val conversation = _state.value.conversationId
        // A resumed turn streams over HTTP, not the socket: dropping the stream is the stop.
        if (conversation == null || bot == null || resumed) {
            running.cancel()
            return
        }
        scope.launch {
            host.backend.stop(conversation, bot)
            // If the backend doesn't end the turn promptly, drop the stream.
            delay(5_000)
            if (job === running) running.cancel()
        }
    }

    /** Resend the last user message after removing the reply to it. */
    fun retry() {
        val state = _state.value
        if (state.streaming) return
        val lastUser = state.messages.indexOfLast { it.role == MessageRole.User }
        if (lastUser < 0) return
        val text = state.messages[lastUser].text
        _state.update { it.copy(messages = it.messages.take(lastUser)) }
        startTurn(text, lastAttachments)
    }

    private fun report(error: Throwable) {
        if (error !is CancellationException) host.failed(error)
    }

    companion object {
        /** A reply that ends with a question waits for the user (`waiting` nod); otherwise idle. */
        fun restingMotion(messages: List<ChatMessage>): BotMotion {
            val last = messages.lastOrNull() ?: return BotMotion.Idle
            val asks = last.role == MessageRole.Assistant && last.status == MessageStatus.Done &&
                last.text.trimEnd().let { it.endsWith("?") || it.endsWith("？") }
            return if (asks) BotMotion.Waiting else BotMotion.Idle
        }
    }
}
