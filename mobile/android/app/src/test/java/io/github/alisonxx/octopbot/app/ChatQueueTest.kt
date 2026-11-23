package io.github.alisonxx.octopbot.app

import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.ChatMessage
import io.github.alisonxx.octopbot.model.ConversationSummary
import io.github.alisonxx.octopbot.model.HitlTexts
import io.github.alisonxx.octopbot.model.ImageAttachment
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.model.MessageRole
import io.github.alisonxx.octopbot.model.ModelOption
import io.github.alisonxx.octopbot.model.StreamEvent
import io.github.alisonxx.octopbot.model.ToolStep
import io.github.alisonxx.octopbot.model.VoiceSupport
import io.github.alisonxx.octopbot.net.ChatBackend
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatQueueTest {
    @Test
    fun queueIsFirstInFirstOutAndCancellable() {
        val a = QueuedMessage(text = "a")
        val b = QueuedMessage(text = "b")
        val c = QueuedMessage(text = "c")
        val queue = SendQueue.enqueue(SendQueue.enqueue(SendQueue.enqueue(emptyList(), a), b), c)
        assertEquals(listOf(a, c), SendQueue.cancel(queue, b.id))
        val (first, rest) = SendQueue.next(queue)
        assertEquals(a, first)
        assertEquals(listOf(b, c), rest)
        assertEquals(null to emptyList<QueuedMessage>(), SendQueue.next(emptyList()))
    }

    /** A backend whose replies end only when the test says so. */
    private class Backend : ChatBackend {
        val sent = mutableListOf<String>()
        val replies = mutableListOf<CompletableDeferred<String>>()
        override val definesBotsLocally = true
        override val supportsGroups = false
        override val accountName = "me"
        override val connectionLabel = "test"
        override suspend fun bots() = emptyList<BotProfile>()
        override suspend fun conversations(bot: BotProfile) = emptyList<ConversationSummary>()
        override suspend fun messages(conversation: ConversationSummary, bot: BotProfile) = emptyList<ChatMessage>()
        override suspend fun models() = emptyList<ModelOption>()
        override fun send(
            text: String,
            images: List<ImageAttachment>,
            bot: BotProfile,
            conversation: String?,
            history: List<ChatMessage>,
            model: String?,
        ): Flow<StreamEvent> = flow {
            sent += text
            val reply = CompletableDeferred<String>().also { replies += it }
            emit(StreamEvent.Tool("t-$text", "web_search", done = false))
            emit(StreamEvent.Text(reply.await()))
        }
        override suspend fun stop(conversation: String, bot: BotProfile) = Unit
        override suspend fun deleteConversation(conversation: ConversationSummary, bot: BotProfile) = Unit
        override suspend fun setLook(bot: BotProfile, look: Look) = Unit
        override suspend fun voiceSupport() = VoiceSupport(stt = false, tts = false)
        override suspend fun transcribe(audio: ByteArray) = ""
        override suspend fun speech(text: String) = ByteArray(0)
        override suspend fun signOut() = Unit
    }

    private class Host(override val backend: ChatBackend) : ChatHost {
        private val bot = BotProfile("b", "Bot", look = Look.fallback)
        override fun bot(id: String) = bot
        override suspend fun model(): String? = null
        override fun replyStarted(botId: String) = Unit
        override fun replyEnded(bot: BotProfile, messageId: String, text: String?) = Unit
        override fun failed(error: Throwable) = Unit
        override val hitlTexts = HitlTexts("decide", "closed", { "Approved: $it" }, { "Declined: $it" })
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    @Test
    fun messagesSentDuringAReplyGoOutInOrderWhenItEnds() = runTest {
        val backend = Backend()
        val chat = ChatSession("b", this, Host(backend))
        chat.send("first", emptyList())
        runCurrent()
        chat.send("second", emptyList())
        chat.send("third", emptyList())
        chat.send("dropped", emptyList())
        chat.cancelQueued(chat.state.value.queued.last().id)
        assertEquals(listOf("second", "third"), chat.state.value.queued.map { it.text })
        assertEquals(listOf("first"), backend.sent)

        backend.replies[0].complete("one")
        runCurrent()
        assertEquals(listOf("first", "second"), backend.sent)
        assertEquals(listOf("third"), chat.state.value.queued.map { it.text })
        assertTrue(chat.state.value.streaming)
        // The finished reply's tool step no longer spins.
        assertEquals(listOf(ToolStep("t-first", "web_search", done = true)), chat.state.value.messages[1].tools)

        // Stopping (cancelling) a reply also sends the next one.
        chat.stop()
        runCurrent()
        assertEquals(listOf("first", "second", "third"), backend.sent)
        backend.replies[2].complete("three")
        runCurrent()
        assertFalse(chat.state.value.streaming)
        assertEquals(
            listOf("first", "one", "second", "third", "three"),
            chat.state.value.messages.filter { it.text.isNotEmpty() }.map { it.text },
        )
        assertEquals(MessageRole.Assistant, chat.state.value.messages.last().role)
    }
}
