package io.github.alisonxx.octopbot.model

import kotlinx.serialization.Serializable
import java.util.UUID

/** The character a Bot wears: a DS Bot shape and an ink, or the Chief octopus. */
@Serializable
data class Look(val shape: String, val color: String) {
    val isOctopus: Boolean get() = shape == OCTOPUS

    companion object {
        const val OCTOPUS = "octop"
        val chief = Look(OCTOPUS, "rose")
        val fallback = Look("gumdrop", "blue")
    }
}

@Serializable
data class BotProfile(
    val id: String,
    val name: String,
    val subtitle: String? = null,
    val look: Look,
    val isChief: Boolean = false,
    /** Persona for Lynxce-account Bots; server Bots keep their prompt on the server. */
    val systemPrompt: String? = null,
    /** True for Bots defined on this phone (Lynxce mode); they can be edited and deleted. */
    val isLocal: Boolean = false,
)

data class ConversationSummary(
    val id: String,
    val title: String,
    /** Epoch milliseconds. */
    val updatedAt: Long?,
    val botId: String?,
)

/** [Note] is a centered caption in the timeline (e.g. "Approved: …"); it is never sent to a model. */
enum class MessageRole { User, Assistant, Note }

sealed interface MessageStatus {
    data object Done : MessageStatus
    data object Streaming : MessageStatus
    /** [message] is null when the UI should show its generic failure text. */
    data class Failed(val message: String?) : MessageStatus
}

data class ToolStep(val id: String, val name: String, val done: Boolean)

data class ChatMessage(
    val id: String = UUID.randomUUID().toString(),
    val role: MessageRole,
    val text: String,
    val thinking: String = "",
    /** Content URIs or remote URLs, shown as thumbnails. */
    val images: List<String> = emptyList(),
    val tools: List<ToolStep> = emptyList(),
    /** Files the Bot sent (server mode); links to files in [text] become cards too. */
    val attachments: List<FileAttachment> = emptyList(),
    val status: MessageStatus = MessageStatus.Done,
    val createdAt: Long = System.currentTimeMillis(),
)

/** A photo ready to send: JPEG bytes plus the URI it was picked from (for display). */
class ImageAttachment(val uri: String, val jpeg: ByteArray)

/** Incremental output of one reply. */
sealed interface StreamEvent {
    data class Conversation(val id: String) : StreamEvent
    data class Text(val delta: String) : StreamEvent
    data class Thinking(val delta: String) : StreamEvent
    data class Tool(val id: String, val name: String, val done: Boolean) : StreamEvent
    /** Server mode: a file the Bot sent (`attachment` frame). */
    data class Attachment(val file: FileAttachment) : StreamEvent
    /** Server mode: the turn paused for a question or an approval. */
    data class Hitl(val request: HitlRequest) : StreamEvent
}

data class ModelOption(val id: String, val name: String, val supportsImage: Boolean)

@Serializable
data class GroupSummary(
    val id: String,
    val name: String,
    val adminId: String?,
    val memberIds: List<String>,
)

data class GroupMessage(
    val id: String,
    val role: String,
    val agentId: String?,
    val text: String,
    val createdAt: Long,
    /** The `request_id` of the post that produced this row, when the server reports it. */
    val requestId: String? = null,
)

data class GroupDraft(val agentId: String, val text: String)

data class GroupGoal(val title: String, val status: String)

/** Which speech services a backend offers; when false the phone uses on-device recognition/synthesis. */
data class VoiceSupport(val stt: Boolean, val tts: Boolean)

enum class BotMotion { Idle, Working, Thinking, Searching, Waiting }
