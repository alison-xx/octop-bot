package io.github.alisonxx.octopbot.net

import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.ChatMessage
import io.github.alisonxx.octopbot.model.ConversationSummary
import io.github.alisonxx.octopbot.model.HitlDecision
import io.github.alisonxx.octopbot.model.HitlRequest
import io.github.alisonxx.octopbot.model.ImageAttachment
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.model.ModelOption
import io.github.alisonxx.octopbot.model.StreamEvent
import io.github.alisonxx.octopbot.model.VoiceSupport
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow

/** A conversation's messages and its open question or approval, if any. */
data class Transcript(val messages: List<ChatMessage>, val pending: HitlRequest?)

/** Where this phone talks to: the Lynxce cloud with a personal account, or a self-hosted Octop server. */
interface ChatBackend {
    /** Lynxce mode: Bots live on the phone and can be created with a persona. */
    val definesBotsLocally: Boolean
    val supportsGroups: Boolean
    /** The person's display name; null when there is none (the UI says "Lynxce user"). */
    val accountName: String?
    /** Shown under Settings → Connection. */
    val connectionLabel: String

    suspend fun bots(): List<BotProfile>
    suspend fun conversations(bot: BotProfile): List<ConversationSummary>
    suspend fun messages(conversation: ConversationSummary, bot: BotProfile): List<ChatMessage>

    /** Messages plus a question or approval still open in the conversation (server mode only). */
    suspend fun transcript(conversation: ConversationSummary, bot: BotProfile): Transcript =
        Transcript(messages(conversation, bot), pending = null)
    suspend fun models(): List<ModelOption>

    /** Stream one reply. The first event is [StreamEvent.Conversation] when a new conversation was created. */
    fun send(
        text: String,
        images: List<ImageAttachment>,
        bot: BotProfile,
        conversation: String?,
        history: List<ChatMessage>,
        model: String?,
    ): Flow<StreamEvent>

    suspend fun stop(conversation: String, bot: BotProfile)

    /** Server mode: answer a paused turn (one decision per action) and stream the continuation as a new reply. */
    fun resumeHitl(bot: BotProfile, conversation: String, pendingId: String?, decisions: List<HitlDecision>): Flow<StreamEvent> =
        emptyFlow()
    suspend fun deleteConversation(conversation: ConversationSummary, bot: BotProfile)
    suspend fun setLook(bot: BotProfile, look: Look)

    suspend fun voiceSupport(): VoiceSupport
    /** Recorded audio (AAC in MP4) → text. Only called when [voiceSupport] reports `stt`. */
    suspend fun transcribe(audio: ByteArray): String
    /** Text → MP3 bytes. Only called when [voiceSupport] reports `tts`. */
    suspend fun speech(text: String): ByteArray

    /** Android v1 has no remote push (no Firebase); finished replies use local notifications. */
    suspend fun registerPush(token: String) = Unit
    suspend fun signOut()
}
