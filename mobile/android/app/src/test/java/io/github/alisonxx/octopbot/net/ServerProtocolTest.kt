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
    @Test fun automaticConversationRequiresPersonalOwnershipAndPrefersActive() {
        val rows = ServerProtocol.conversations(Http.parse("""[{"thread_id":"shared","owned":false,"is_active":true},{"thread_id":"unknown"},{"thread_id":"recent","owned":true},{"thread_id":"active","owned":true,"is_active":true}]"""), "bot")
        assertNull(io.github.alisonxx.octopbot.model.ConversationSummary.personalDefault(rows.take(2)))
        assertEquals("active", io.github.alisonxx.octopbot.model.ConversationSummary.personalDefault(rows)?.id)
    }

    @Test fun observedQuestionAndReplyPrefixSurviveReconnectAndSavedUserIsNotDuplicated() {
        val previous = io.github.alisonxx.octopbot.model.ChatMessage("old", MessageRole.Assistant, "previous")
        val user = io.github.alisonxx.octopbot.model.ChatMessage("u", MessageRole.User, "question")
        val reply = io.github.alisonxx.octopbot.model.ChatMessage("reply", MessageRole.Assistant, "prefix", status = MessageStatus.Streaming)
        val current = io.github.alisonxx.octopbot.app.ChatSession.ObservedTurn("turn", previous, mutableListOf(user, reply))
        assertEquals(listOf(previous, user, reply), current.merged(listOf(previous)))
        assertEquals(listOf(previous, user, reply), current.merged(listOf(previous, user)))
        assertEquals(listOf(user), current.committedTail(listOf(previous, user)))
    }

    @Test fun interruptedSenderUsesPersistentAnchorAndWaitsForItsOwnQuestion() {
        val mapper = ServerProtocol.FrameMapper(emptyMap())
        val start = mapper.map(Http.parse("""{"type":"turn.started","turn_id":"run"}""").asObject()!!, "thread")
        assertEquals(listOf(StreamEvent.TurnStarted("run")), (start as ServerProtocol.FrameMapper.Outcome.Events).events)
        val previous = io.github.alisonxx.octopbot.model.ChatMessage("old", MessageRole.Assistant, "previous")
        val user = io.github.alisonxx.octopbot.model.ChatMessage("local-user", MessageRole.User, "question")
        val partial = io.github.alisonxx.octopbot.model.ChatMessage("local-reply", MessageRole.Assistant, "prefix", status = MessageStatus.Streaming)
        val turn = io.github.alisonxx.octopbot.app.ChatSession.ObservedTurn("run", previous, mutableListOf(user, partial))
        val savedUser = user.copy(id = "saved-user")
        val other = previous.copy(id = "other", text = "previous completed turn")
        assertFalse(turn.hasCommittedReply(listOf(previous, other, savedUser)))
        assertEquals("local-reply", turn.merged(listOf(previous, savedUser)).last().id)
        assertTrue(turn.hasCommittedReply(listOf(previous, savedUser, partial.copy(id = "saved-reply", text = "prefix and complete response"))))
    }

    @Test fun historyPageOverlapRetainsNewestVersionAndOriginalOrder() {
        val old = Http.parse("""[{"id":"a"},{"history_seq":2,"content":"partial"}]""").asArray()!!
        val new = Http.parse("""[{"history_seq":2,"content":"finished"},{"id":"b"}]""").asArray()!!
        val rows = ServerProtocol.joinHistory(old, new)
        assertEquals(3, rows.size)
        assertEquals("finished", rows[1].asObject()?.str("content"))
        assertEquals("b", rows[2].asObject()?.str("id"))
    }

    @Test fun onlyTheExactCheckoutCallbackIsAccepted() {
        val url = "octop-bot://recharge/done"
        assertTrue(io.github.alisonxx.octopbot.isRechargeReturn(url))
        for (invalid in listOf(null, "$url?paid=true", "$url#order", "$url/", url.replace("done", "other"))) {
            assertFalse(io.github.alisonxx.octopbot.isRechargeReturn(invalid))
        }
    }

    @org.junit.Test
    fun computerCreditCodesAreRecognized() {
        org.junit.Assert.assertTrue(ApiException.isCreditsRequired(ApiException.COMPUTER_CREDITS_REQUIRED))
        org.junit.Assert.assertTrue(ApiException.isCreditsRequired(ApiException.COMPUTER_PAUSED_NO_CREDITS))
        org.junit.Assert.assertFalse(ApiException.isCreditsRequired(null))
    }

    @org.junit.Test
    fun rechargeBodyCarriesOnlyValidOptionalFields() {
        val body = ServerProtocol.rechargeBody("test-account", 12.1, "image")
        org.junit.Assert.assertEquals("credits", body["intent"]?.toString()?.trim('"'))
        org.junit.Assert.assertEquals("android", body["from"]?.toString()?.trim('"'))
        org.junit.Assert.assertEquals("13", body["need"]?.toString())
        org.junit.Assert.assertEquals("image", body["reason"]?.toString()?.trim('"'))
        val invalid = ServerProtocol.rechargeBody("test-account", 0.0, "invalid")
        org.junit.Assert.assertNull(invalid["need"])
        org.junit.Assert.assertNull(invalid["reason"])
    }

    @Test
    fun creditScenariosAndDetailsSurviveErrors() {
        for (kind in listOf("text", "image", "video")) {
            val details = CreditDetails(12.2, 3.0, kind)
            assertEquals(CreditScenario(kind, 12.2, 3.0), creditScenario(ApiException.CREDITS_REQUIRED, details))
        }
        val details = CreditDetails(12.2, 3.0, null)
        assertEquals("computer", creditScenario(ApiException.COMPUTER_CREDITS_REQUIRED, details)?.reason)
        assertEquals("paused", creditScenario(ApiException.COMPUTER_PAUSED_NO_CREDITS, details)?.type)
        assertNull(creditScenario(ApiException.CREDITS_REQUIRED, CreditDetails(null, 3.0, "text")))
        assertNull(creditScenario(ApiException.CREDITS_REQUIRED, CreditDetails(1.0, null, "text")))
        // A paused computer needs no figures; starting one needs only `need`.
        assertEquals("paused", creditScenario(ApiException.COMPUTER_PAUSED_NO_CREDITS, null)?.type)
        assertEquals(9.0, creditScenario(ApiException.COMPUTER_CREDITS_REQUIRED, CreditDetails(9.0, null, null))!!.need, 0.0)
        assertNull(creditScenario(ApiException.COMPUTER_CREDITS_REQUIRED, CreditDetails(null, 2.0, null)))
        assertNull(creditScenario(ApiException.CREDITS_REQUIRED, CreditDetails(1.0, 2.0, "unknown")))
        val http = ApiException.fromBody(402, """{"error":{"code":"BOT_CLOUD_CREDITS_REQUIRED","details":{"need":12.2,"balance":3,"kind":"image"}}}""")
        val frame = ServerProtocol.streamError(obj("""{"error_code":"BOT_CLOUD_CREDITS_REQUIRED","error_details":{"need":12.2,"balance":3,"kind":"image"}}"""), null)
        assertEquals(CreditScenario("image", 12.2, 3.0), creditScenario(http.code, http.details))
        assertEquals(http.details, frame.details)
        val provider = ServerProtocol.streamError(obj("""{"error_code":"insufficient_balance"}"""), null)
        assertEquals(ApiException.Kind.Server, provider.kind)
        assertEquals("insufficient_balance", provider.code)
        val empty = ServerProtocol.rechargeBody("account")
        assertNull(empty["need"])
        assertNull(empty["reason"])
        val scenario = creditScenario(frame.code, frame.details)!!
        val body = ServerProtocol.rechargeBody("account", scenario.need, scenario.reason)
        assertEquals("13", body["need"].toString())
        assertEquals("\"image\"", body["reason"].toString())
    }

    private fun obj(text: String) = Http.parse(text) as JsonObject

    @Test
    fun botPreparationFieldsAndPolling() {
        val legacy = ServerProtocol.bot(obj("""{"agent_id":"old"}"""))!!
        val starting = ServerProtocol.bot(obj("""{"agent_id":"new","state":"starting","preparing":true}"""))!!
        val failed = ServerProtocol.bot(obj("""{"agent_id":"bad","state":"failed","preparing":false,"last_error":"problem"}"""))!!
        assertTrue(legacy.canSend)
        assertNull(legacy.state)
        assertFalse(starting.canSend)
        assertEquals("starting", starting.state)
        assertFalse(failed.canSend)
        assertEquals("problem", failed.lastError)
        assertTrue(io.github.alisonxx.octopbot.model.shouldPollBots(listOf(legacy, starting, failed)))
        assertFalse(io.github.alisonxx.octopbot.model.shouldPollBots(listOf(legacy, failed)))
    }

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

        assertEquals(listOf(StreamEvent.TurnStarted("x")), events("""{"type":"turn.started","turn_id":"x","thread_id":"th1"}"""))
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

    @Test
    fun screenPageCarriesTheTicket() {
        assertEquals(
            "https://bot.lynxce.cn/octop-bot/screen/AbC123?ticket=t-1&session=s-1&control=1",
            ServerProtocol.screenPage(
                "https://bot.lynxce.cn", "AbC123", "/api/octop-bot/computers/AbC123/screen/ws?ticket=t-1", "s-1", control = true,
            ),
        )
        assertEquals(
            "https://bot.lynxce.cn/octop-bot/screen/AbC123?ticket=t-1&control=0",
            ServerProtocol.screenPage(
                "https://bot.lynxce.cn", "AbC123", "/api/octop-bot/computers/AbC123/screen/ws?ticket=t-1", null, control = false,
            ),
        )
        assertEquals(true, ServerProtocol.computerStatus(Http.parse("""{"state":"running","takeover":true}"""))?.takeover)
    }

    @Test
    fun historyAttachesSentFilesToTheTurnsReply() {
        val messages = ServerProtocol.history(
            Http.parse(
                """[
                  {"role":"user","content":"make a report"},
                  {"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"send_file_to_user"}]},
                  {"role":"tool","content":[{"type":"tool_result","id":"t1","name":"send_file_to_user",
                    "output":"{\"type\":\"file\",\"path\":\"outbound/Q4 report.pdf\",\"filename\":\"Q4 report.pdf\",\"media_type\":\"application/pdf\"}"}]},
                  {"role":"tool","content":[{"type":"tool_result","id":"t2","name":"mcp/send_file",
                    "output":"[{\"type\":\"image\",\"path\":\"outbound/chart.png\",\"preview_url\":\"/api/agents/A1/media/preview?source=outbound%2Fchart.png\"}]"}]},
                  {"role":"tool","content":[{"type":"tool_result","id":"t3","name":"write_file","output":"{\"type\":\"file\",\"path\":\"x.txt\"}"}]},
                  {"role":"assistant","content":[{"type":"text","text":"Done."}]},
                  {"role":"user","content":"and the data?"},
                  {"role":"assistant","content":[{"type":"text","text":"Sending."}]},
                  {"role":"tool","agent_id":"B2","content":[{"type":"tool_result","name":"send_file_to_user","output":"{\"type\":\"file\",\"path\":\"/tmp/dec.csv\"}"}]}
                ]""",
            ) as kotlinx.serialization.json.JsonArray,
            agentId = "A1",
        )
        assertEquals(4, messages.size)
        val reply = messages[1]
        assertEquals("Done.", reply.text)
        assertEquals(listOf("Q4 report.pdf", "chart.png"), reply.attachments.map { it.name })
        assertEquals("/api/agents/A1/workspace/download?path=outbound%2FQ4%20report.pdf", reply.attachments[0].url)
        assertEquals("application/pdf", reply.attachments[0].mime)
        assertEquals("/api/agents/A1/media/preview?source=outbound%2Fchart.png", reply.attachments[1].url)
        // A file sent after the last text of a turn still lands on that reply, from the speaker's workspace.
        assertEquals(listOf("/api/agents/B2/workspace/download?path=%2Ftmp%2Fdec.csv"), messages[3].attachments.map { it.url })
        assertEquals("dec.csv", messages[3].attachments[0].name)
    }

    @Test
    fun historyAttachesGeneratedImagesAndVideos() {
        val messages = ServerProtocol.history(
            Http.parse(
                """[
                  {"role":"user","content":"画一只猫，再做一段海浪的视频"},
                  {"role":"tool","content":[{"type":"tool_result","name":"generate_image",
                    "output":"{\"type\":\"image_gen_tool_result\",\"images\":[{\"path\":\"generated/images/cat.png\",\"mediaType\":\"image/png\"}]}"}]},
                  {"role":"tool","content":[{"type":"tool_result","name":"generate_video",
                    "output":"{\"type\":\"video_gen_tool_result\",\"videos\":[{\"path\":\"generated/videos/sea.mp4\",\"mediaType\":\"video/mp4\"}]}"}]},
                  {"role":"assistant","content":[{"type":"text","text":"好了。"}]}
                ]""",
            ) as kotlinx.serialization.json.JsonArray,
            agentId = "A1",
        )
        val files = messages[1].attachments
        assertEquals(listOf("cat.png", "sea.mp4"), files.map { it.name })
        assertEquals("/api/agents/A1/workspace/download?path=generated%2Fvideos%2Fsea.mp4", files[1].url)
        assertEquals(listOf("image/png", "video/mp4"), files.map { it.mime })
    }

    @Test
    fun attachmentFramesStreamIntoTheReply() {
        val mapper = ServerProtocol.FrameMapper()
        val outcome = mapper.map(
            obj("""{"type":"attachment","kind":"file","url":"/api/agents/A1/workspace/download?path=outbound%2Fdeck.pptx","path":"outbound/deck.pptx","mime_type":"application/vnd.ms-powerpoint"}"""),
            "th1",
        ) as ServerProtocol.FrameMapper.Outcome.Events
        val file = (outcome.events.single() as StreamEvent.Attachment).file
        assertEquals("deck.pptx", file.name)
        assertEquals("application/vnd.ms-powerpoint", file.mime)
        val named = mapper.map(obj("""{"type":"attachment","kind":"image","url":"/api/agents/A1/media/preview?source=outbound%2Fa.png","filename":"chart.png"}"""), "th1")
        assertEquals("chart.png", ((named as ServerProtocol.FrameMapper.Outcome.Events).events.single() as StreamEvent.Attachment).file.name)
        // Inline data and foreign URLs are not cards.
        val inline = mapper.map(obj("""{"type":"attachment","kind":"image","url":"data:image/png;base64,AAAA"}"""), "th1")
        assertTrue((inline as ServerProtocol.FrameMapper.Outcome.Events).events.isEmpty())
    }

    @Test
    fun outOfCreditsKeepsItsCode() {
        val mapper = ServerProtocol.FrameMapper()
        val error = try {
            mapper.map(obj("""{"type":"error","message":"灵策积分不足","error_code":"BOT_CLOUD_CREDITS_REQUIRED"}"""), "t")
            fail()
            null
        } catch (error: ApiException) {
            error
        }
        assertEquals(ApiException.Kind.Credits, error?.kind)
        assertEquals("灵策积分不足", error?.message)
        assertEquals(ApiException.Kind.Credits, ServerProtocol.handshakeError(402).kind)
        assertEquals(ApiException.Kind.Unauthorized, ServerProtocol.handshakeError(401).kind)
        assertEquals(ApiException.Kind.Network, ServerProtocol.handshakeError(null).kind)

        val envelope = """{"error":{"code":"BOT_CLOUD_CREDITS_REQUIRED","message":"m"}}"""
        assertEquals(ApiException.Kind.Credits, ApiException.fromBody(409, envelope).kind)
        assertEquals(ApiException.Kind.Credits, ApiException.fromBody(402, "{}").kind)
        assertEquals(ApiException.Kind.Rejected, ApiException.fromBody(409, "{}").kind)

        val rows = ServerProtocol.history(
            Http.parse(
                """[{"role":"user","content":"hi"},
                   {"role":"assistant","content":"partial","status":"error","error_code":"BOT_CLOUD_CREDITS_REQUIRED"},
                   {"role":"user","content":"again"},
                   {"role":"assistant","content":"x","status":"error"}]""",
            ).jsonArray,
        )
        assertEquals(MessageStatus.Failed(null, credits = true), rows[1].status)
        assertEquals(MessageStatus.Failed(null, credits = false), rows[3].status)
    }

    @Test
    fun cloudCheckoutAcceptsOnlyLynxceRechargeWithAFreshTicket() {
        val now = java.time.Instant.parse("2026-11-24T00:00:00Z")
        val ticket = "x." + "a".repeat(43)
        val good = "https://admin.lynxce.cn/recharge?token=$ticket"
        fun link(url: String, expires: String = "2026-11-24T00:15:00+00:00") =
            Http.parse("""{"url":"$url","expires_at":"$expires"}""")
        assertEquals(good, ServerProtocol.cloudCheckoutUrl(link(good), now))
        assertEquals("$good&tab=boost", ServerProtocol.cloudCheckoutUrl(link("$good&tab=boost"), now))
        assertNull(ServerProtocol.cloudCheckoutUrl(link("https://admin.lynxce.cn/recharge"), now))
        assertNull(ServerProtocol.cloudCheckoutUrl(link("$good&tab=evil"), now))
        assertEquals(good, ServerProtocol.cloudCheckoutUrl(link(good, "2026-11-24T00:15:00.123456Z"), now))
        assertNull(ServerProtocol.cloudCheckoutUrl(link("http://admin.lynxce.cn/recharge?token=$ticket"), now))
        assertNull(ServerProtocol.cloudCheckoutUrl(link("https://admin.lynxce.cn.evil.cn/recharge?token=$ticket"), now))
        assertNull(ServerProtocol.cloudCheckoutUrl(link("https://u:p@admin.lynxce.cn/recharge?token=$ticket"), now))
        assertNull(ServerProtocol.cloudCheckoutUrl(link("https://admin.lynxce.cn/recharge/x?token=$ticket"), now))
        assertNull(ServerProtocol.cloudCheckoutUrl(link("$good&next=evil"), now))
        assertNull(ServerProtocol.cloudCheckoutUrl(link("$good#frag"), now))
        assertNull(ServerProtocol.cloudCheckoutUrl(link("https://admin.lynxce.cn/recharge?token=mcrt1.${"a".repeat(43)}"), now))
        assertNull(ServerProtocol.cloudCheckoutUrl(link("https://admin.lynxce.cn/recharge?token=x.short"), now))
        assertNull(ServerProtocol.cloudCheckoutUrl(link(good, "2026-11-24T00:17:00Z"), now))
        assertNull(ServerProtocol.cloudCheckoutUrl(link(good, "2026-11-23T23:59:00Z"), now))
        assertNull(ServerProtocol.cloudCheckoutUrl(Http.parse("""{"url":"$good"}"""), now))
    }

    @Test
    fun usageAndNames() {
        val usage = ServerProtocol.usage(
            Http.parse(
                """{"total_tokens":1500,"model_calls":7,"buckets":[
                  {"key":"a","label":"Writer","total_tokens":500},
                  {"key":"b","label":"","total_tokens":1000},
                  {"key":"c","label":"Idle","total_tokens":0}]}""",
            ),
        )!!
        assertEquals(1500L, usage.totalTokens)
        assertEquals(7L, usage.modelCalls)
        assertEquals(listOf("b" to "b", "a" to "Writer"), usage.buckets.map { it.key to it.label })

        assertNull(ServerProtocol.personName("sso_3f9a2c"))
        assertNull(ServerProtocol.personName("owner"))
        assertNull(ServerProtocol.personName("local"))
        assertNull(ServerProtocol.personName(" "))
        assertEquals("138****5678", ServerProtocol.personName("138****5678"))
    }

    @Test
    fun dailyLimitIsNotOutOfCredits() {
        fun kindOf(block: () -> Unit) = (runCatching(block).exceptionOrNull() as ApiException).kind
        val mapper = ServerProtocol.FrameMapper()
        assertEquals(
            ApiException.Kind.DailyLimit,
            kindOf { mapper.map(obj("""{"type":"error","message":"m","error_code":"BOT_LYNXCE_DAILY_LIMIT"}"""), "t") },
        )
        assertEquals(ApiException.Kind.DailyLimit, ApiException.fromBody(429, """{"error":{"code":"BOT_LYNXCE_DAILY_LIMIT","message":"m"}}""").kind)
        // Direct Lynxce may send the cap as a 402; it is still not "out of credits".
        assertEquals(ApiException.Kind.DailyLimit, ApiException.fromBody(402, """{"code":"api_key_credit_limit_reached","message":"m"}""").kind)
        assertEquals(ApiException.Kind.DailyLimit, kindOf { LynxceProtocol.unwrap(402, """{"code":"api_key_credit_limit_reached"}""") })
        assertEquals(ApiException.Kind.DailyLimit, kindOf { LynxceProtocol.unwrap(200, """{"code":"api_key_credit_limit_reached"}""") })
        assertEquals(
            ApiException.Kind.DailyLimit,
            kindOf { LynxceProtocol.parseChunk("""{"error":{"code":"api_key_credit_limit_reached","message":"limit"}}""") },
        )
        assertEquals(ApiException.Kind.Credits, ApiException.fromBody(402, """{"code":402,"message":"no credits"}""").kind)
        val rows = ServerProtocol.history(
            Http.parse(
                """[{"role":"user","content":"hi"},{"role":"assistant","content":"x","status":"error","error_code":"BOT_LYNXCE_DAILY_LIMIT"}]""",
            ).jsonArray,
        )
        assertEquals(MessageStatus.Failed(null, dailyLimit = true), rows[1].status)
    }

    @Test
    fun cloudComputerOffAndBusyKeepTheirCodes() {
        val off = ApiException.fromBody(409, """{"error":{"code":"BOT_COMPUTER_OFF","message":"m","details":{}}}""")
        assertEquals(ApiException.Kind.Rejected, off.kind)
        assertEquals(ApiException.COMPUTER_OFF, off.code)
        val busy = ApiException.fromBody(503, """{"error":{"code":"BOT_COMPUTER_BUSY","message":"m","details":{}}}""")
        assertEquals(ApiException.Kind.Server, busy.kind)
        assertEquals(ApiException.COMPUTER_BUSY, busy.code)
        // Longer than the server's 300 s wait for a cold start, so the phone never gives up first.
        assertTrue(ServerBackend.SCREEN_SECONDS > 300)
    }
}
