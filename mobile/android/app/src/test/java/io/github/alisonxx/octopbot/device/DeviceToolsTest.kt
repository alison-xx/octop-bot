package io.github.alisonxx.octopbot.device

import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.HitlDecision
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.net.Http
import io.github.alisonxx.octopbot.net.LynxceProtocol
import io.github.alisonxx.octopbot.net.ServerProtocol
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZonedDateTime
import java.util.Locale

class DeviceToolsTest {
    private val catalog = DeviceCatalog.parse(File("src/main/assets/device_tools.json").readText())
    private val shanghai = ZoneId.of("Asia/Shanghai")

    @Test
    fun androidLoadsHealthAndCalendarButNeverReminders() {
        assertEquals(
            listOf("device_health_summary", "device_calendar_events", "device_calendar_create_event", "device_calendar_update_event"),
            catalog.map { it.name },
        )
        assertTrue(catalog.none { it.capability == DeviceCapability.Reminders })
        assertEquals(listOf(false, false, true, true), catalog.map { it.writes })
        assertEquals("object", catalog.first().parameters["type"]!!.jsonPrimitive.content)
        // iOS would keep them.
        val all = DeviceCatalog.parse(File("src/main/assets/device_tools.json").readText(), DeviceCapability.entries.toSet())
        assertEquals(6, all.size)
    }

    @Test
    fun onlyConnectorsThatAreOnAreOffered() {
        assertEquals(emptyList<DeviceTool>(), DeviceCatalog.offered(catalog, emptySet()))
        assertEquals(listOf("device_health_summary"), DeviceCatalog.offered(catalog, setOf(DeviceCapability.Health)).map { it.name })
        val calendar = DeviceCatalog.offered(catalog, setOf(DeviceCapability.Calendar, DeviceCapability.Reminders))
        assertEquals(3, calendar.size)
        val tools = DeviceCatalog.openAiTools(calendar)
        val function = tools[0].jsonObject["function"]!!.jsonObject
        assertEquals("function", tools[0].jsonObject["type"]!!.jsonPrimitive.content)
        assertEquals("device_calendar_events", function["name"]!!.jsonPrimitive.content)
        assertTrue("start" in function["parameters"]!!.jsonObject["properties"]!!.jsonObject)
    }

    @Test
    fun toolCallPiecesJoinByIndex() {
        val calls = ToolCallAccumulator()
        assertTrue(calls.isEmpty)
        fun chunk(json: String) = LynxceProtocol.parseChunk(json, calls)
        chunk("""{"choices":[{"delta":{"content":"Let me check. "}}]}""")
        chunk("""{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_a","type":"function","function":{"name":"device_calendar_events","arguments":""}}]}}]}""")
        chunk("""{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\"start\":\"2026-11-24\","}}]}}]}""")
        chunk("""{"choices":[{"delta":{"tool_calls":[{"index":1,"id":"call_b","function":{"name":"device_health_summary","arguments":"{\"metrics\":[\"steps\"]}"}}]}}]}""")
        chunk("""{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\"end\":\"2026-11-25\"}"}}]}}]}""")
        // A provider that leaves out the id.
        chunk("""{"choices":[{"delta":{"tool_calls":[{"index":2,"function":{"name":"device_calendar_events","arguments":"{}"}}]}}]}""")
        val result = calls.calls()
        assertEquals(
            listOf(
                ToolCallAccumulator.Call("call_a", "device_calendar_events", """{"start":"2026-11-24","end":"2026-11-25"}"""),
                ToolCallAccumulator.Call("call_b", "device_health_summary", """{"metrics":["steps"]}"""),
                ToolCallAccumulator.Call("call_2", "device_calendar_events", "{}"),
            ),
            result,
        )
        assertEquals("2026-11-25", DeviceCatalog.args(result[0].arguments)["end"]!!.jsonPrimitive.content)
        assertEquals(JsonObject(emptyMap()), DeviceCatalog.args("{not json"))

        val assistant = LynxceProtocol.assistantToolCalls("", result)
        assertEquals(JsonNull, assistant["content"])
        assertEquals("call_b", assistant["tool_calls"]!!.jsonArray[1].jsonObject["id"]!!.jsonPrimitive.content)
        val tool = LynxceProtocol.toolResult("call_a", """{"events":[]}""")
        assertEquals("tool", tool["role"]!!.jsonPrimitive.content)
        assertEquals("call_a", tool["tool_call_id"]!!.jsonPrimitive.content)
    }

    @Test
    fun chatBodyAddsToolsOnlyWhenAConnectorIsOn() {
        val bot = BotProfile("chief", "Chief", look = Look.chief, systemPrompt = "Be brief.")
        val now = ZonedDateTime.of(2026, 11, 24, 15, 0, 0, 0, shanghai)
        val plain = LynxceProtocol.chatBody("hi", emptyList(), bot, emptyList(), "s", null, now = now)
        assertFalse("tools" in plain)
        assertEquals("Be brief.", plain["messages"]!!.jsonArray[0].jsonObject["content"]!!.jsonPrimitive.content)

        val body = LynxceProtocol.chatBody("hi", emptyList(), bot, emptyList(), "s", null, tools = catalog, now = now)
        assertEquals("auto", body["tool_choice"]!!.jsonPrimitive.content)
        assertEquals(4, body["tools"]!!.jsonArray.size)
        assertEquals(
            "Be brief.\n\nNow: 2026-11-24T15:00:00+08:00 (Asia/Shanghai).",
            body["messages"]!!.jsonArray[0].jsonObject["content"]!!.jsonPrimitive.content,
        )

        val loop = listOf(LynxceProtocol.toolResult("c", "{}"))
        val next = LynxceProtocol.roundBody(body, loop, withTools = true)
        assertEquals(3, next["messages"]!!.jsonArray.size)
        assertTrue("tools" in next)
        val retry = LynxceProtocol.roundBody(body, loop, withTools = false)
        assertFalse("tools" in retry)
        assertFalse("tool_choice" in retry)
    }

    @Test
    fun isoTimesUseThePhoneZoneAndBareDatesAreWholeDays() {
        val offset = DeviceTimes.parse("2026-11-24T09:30:00Z", shanghai) as DeviceTime.Moment
        assertEquals("2026-11-24T17:30:00+08:00", DeviceTimes.format(offset.time))
        val local = DeviceTimes.parse("2026-11-24T09:30", shanghai) as DeviceTime.Moment
        assertEquals("2026-11-24T09:30:00+08:00", DeviceTimes.format(local.time))
        assertEquals(local, DeviceTimes.parse("2026-11-24 09:30:00", shanghai))
        val day = DeviceTimes.parse("2026-11-24", shanghai)
        assertEquals(DeviceTime.Day(LocalDate.of(2026, 11, 24)), day)
        assertEquals("2026-11-24T00:00:00+08:00", DeviceTimes.format(DeviceTimes.start(day!!, shanghai)))
        assertEquals("2026-11-25T00:00:00+08:00", DeviceTimes.format(DeviceTimes.end(day, shanghai)))
        assertEquals(local.time, DeviceTimes.end(local, shanghai))
        assertNull(DeviceTimes.parse("tomorrow", shanghai))
        assertNull(DeviceTimes.parse("", shanghai))
    }

    @Test
    fun writePreviewShowsTitleTimePlaceNotesAndAlert() {
        val args = Http.parse(
            """{"title":"Dentist","start":"2026-11-25T15:00","end":"2026-11-25T16:00","location":"Main St","notes":"Bring card","alarm_minutes":30}""",
        ) as JsonObject
        val rows = DevicePreview.rows(args, shanghai, Locale.US)
        assertEquals(
            listOf(DevicePreview.Field.Title, DevicePreview.Field.Time, DevicePreview.Field.Location, DevicePreview.Field.Notes, DevicePreview.Field.Alert),
            rows.map { it.first },
        )
        assertEquals("Dentist", rows[0].second)
        assertTrue(rows[1].second, rows[1].second.startsWith("Nov 25, 2026") && " – " in rows[1].second)
        assertEquals("30", rows[4].second)
        val allDay = DevicePreview.rows(Http.parse("""{"title":"Trip","start":"2026-12-01","end":"2026-12-03"}""") as JsonObject, shanghai, Locale.US)
        assertEquals("Dec 1, 2026 – Dec 3, 2026", allDay[1].second)
    }

    @Test
    fun mixedPauseApprovesDeviceWithRespondAndOthersWithApprove() = runTest {
        val request = ServerProtocol.hitlRequest(
            Http.parse(
                """{"pending_id":"p","action_requests":[
                  {"name":"device_calendar_create_event","args":"{\"title\":\"Dentist\",\"start\":\"2026-11-25T15:00\",\"end\":\"2026-11-25T16:00\"}","description":"Runs on the user's phone."},
                  {"name":"shell","args":{"command":"ls"}},
                  {"name":"ask_user_question","args":{"question":"Which?"}}
                ],"review_configs":[{"action_name":"device_calendar_create_event","allowed_decisions":["respond","reject"]}]}""",
            ),
        )!!
        val device = request.actions[0]
        assertEquals("Dentist", device.args!!["title"]!!.jsonPrimitive.content)
        assertNull("the server's model-facing text is not shown", device.description)
        assertEquals(emptyList<Pair<String, String>>(), device.details)
        assertNull(request.actions[1].args)

        val ran = mutableListOf<String>()
        val approved = DeviceDecisions.review(request, approve = true, questionReply = "decide") { action ->
            ran += action.name
            """{"id":"42"}"""
        }
        assertEquals(listOf("device_calendar_create_event"), ran)
        assertEquals(
            listOf(HitlDecision.Respond("""{"id":"42"}"""), HitlDecision.Approve, HitlDecision.Respond("decide")),
            approved,
        )
        val rejected = DeviceDecisions.review(request, approve = false, questionReply = "closed") { error("must not run") }
        assertEquals(
            listOf(HitlDecision.Reject(DeviceDecisions.DECLINED), HitlDecision.Reject(), HitlDecision.Respond("closed")),
            rejected,
        )
        val resume = ServerProtocol.hitlResume("t", "p", approved)["decisions"]!!.jsonArray
        assertEquals("respond", resume[0].jsonObject["type"]!!.jsonPrimitive.content)
        assertEquals("approve", resume[1].jsonObject["type"]!!.jsonPrimitive.content)
    }

    @Test
    fun onlyReadPausesRunWithoutACard() {
        fun pause(vararg names: String) = ServerProtocol.hitlRequest(
            Http.parse("""{"action_requests":[${names.joinToString(",") { """{"name":"$it","args":{}}""" }}]}"""),
        )!!
        val writes = { name: String -> catalog.firstOrNull { it.name == name }?.writes == true }
        assertTrue(DeviceDecisions.runsAlone(pause("device_calendar_events", "device_health_summary"), writes))
        // Unknown here (Reminders on Android): answered at once with an error.
        assertTrue(DeviceDecisions.runsAlone(pause("device_reminders"), writes))
        assertFalse(DeviceDecisions.runsAlone(pause("device_calendar_events", "device_calendar_create_event"), writes))
        assertFalse(DeviceDecisions.runsAlone(pause("device_calendar_events", "shell"), writes))
    }

    @Test
    fun userTurnListsTheOfferedTools() {
        val turn = ServerProtocol.userTurn("t", "hi", JsonPrimitive("hi"), null, listOf("device_calendar_events"))
        assertEquals(listOf("device_calendar_events"), turn["device_tools"]!!.jsonArray.map { it.jsonPrimitive.content })
        assertEquals(0, ServerProtocol.userTurn("t", "hi", JsonPrimitive("hi"), null)["device_tools"]!!.jsonArray.size)
    }

    @Test
    fun aDeclinedLynxceWriteTellsTheModelWhatTheUserSaid() {
        assertEquals("""{"error":"The user declined."}""", LynxceProtocol.declined(DeviceDecisions.DECLINED).toString())
        assertEquals("""{"error":"The user declined."}""", LynxceProtocol.declined(HitlDecision.REJECTED).toString())
        assertEquals(
            """{"error":"The user declined.","user_message":"Make it 4pm"}""",
            LynxceProtocol.declined("Make it 4pm").toString(),
        )
        val pause = LynxceProtocol.devicePause(
            "p",
            listOf(ToolCallAccumulator.Call("c", "device_calendar_create_event", """{"title":"X"}""")),
        ) { "Add calendar event" }
        assertEquals("p", pause.pendingId)
        assertFalse(pause.isQuestion)
        assertEquals("Add calendar event", pause.actions[0].label)
        assertFalse(pause.actions[0].allows("approve"))
        assertEquals("X", pause.actions[0].args!!["title"]!!.jsonPrimitive.content)
    }
}
