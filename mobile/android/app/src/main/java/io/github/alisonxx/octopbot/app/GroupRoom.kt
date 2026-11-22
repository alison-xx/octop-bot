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

data class GroupRoomState(
    val messages: List<GroupMessage> = emptyList(),
    val drafts: List<GroupDraft> = emptyList(),
    /** Messages posted from this phone that the server has not listed yet. */
    val pending: List<GroupMessage> = emptyList(),
    val goal: GroupGoal? = null,
    val memory: String = "",
)

/**
 * A server group room. Polled, no socket: messages + drafts every 2.5 s while Bots are replying or right
 * after sending, otherwise every 10 s.
 */
class GroupRoom(private val server: ServerBackend, private val groupId: String, private val host: ChatHost) : ViewModel() {
    private val _state = MutableStateFlow(GroupRoomState())
    val state: StateFlow<GroupRoomState> = _state
    private var fastUntil = 0L
    private var sending = 0

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
            val busy = sending > 0 || _state.value.drafts.isNotEmpty() || System.currentTimeMillis() < fastUntil
            delay(if (busy) 2_500 else 10_000)
        }
    }

    private suspend fun refresh() {
        val after = _state.value.messages.lastOrNull()?.id
        val fresh = server.groupMessages(groupId, after)
        val drafts = server.groupDrafts(groupId)
        _state.update { state ->
            val known = state.messages.map { it.id }.toSet()
            val messages = state.messages + fresh.filter { it.id !in known }
            // A pending message is done once the server lists a user message with the same text.
            val pending = state.pending.filterNot { mine -> fresh.any { it.role == "user" && it.text == mine.text } }
            state.copy(messages = messages, drafts = drafts.filter { it.text.isNotBlank() }, pending = pending)
        }
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

    fun send(text: String, members: List<Mentions.Member>) {
        val body = text.trim()
        if (body.isEmpty()) return
        val requestId = UUID.randomUUID().toString()
        val local = GroupMessage("local-$requestId", "user", null, body, System.currentTimeMillis())
        _state.update { it.copy(pending = it.pending + local) }
        sending++
        viewModelScope.launch {
            // The post blocks until every addressed Bot has replied; polling shows drafts meanwhile.
            runCatching { server.postGroupMessage(groupId, requestId, body, Mentions.resolve(body, members)) }
                .onFailure {
                    _state.update { state -> state.copy(pending = state.pending - local) }
                    host.failed(it)
                }
            sending--
            fastUntil = System.currentTimeMillis() + 15_000
            runCatching { refresh() }
        }
    }
}
