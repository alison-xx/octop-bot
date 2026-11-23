package io.github.alisonxx.octopbot.net

import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.ChatMessage
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.model.MessageRole
import io.github.alisonxx.octopbot.model.MessageStatus
import io.github.alisonxx.octopbot.model.StreamEvent
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class LynxceProtocolTest {
    @Test
    fun parsesContentAndReasoningDeltas() {
        assertEquals(
            listOf(StreamEvent.Thinking("hmm"), StreamEvent.Text("Hi")),
            LynxceProtocol.parseChunk("""{"choices":[{"delta":{"content":"Hi","reasoning_content":"hmm"}}]}"""),
        )
        assertEquals(listOf(StreamEvent.Text("x")), LynxceProtocol.parseChunk("""{"choices":[{"delta":{"content":"x"}}]}"""))
        // Usage-only chunks, empty deltas and the [DONE] sentinel produce nothing.
        assertEquals(emptyList<StreamEvent>(), LynxceProtocol.parseChunk("""{"choices":[],"usage":{"total_tokens":9}}"""))
        assertEquals(emptyList<StreamEvent>(), LynxceProtocol.parseChunk("""{"choices":[{"delta":{"content":""}}]}"""))
        assertEquals(emptyList<StreamEvent>(), LynxceProtocol.parseChunk("[DONE]"))
    }

    @Test
    fun errorChunkThrows() {
        try {
            LynxceProtocol.parseChunk("""{"error":{"message":"quota exceeded","code":402}}""")
            fail("expected failure")
        } catch (error: ApiException) {
            assertEquals("quota exceeded", error.message)
        }
        try {
            LynxceProtocol.parseChunk("""{"error":"bad"}""")
            fail("expected failure")
        } catch (error: ApiException) {
            assertEquals("bad", error.message)
        }
    }

    @Test
    fun unwrapsEnvelope() {
        val data = LynxceProtocol.unwrap(200, """{"code":0,"data":{"accessToken":"a"}}""")
        assertEquals("a", data.jsonObject["accessToken"]!!.jsonPrimitive.content)
        assertFailure(ApiException.Kind.Credits, 402) { LynxceProtocol.unwrap(200, """{"code":402,"message":"no credits"}""") }
        assertFailure(ApiException.Kind.Unauthorized, 401) { LynxceProtocol.unwrap(401, """{"code":401,"message":"expired"}""") }
        assertFailure(ApiException.Kind.Rejected, 400) { LynxceProtocol.unwrap(200, """{"code":10012,"message":"wrong password"}""") }
        assertFailure(ApiException.Kind.Server, 502) { LynxceProtocol.unwrap(200, "<html>") }
        assertFailure(ApiException.Kind.Server, 503) { LynxceProtocol.unwrap(503, "") }
    }

    private fun assertFailure(kind: ApiException.Kind, status: Int, block: () -> Unit) {
        try {
            block()
            fail("expected $kind")
        } catch (error: ApiException) {
            assertEquals(kind, error.kind)
            assertEquals(status, error.status)
        }
    }

    @Test
    fun chatBodyCarriesPersonaHistoryAndImages() {
        val bot = BotProfile("engineer", "Engineer", look = Look("beacon", "cobalt"), systemPrompt = "Be precise.")
        val history = (1..25).map { ChatMessage(role = if (it % 2 == 1) MessageRole.User else MessageRole.Assistant, text = "m$it") } +
            ChatMessage(role = MessageRole.Assistant, text = "broken", status = MessageStatus.Failed(null))
        val body = LynxceProtocol.chatBody("look", listOf(byteArrayOf(1, 2, 3)), bot, history, "octop-bot-v1-abc", "m1", turnId = "t")
        val messages = body["messages"]!!.jsonArray
        assertEquals("system", messages.first().jsonObject["role"]!!.jsonPrimitive.content)
        // System + the last 20 finished turns + the new user message.
        assertEquals(22, messages.size)
        assertEquals("m6", messages[1].jsonObject["content"]!!.jsonPrimitive.content)
        val content = messages.last().jsonObject["content"]!!.jsonArray
        assertEquals("look", content[0].jsonObject["text"]!!.jsonPrimitive.content)
        assertEquals("data:image/jpeg;base64,AQID", content[1].jsonObject["image_url"]!!.jsonObject["url"]!!.jsonPrimitive.content)
        assertEquals("octop-bot-v1-abc", body["sessionId"]!!.jsonPrimitive.content)
        assertEquals("m1", body["model"]!!.jsonPrimitive.content)
        assertEquals("octop-bot-android", body["metadata"]!!.jsonObject["client"]!!.jsonPrimitive.content)
        assertTrue(body["stream"]!!.jsonPrimitive.content.toBoolean())
        assertFalse("model omitted for auto", "model" in LynxceProtocol.chatBody("x", emptyList(), bot, emptyList(), "s", null))
    }

    @Test
    fun conversationsKeepOnlyOurPrefixAndOwner() {
        val data = Http.parse(
            """{"items":[
              {"id":"octop-bot-v1-1","title":"Plan\nmore","updatedAt":"2026-11-20T10:00:00Z"},
              {"id":"octop-bot-v1-2","title":"Code"},
              {"id":"web-3","title":"Other app"}
            ],"nextCursor":null}""",
        )
        val owners = mapOf("octop-bot-v1-2" to "engineer")
        val chief = LynxceProtocol.conversations(data, owners, "chief", "chief")
        assertEquals(listOf("octop-bot-v1-1"), chief.map { it.id })
        assertEquals("Plan", chief.single().title)
        assertEquals(1795168800000L, chief.single().updatedAt)
        assertEquals(listOf("octop-bot-v1-2"), LynxceProtocol.conversations(data, owners, "engineer", "chief").map { it.id })
        assertTrue(LynxceProtocol.newSessionId().matches(Regex("octop-bot-v1-[0-9a-f-]{36}")))
    }

    @Test
    fun messagesStripDesktopRoleBlock() {
        val data = Http.parse(
            """{"items":[
              {"role":"system","content":"persona"},
              {"role":"user","content":"hello\n\n[Octop Bot role/v1] {\"bot\":\"x\"}"},
              {"role":"assistant","content":"hi","thinking":"t","status":"failed"}
            ]}""",
        )
        val messages = LynxceProtocol.messages(data)
        assertEquals(listOf("hello", "hi"), messages.map { it.text })
        assertEquals("t", messages[1].thinking)
        assertEquals(MessageStatus.Failed(null), messages[1].status)
    }

    @Test
    fun syncBodyAndModelsAndBalance() {
        val sync = LynxceProtocol.syncBody("  question  ", 0, " answer ", "", null, 1000)
        assertEquals("question", sync["title"]!!.jsonPrimitive.content)
        assertEquals("auto", sync["model"]!!.jsonPrimitive.content)
        assertEquals("answer", sync["items"]!!.jsonArray[1].jsonObject["content"]!!.jsonPrimitive.content)
        assertEquals(1, LynxceProtocol.syncBody("q", 0, "  ", "", null, 0)["items"]!!.jsonArray.size)

        val models = LynxceProtocol.models(Http.parse("""{"items":[{"modelId":"a","modelName":"A","supportsImage":true},{"x":1}]}"""))
        assertEquals(listOf("a"), models.map { it.id })
        assertTrue(models.single().supportsImage)
        assertEquals(1, LynxceProtocol.models(Http.parse("""[{"modelId":"b"}]""")).size)

        assertEquals("12.5", LynxceProtocol.balance(Http.parse("""{"credits":12.5,"balance":null}""")))
        assertNull(LynxceProtocol.balance(Http.parse("""{"plan":"free"}""")))
    }
}
