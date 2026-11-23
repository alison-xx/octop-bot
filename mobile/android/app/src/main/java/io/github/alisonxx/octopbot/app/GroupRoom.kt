package io.github.alisonxx.octopbot.app

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import io.github.alisonxx.octopbot.model.GroupDraft
import io.github.alisonxx.octopbot.model.GroupGoal
import io.github.alisonxx.octopbot.model.GroupMessage
import io.github.alisonxx.octopbot.net.Mentions
import io.github.alisonxx.octopbot.net.ServerBackend
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.util.UUID

/** A message posted from this phone, shown until the server lists it. */
data class GroupPost(
    val requestId: String,
    val text: String,
    val mentionIds: List<String>,
    val createdAt: Long,
    /** The post failed; tapping retries it with the same [requestId], so the server never doubles it. */
    val failed: Boolean = false,
) {
    val id: String get() = "local-$requestId"
}

data class GroupRoomState(
    /** Server rows only, ascending; the last one's id is the poll cursor. */
    val messages: List<GroupMessage> = emptyList(),
    val drafts: List<GroupDraft> = emptyList(),
    /** Posts from this phone that the server has not listed yet. */
    val pending: List<GroupPost> = emptyList(),
    val goal: GroupGoal? = null,
    val memory: String = "",
)

/** Pure merge of polled rows into the room (unit tested). */
object GroupTimeline {
    /**
     * Appends unseen [fresh] rows and drops each local echo once the server lists its post: a row with the
     * same `request_id`, or (servers that don't report it) a user row with the same text.
     */
    fun merge(state: GroupRoomState, fresh: List<GroupMessage>): GroupRoomState {
        val known = state.messages.map { it.id }.toSet()
        val messages = state.messages + fresh.filter { it.id !in known }
        val listed = fresh.mapNotNull { it.requestId }.toSet()
        val pending = state.pending.filterNot { post ->
            post.requestId in listed || fresh.any { it.role == "user" && it.requestId == null && it.text == post.text }
        }
        return state.copy(messages = messages, pending = pending)
    }

    /** The `after_id` cursor: the last server message, never a local echo. */
    fun cursor(state: GroupRoomState): String? = state.messages.lastOrNull()?.id
}

/**
 * A server group room. Polled, no socket: messages + drafts every 2.5 s while Bots are replying or right
 * after sending, otherwise every 10 s. Sending never waits for earlier posts.
 */
class GroupRoom(private val server: ServerBackend, private val groupId: String, private val host: ChatHost) : ViewModel() {
    private val _state = MutableStateFlow(GroupRoomState())
    val state: StateFlow<GroupRoomState> = _state
    private var fastUntil = 0L
    private var inFlight = 0

    init {
        viewModelScope.launch { poll() }
    }

    private suspend fun poll() {
        while (true) {
            try {
                refresh()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Throwable) {
                host.failed(error)
                delay(10_000)
                continue
            }
            val busy = inFlight > 0 || _state.value.drafts.isNotEmpty() || System.currentTimeMillis() < fastUntil
            delay(if (busy) 2_500 else 10_000)
        }
    }

    private suspend fun refresh() {
        val fresh = server.groupMessages(groupId, GroupTimeline.cursor(_state.value))
        val drafts = server.groupDrafts(groupId)
        _state.update { GroupTimeline.merge(it, fresh).copy(drafts = drafts.filter { draft -> draft.text.isNotBlank() }) }
    }

    fun loadInfo() {
        viewModelScope.launch {
            runCatching {
                val goal = server.groupGoal(groupId)
                val memory = server.groupMemory(groupId)
                _state.update { it.copy(goal = goal, memory = memory) }
            }.onFailure(host::failed)
        }
    }

    /** Returns false when there was nothing to send. */
    fun send(text: String, members: List<Mentions.Member>): Boolean {
        val body = text.trim()
        if (body.isEmpty()) return false
        val post = GroupPost(UUID.randomUUID().toString(), body, Mentions.resolve(body, members), System.currentTimeMillis())
        _state.update { it.copy(pending = it.pending + post) }
        deliver(post)
        return true
    }

    /** Try a failed post again with the same request id. */
    fun retry(requestId: String) {
        val post = _state.value.pending.firstOrNull { it.requestId == requestId && it.failed } ?: return
        mark(requestId, failed = false)
        deliver(post.copy(failed = false))
    }

    private fun deliver(post: GroupPost) {
        inFlight++
        viewModelScope.launch {
            // The post blocks until every addressed Bot has replied; polling shows drafts meanwhile.
            runCatching { server.postGroupMessage(groupId, post.requestId, post.text, post.mentionIds) }
                .onFailure {
                    mark(post.requestId, failed = true)
                    host.failed(it)
                }
            inFlight--
            fastUntil = System.currentTimeMillis() + 15_000
            runCatching { refresh() }
        }
    }

    private fun mark(requestId: String, failed: Boolean) {
        _state.update { state ->
            state.copy(pending = state.pending.map { if (it.requestId == requestId) it.copy(failed = failed) else it })
        }
    }
}
