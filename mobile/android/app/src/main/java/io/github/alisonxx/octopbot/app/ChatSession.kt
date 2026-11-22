package io.github.alisonxx.octopbot.app

import io.github.alisonxx.octopbot.model.BotMotion
import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.ChatMessage
import io.github.alisonxx.octopbot.model.ConversationSummary
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
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class ChatState(
    val conversationId: String? = null,
    val messages: List<ChatMessage> = emptyList(),
    val streaming: Boolean = false,
    val loading: Boolean = false,
    val conversations: List<ConversationSummary> = emptyList(),
    val motion: BotMotion = BotMotion.Idle,
)

/** What a chat needs from the app around it. */
interface ChatHost {
    val backend: ChatBackend
    fun bot(id: String): BotProfile?
    suspend fun model(): String?
    fun replyStarted(botId: String)
    /** [text] is the finished reply, or null when it failed or produced nothing. */
    fun replyEnded(bot: BotProfile, text: String?)
    fun failed(error: Throwable)
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
        _state.update { it.copy(conversationId = conversation.id, messages = emptyList(), loading = true) }
        val messages = runCatching { host.backend.messages(conversation, bot) }.onFailure(::report).getOrDefault(emptyList())
        _state.update { it.copy(messages = messages, loading = false, motion = restingMotion(messages)) }
    }

    fun newChat() {
        if (_state.value.streaming) return
        _state.update { it.copy(conversationId = null, messages = emptyList(), loading = false, motion = BotMotion.Idle) }
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

    fun send(text: String, images: List<ImageAttachment>) {
        val bot = bot ?: return
        val state = _state.value
        if (state.streaming || (text.isBlank() && images.isEmpty())) return
        lastAttachments = images
        val history = state.messages
        val user = ChatMessage(role = MessageRole.User, text = text.trim(), images = images.map { it.uri })
        val reply = ChatMessage(role = MessageRole.Assistant, text = "", status = MessageStatus.Streaming)
        _state.update { it.copy(messages = it.messages + user + reply, streaming = true, motion = BotMotion.Working) }
        host.replyStarted(botId)
        job = scope.launch {
            var status: MessageStatus = MessageStatus.Done
            try {
                host.backend.send(user.text, images, bot, state.conversationId, history, host.model()).collect { event ->
                    apply(reply.id, event)
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Throwable) {
                status = MessageStatus.Failed((error as? ApiException)?.message)
                report(error)
            } finally {
                finish(reply.id, status, bot)
            }
        }
    }

    private fun apply(replyId: String, event: StreamEvent) {
        if (event is StreamEvent.Conversation) {
            _state.update { it.copy(conversationId = event.id) }
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
                    is StreamEvent.Conversation -> message
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

    private fun finish(replyId: String, status: MessageStatus, bot: BotProfile) {
        var finalText = ""
        _state.update { state ->
            val messages = state.messages.mapNotNull { message ->
                if (message.id != replyId) return@mapNotNull message
                finalText = message.text
                // A stopped reply with no output leaves nothing behind.
                if (status == MessageStatus.Done && message.text.isEmpty() && message.tools.isEmpty() && message.thinking.isEmpty()) {
                    null
                } else {
                    message.copy(status = status, tools = message.tools.map { it.copy(done = true) })
                }
            }
            state.copy(messages = messages, streaming = false, motion = restingMotion(messages))
        }
        job = null
        host.replyEnded(bot, finalText.takeIf { status == MessageStatus.Done && it.isNotBlank() })
        refreshConversations()
    }

    fun stop() {
        val running = job ?: return
        val bot = bot
        val conversation = _state.value.conversationId
        if (conversation == null || bot == null) {
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
        send(text, lastAttachments)
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
