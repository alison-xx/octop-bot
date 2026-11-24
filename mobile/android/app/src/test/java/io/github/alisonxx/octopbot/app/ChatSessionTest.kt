package io.github.alisonxx.octopbot.app

import io.github.alisonxx.octopbot.model.BotMotion
import io.github.alisonxx.octopbot.model.ChatMessage
import io.github.alisonxx.octopbot.model.MessageRole
import io.github.alisonxx.octopbot.model.MessageStatus
import org.junit.Assert.assertEquals
import org.junit.Test

class ChatSessionTest {
    @org.junit.Test
    fun lowBalanceDismissalLasts24Hours() {
        org.junit.Assert.assertTrue(lowBalanceIsDismissed(1_000, 1_000 + LOW_BALANCE_DISMISSAL_MS - 1))
        org.junit.Assert.assertFalse(lowBalanceIsDismissed(1_000, 1_000 + LOW_BALANCE_DISMISSAL_MS))
        org.junit.Assert.assertFalse(lowBalanceIsDismissed(null, 1_000))
    }

    @Test
    fun aReplyThatAsksWaitsForTheUser() {
        fun reply(text: String, status: MessageStatus = MessageStatus.Done) =
            listOf(ChatMessage(role = MessageRole.Assistant, text = text, status = status))
        assertEquals(BotMotion.Waiting, ChatSession.restingMotion(reply("Which one do you prefer?")))
        assertEquals(BotMotion.Waiting, ChatSession.restingMotion(reply("要继续吗？ ")))
        assertEquals(BotMotion.Idle, ChatSession.restingMotion(reply("Done.")))
        assertEquals(BotMotion.Idle, ChatSession.restingMotion(reply("Why?", MessageStatus.Failed(null))))
        assertEquals(BotMotion.Idle, ChatSession.restingMotion(emptyList()))
    }
}
