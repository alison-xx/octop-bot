package io.github.alisonxx.octopbot.app

import io.github.alisonxx.octopbot.model.GroupMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class GroupTimelineTest {
    private fun row(id: String, text: String, role: String = "user", requestId: String? = null) =
        GroupMessage(id, role, if (role == "user") null else "bot", text, createdAt = 1, requestId = requestId)

    @Test
    fun echoDropsOnceItsRequestIdIsListed() {
        val mine = GroupPost("r1", "hello", emptyList(), createdAt = 1)
        val other = GroupPost("r2", "hello", emptyList(), createdAt = 2)
        var state = GroupRoomState(pending = listOf(mine, other))
        state = GroupTimeline.merge(state, listOf(row("1", "hello", requestId = "r1"), row("2", "hi there", "assistant", "r1")))
        // Same text, different request: the second echo stays until its own row arrives.
        assertEquals(listOf("r2"), state.pending.map { it.requestId })
        assertEquals(listOf("1", "2"), state.messages.map { it.id })
        // A repeated poll never duplicates rows.
        state = GroupTimeline.merge(state, listOf(row("2", "hi there", "assistant", "r1"), row("3", "hello", requestId = "r2")))
        assertEquals(listOf("1", "2", "3"), state.messages.map { it.id })
        assertEquals(emptyList<GroupPost>(), state.pending)
    }

    @Test
    fun withoutRequestIdsAUserRowWithTheSameTextClearsTheEcho() {
        val state = GroupTimeline.merge(
            GroupRoomState(pending = listOf(GroupPost("r1", "hello", emptyList(), 1, failed = false))),
            listOf(row("9", "hello")),
        )
        assertEquals(emptyList<GroupPost>(), state.pending)
    }

    @Test
    fun cursorIsTheLastServerRowNeverAnEcho() {
        val empty = GroupRoomState(pending = listOf(GroupPost("r1", "hello", emptyList(), 1, failed = true)))
        assertNull(GroupTimeline.cursor(empty))
        assertEquals("7", GroupTimeline.cursor(empty.copy(messages = listOf(row("5", "a"), row("7", "b")))))
    }
}
