package io.github.alisonxx.octopbot.net

import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.ChatMessage
import io.github.alisonxx.octopbot.model.ConversationSummary
import io.github.alisonxx.octopbot.model.MessageRole
import io.github.alisonxx.octopbot.model.ModelOption
import io.github.alisonxx.octopbot.model.VoiceSupport
import io.github.alisonxx.octopbot.store.LocalBots
import kotlinx.coroutines.cancel
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonObject
import okhttp3.Request
import java.io.File
import java.util.UUID

/**
 * Used without signing in: the Bots live on this phone and chat goes straight to the model the user set up here (their
 * own vendor API key, or a model server on their network). Nothing goes through Lynxce or Octop Bot cloud, and
 * conversations stay on this phone.
 */
class DeviceBackend(
    localBots: LocalBots,
    private val phoneModels: PhoneModels,
    private val store: DeviceConversations,
    override val accountName: String?,
) : PhoneChat(localBots, phoneModels) {
    override val connectionLabel: String = ""

    override suspend fun conversations(bot: BotProfile): List<ConversationSummary> = store.conversations(bot.id)

    override suspend fun messages(conversation: ConversationSummary, bot: BotProfile): List<ChatMessage> =
        store.messages(conversation.id)

    override suspend fun deleteConversation(conversation: ConversationSummary, bot: BotProfile) = store.delete(conversation.id)

    /** The model is chosen in Settings → Models, not per chat. */
    override suspend fun models(): List<ModelOption> = emptyList()

    override fun newSessionId(): String = "device-" + UUID.randomUUID().toString()

    override suspend fun started(sessionId: String, bot: BotProfile, text: String) = store.create(sessionId, bot.id, text)

    override fun finished(sessionId: String, user: String, startedAt: Long, answer: String, thinking: String, model: String?) =
        store.append(sessionId, user, startedAt, answer.trim(), thinking)

    /** No Lynxce here: a chat without a model set up asks for one. */
    override suspend fun gatewayRequest(body: JsonObject, renew: Boolean): Request =
        throw ModelSourceException(ModelSourceException.Reason.NoModel)

    // The phone's own speech recognition and voice are used instead.
    override suspend fun voiceSupport() = VoiceSupport(stt = false, tts = false)
    override suspend fun transcribe(audio: ByteArray): String = ""
    override suspend fun speech(text: String): ByteArray = ByteArray(0)

    /** Leaving phone-only use keeps the keys and conversations here for next time. */
    override suspend fun signOut() {
        cancelAll()
        background.cancel()
    }
}

/** Conversations of phone-only use, kept in one JSON file in the app's files. */
class DeviceConversations(private val file: File) {
    @Serializable
    data class Message(val role: String, val text: String, val thinking: String? = null, val createdAt: Long)

    @Serializable
    data class Stored(val id: String, val botId: String, val title: String, val updatedAt: Long, val messages: List<Message>)

    private val serializer = ListSerializer(Stored.serializer())
    private var all: List<Stored> = runCatching { Http.json.decodeFromString(serializer, file.readText()) }.getOrDefault(emptyList())

    @Synchronized
    fun conversations(bot: String): List<ConversationSummary> =
        all.filter { it.botId == bot }.sortedByDescending { it.updatedAt }.map { ConversationSummary(it.id, it.title, it.updatedAt, it.botId) }

    @Synchronized
    fun messages(id: String): List<ChatMessage> = all.firstOrNull { it.id == id }?.messages.orEmpty().map {
        ChatMessage(
            role = if (it.role == "user") MessageRole.User else MessageRole.Assistant,
            text = it.text,
            thinking = it.thinking.orEmpty(),
            createdAt = it.createdAt,
        )
    }

    @Synchronized
    fun create(id: String, bot: String, title: String) {
        if (all.any { it.id == id }) return
        val line = title.trim().lineSequence().firstOrNull().orEmpty().take(40)
        all = all + Stored(id, bot, line, System.currentTimeMillis(), emptyList())
        save()
    }

    @Synchronized
    fun append(id: String, user: String, startedAt: Long, answer: String, thinking: String) {
        val index = all.indexOfFirst { it.id == id }.takeIf { it >= 0 } ?: return
        val now = System.currentTimeMillis()
        val added = listOfNotNull(
            Message("user", user, null, startedAt),
            answer.takeIf { it.isNotEmpty() }?.let { Message("assistant", it, thinking.ifEmpty { null }, now) },
        )
        all = all.toMutableList().also { it[index] = it[index].copy(updatedAt = now, messages = it[index].messages + added) }
            .sortedByDescending { it.updatedAt }
            .take(LIMIT)
        save()
    }

    @Synchronized
    fun delete(id: String) {
        all = all.filterNot { it.id == id }
        save()
    }

    private fun save() {
        file.parentFile?.mkdirs()
        val temp = File(file.parentFile, file.name + ".tmp")
        temp.writeText(Http.json.encodeToString(serializer, all))
        temp.renameTo(file)
    }

    private companion object {
        const val LIMIT = 200
    }
}
