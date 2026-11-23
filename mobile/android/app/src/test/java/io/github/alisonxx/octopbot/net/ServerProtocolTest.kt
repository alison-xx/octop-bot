package io.github.alisonxx.octopbot.net

import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.model.MessageRole
import io.github.alisonxx.octopbot.model.MessageStatus
import io.github.alisonxx.octopbot.model.StreamEvent
import io.github.alisonxx.octopbot.model.ToolStep
import io.github.alisonxx.octopbot.model.VoiceSupport
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class ServerProtocolTest {
    private fun obj(text: String) = Http.parse(text) as JsonObject

    @Test
    fun historyMergesAssistantSegmentsAndSkipsToolRows() {
        val page = ServerProtocol.historyPage(
            Http.parse(
                """{"messages":[
                  {"id":"u1","role":"user","content":"weather?","timestamp":1763600000000},
                  {"role":"assistant","content":[{"type":"thinking","thinking":"need search"},{"type":"tool_use","id":"t1","name":"web_search"}]},
                  {"role":"tool","content":[{"type":"text","text":"raw result"}]},
                  {"role":"assistant","content":[{"type":"text","text":"Sunny."}]},
                  {"role":"user","content":[{"type":"text","text":"photo"},{"type":"image","source":{"type":"url","url":"/files/a.jpg"}}]},
                  {"role":"assistant","content":"plain","status":"error"},
                  {"role":"assistant","content":[]}
                ],"history_loading":false,"turn_active":false}""",
            ),
        )
        val messages = page.messages
        assertEquals(4, messages.size)
        assertEquals(MessageRole.User, messages[0].role)
        assertEquals("u1", messages[0].id)
        assertEquals(1763600000000L, messages[0].createdAt)
        assertEquals("Sunny.", messages[1].text)
        assertEquals("need search", messages[1].thinking)
        assertEquals(listOf(ToolStep("t1", "web_search", done = true)), messages[1].tools)
        assertEquals(listOf("/files/a.jpg"), messages[2].images)
        // The failed plain reply follows a user message, so it stays separate; the empty one merges away.
        assertEquals("plain", messages[3].text)
        assertEquals(MessageStatus.Failed(null), messages[3].status)
    }

    @Test
    fun historyLoadingRetries() {
        val page = ServerProtocol.historyPage(Http.parse("""{"messages":[],"history_loading":true,"history_retry_after_ms":1200}"""))
        assertTrue(page.loading)
        assertEquals(1200L, page.retryAfterMs)
    }

    @Test
    fun frameMapperFollowsATurn() {
        val mapper = ServerProtocol.FrameMapper()
        fun map(frame: String) = mapper.map(obj(frame), "th1")
        fun events(frame: String) = (map(frame) as ServerProtocol.FrameMapper.Outcome.Events).events

        assertEquals(emptyList<StreamEvent>(), events("""{"type":"turn.started","turn_id":"x","thread_id":"th1"}"""))
        assertEquals(listOf(StreamEvent.Thinking("plan")), events("""{"type":"reasoning","content":"plan"}"""))
        assertEquals(listOf(StreamEvent.Tool("c1", "Web search", false)), events("""{"type":"tool_call_chunk","id":"c1","name":"web_search","display_name":"Web search"}"""))
        // Argument chunks for the same call don't repeat the step.
        assertEquals(emptyList<StreamEvent>(), events("""{"type":"tool_call_chunk","id":"c1","args":"{"}"""))
        assertEquals(listOf(StreamEvent.Tool("c1", "Web search", true)), events("""{"type":"tool_result","messages":[{"tool_call_id":"c1"}]}"""))
        assertEquals(listOf(StreamEvent.Text("Hi")), events("""{"type":"token","content":"Hi","thread_id":"th1"}"""))
        // Frames for another thread on the same socket are ignored.
        assertEquals(emptyList<StreamEvent>(), events("""{"type":"token","content":"nope","thread_id":"other"}"""))
        assertEquals(emptyList<StreamEvent>(), events("""{"type":"done"}"""))
        assertEquals(ServerProtocol.FrameMapper.Outcome.Finished, map("""{"type":"turn.ended","thread_id":"th1","failed":null}"""))
    }

    @Test
    fun frameMapperFailures() {
        val mapper = ServerProtocol.FrameMapper()
        try {
            mapper.map(obj("""{"type":"error","message":"model unavailable","error_code":"X"}"""), "t")
            fail()
        } catch (error: ApiException) {
            assertEquals("model unavailable", error.message)
        }
        try {
            mapper.map(obj("""{"type":"turn.ended","failed":true}"""), "t")
            fail()
        } catch (error: ApiException) {
            assertEquals(ApiException.Kind.Server, error.kind)
        }
        assertEquals(ApiException.Kind.Unauthorized, ServerProtocol.closeError(4001, "").kind)
        assertEquals(404, ServerProtocol.closeError(4404, "no bot").status)
        assertEquals(ApiException.Kind.Network, ServerProtocol.closeError(1000, "").kind)
    }

    @Test
    fun userTurnAndImages() {
        val turn = ServerProtocol.userTurn("th", "hi", JsonPrimitive("hi"), null)
        assertEquals("user_turn", turn["type"]!!.jsonPrimitive.content)
        assertEquals("th", turn["thread_id"]!!.jsonPrimitive.content)
        assertEquals("hi", turn["messages"]!!.jsonArray[0].jsonObject["content"]!!.jsonPrimitive.content)
        val content = ServerProtocol.imageContent(
            "look",
            listOf(obj("""{"workspace_path":"inbound/p.jpg","url":"/u/p.jpg","filename":"p.jpg","media_type":"image/jpeg"}""")),
        )
        val image = content[1].jsonObject
        assertEquals("image", image["type"]!!.jsonPrimitive.content)
        assertEquals("/u/p.jpg", image["source"]!!.jsonObject["url"]!!.jsonPrimitive.content)
        assertEquals("inbound/p.jpg", image["workspace_path"]!!.jsonPrimitive.content)
    }

    @Test
    fun workspaceAndLooks() {
        val (bots, groups) = ServerProtocol.workspace(
            Http.parse(
                """{"chief_id":"a1","bots":[
                  {"agent_id":"b2","name":"Researcher","description":"","avatar":{"shape":"acorn","color":"violet"},"enabled":true},
                  {"agent_id":"a1","name":"Chief","is_main":true,"avatar":{"shape":"whale","color":"deepseek"}},
                  {"agent_id":"b3","name":"Off","enabled":false}
                ],"groups":[{"group_id":"g1","name":"Launch Team","admin_id":"a1","member_ids":["a1","b2"],"reply_mode":"admin_first"}]}""",
            ),
        )
        assertEquals(listOf("a1", "b2"), bots.map { it.id })
        assertEquals(Look.chief, bots[0].look)
        assertNull(bots[1].subtitle)
        assertEquals(listOf("a1", "b2"), groups.single().memberIds)
        assertEquals(Look("gumdrop", "blue"), ServerProtocol.normalizedLook("whale", "deepseek", chief = false))
        assertEquals(Look.fallback, ServerProtocol.normalizedLook(null, null, chief = false))
    }

    @Test
    fun threadsNewestFirstWithMessagesOnly() {
        val list = ServerProtocol.conversations(
            Http.parse(
                """[{"thread_id":"old","title":"Old","last_active":"2026-11-01T00:00:00","has_messages":true},
                    {"thread_id":"empty","has_messages":false},
                    {"thread_id":"new","title":"","last_active":1795168800}]""",
            ),
            "b",
        )
        assertEquals(listOf("new", "old"), list.map { it.id })
        assertEquals(1795168800000L, list[0].updatedAt)
    }

    @Test
    fun newGroupPrefersChiefAsAdmin() {
        val chief = io.github.alisonxx.octopbot.model.BotProfile("c1", "Chief", look = Look.chief, isChief = true)
        val researcher = io.github.alisonxx.octopbot.model.BotProfile("r1", "Researcher", look = Look("acorn", "violet"))
        val writer = io.github.alisonxx.octopbot.model.BotProfile("w1", "Writer", look = Look("cushion", "violet"))
        val body = ServerProtocol.groupCreate(" Launch Team ", listOf(researcher, chief))
        assertEquals("Launch Team", body["name"]!!.jsonPrimitive.content)
        assertEquals("c1", body["admin_id"]!!.jsonPrimitive.content)
        assertEquals(listOf("r1", "c1"), body["member_ids"]!!.jsonArray.map { it.jsonPrimitive.content })
        assertEquals("admin_first", body["reply_mode"]!!.jsonPrimitive.content)
        // Without Chief the first picked Bot administers.
        assertEquals("w1", ServerProtocol.groupCreate("Docs", listOf(writer, researcher))["admin_id"]!!.jsonPrimitive.content)
    }

    @Test
    fun toolNamesAreLocalized() {
        val labels = ServerProtocol.toolLabels(Http.parse("""{"locale":"zh","labels":{"execute":"执行指令","web_search":"网页搜索","bad":1}}"""))
        assertEquals(mapOf("execute" to "执行指令", "web_search" to "网页搜索"), labels)
        val history = ServerProtocol.history(
            Http.parse("""[{"role":"assistant","content":[{"type":"tool_use","id":"t","name":"execute"},{"type":"tool_use","id":"u","name":"other"}]}]""").jsonArray,
            labels,
        )
        assertEquals(listOf("执行指令", "other"), history.single().tools.map { it.name })
        val mapper = ServerProtocol.FrameMapper(labels)
        val events = mapper.map(obj("""{"type":"tool_call_chunk","id":"c","name":"web_search"}"""), "t") as ServerProtocol.FrameMapper.Outcome.Events
        assertEquals(listOf(StreamEvent.Tool("c", "网页搜索", false)), events.events)
        // An explicit display_name from the server wins.
        val named = mapper.map(obj("""{"type":"tool_call_chunk","id":"d","name":"web_search","display_name":"Search"}"""), "t")
        assertEquals(listOf(StreamEvent.Tool("d", "Search", false)), (named as ServerProtocol.FrameMapper.Outcome.Events).events)
    }

    @Test
    fun urlsGroupsAndVoice() {
        assertEquals("https://nas.local:8080", ServerProtocol.normalizeUrl(" nas.local:8080/ "))
        assertEquals("http://10.0.2.2:18790", ServerProtocol.normalizeUrl("http://10.0.2.2:18790"))
        assertNull(ServerProtocol.normalizeUrl("ftp://x"))
        assertNull(ServerProtocol.normalizeUrl(""))

        val messages = ServerProtocol.groupMessages(Http.parse("""[{"message_id":7,"role":"assistant","agent_id":"b2","text":"ok","created_at":1795168800}]"""))
        assertEquals("7", messages.single().id)
        assertEquals(1795168800000L, messages.single().createdAt)
        assertEquals("b2", ServerProtocol.groupDrafts(Http.parse("""[{"agent_id":"b2","request_id":"r","text":"par"}]""")).single().agentId)
        assertNull(ServerProtocol.groupGoal(Http.parse("null")))
        val post = ServerProtocol.groupPost("r1", "@Researcher hi", listOf("b2"))
        assertEquals("b2", post["mention_ids"]!!.jsonArray.single().jsonPrimitive.content)

        assertEquals(VoiceSupport(stt = true, tts = false), ServerProtocol.voiceSupport(Http.parse("""{"stt":"whisper","tts":null}""")))
        assertEquals(VoiceSupport(stt = false, tts = false), ServerProtocol.voiceSupport(Http.parse("{}")))
    }

    @Test
    fun lynxceOwnerCodeBodies() {
        assertEquals(
            """{"target":"13800138000","locale":"zh"}""",
            ServerProtocol.lynxceCodeBody(" 13800138000 ", chinese = true).toString(),
        )
        assertEquals("""{"target":"a@b.cn","locale":"en"}""", ServerProtocol.lynxceCodeBody("a@b.cn", chinese = false).toString())
        assertEquals(
            """{"target":"a@b.cn","code":"012345","locale":"zh"}""",
            ServerProtocol.lynxceCodeLoginBody(" a@b.cn", "012345", chinese = true).toString(),
        )
    }

    @Test
    fun lynxceOwnerCodeErrorsKeepServerMessage() {
        // Octop's envelope: the localized message is what the app shows.
        val text = """{"error":{"code":"LYNXCE_CODE_INVALID","message":"验证码错误或已过期"}}"""
        val error = ApiException.from(401, Http.errorMessage(text))
        assertEquals("验证码错误或已过期", error.message)
        assertEquals(LynxceProtocol.CodeFailure.InvalidCode, LynxceProtocol.codeFailure(error))
        assertEquals(LynxceProtocol.CodeFailure.TooFrequent, LynxceProtocol.codeFailure(ApiException.from(429, null)))
        assertNull(LynxceProtocol.codeFailure(ApiException.from(403, "owner mismatch")))
    }

    @Test
    fun cloudIsRecognisedAndItsFileLinksIntercepted() {
        assertTrue(ServerProtocol.isCloudInfo(Http.parse("""{"product":"octop-bot","edition":"cloud"}""")))
        assertFalse(ServerProtocol.isCloudInfo(Http.parse("""{"product":"octop-bot","edition":"web"}""")))
        assertTrue(ServerProtocol.isWorkspaceDownload("/api/agents/AbC123/workspace/download?path=outbound/a.pdf"))
        assertFalse(ServerProtocol.isWorkspaceDownload("https://example.com/api/agents/A/workspace/download?path=x"))
        assertFalse(ServerProtocol.isWorkspaceDownload("/api/agents/A/workspace/tree"))
    }

    @Test
    fun computerStatusParses() {
        val running = ServerProtocol.computerStatus(Http.parse("""{"state":"running","spec":"standard","running_since":1700000000.5}"""))
        assertEquals(ServerProtocol.ComputerStatus.State.Running, running?.state)
        assertEquals(1_700_000_000_500L, running?.runningSinceMillis)
        assertEquals(ServerProtocol.ComputerStatus.State.None, ServerProtocol.computerStatus(Http.parse("""{"state":"none"}"""))?.state)
        assertNull(ServerProtocol.computerStatus(Http.parse("""{"state":"melted"}""")))
    }
}
