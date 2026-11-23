package io.github.alisonxx.octopbot.net

import io.github.alisonxx.octopbot.model.HitlAnswer
import io.github.alisonxx.octopbot.model.HitlAnswers
import io.github.alisonxx.octopbot.model.HitlDecision
import io.github.alisonxx.octopbot.model.HitlOption
import io.github.alisonxx.octopbot.model.HitlQuestion
import io.github.alisonxx.octopbot.model.HitlRequest
import io.github.alisonxx.octopbot.model.StreamEvent
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HitlProtocolTest {
    private fun obj(text: String) = Http.parse(text) as JsonObject

    @Test
    fun questionFrameWithStringArgsUnwrapsValue() {
        val mapper = ServerProtocol.FrameMapper()
        val outcome = mapper.map(
            obj(
                """{"type":"hitl_required","thread_id":"t","request":{"value":{"value":{"pending_id":"p1","action_requests":[
                  {"name":"ask_user_question","args":"{\"questions\":[{\"question\":\"Which city?\",\"header\":\"City\",\"options\":[{\"label\":\"Paris\",\"description\":\"France\"},\"Rome\"]},{\"prompt\":\"Anything else?\",\"multi_select\":true}]}"}
                ]}}}}""",
            ),
            "t",
        )
        val request = ((outcome as ServerProtocol.FrameMapper.Outcome.Events).events.single() as StreamEvent.Hitl).request
        assertEquals("p1", request.pendingId)
        assertTrue(request.isQuestion)
        val questions = request.actions.single().questions!!
        assertEquals(
            HitlQuestion("Which city?", "City", listOf(HitlOption("Paris", "France"), HitlOption("Rome", null)), multiSelect = false),
            questions[0],
        )
        assertEquals(HitlQuestion("Anything else?", null, emptyList(), multiSelect = true), questions[1])
        // The paused turn still ends normally.
        assertEquals(ServerProtocol.FrameMapper.Outcome.Finished, mapper.map(obj("""{"type":"turn.ended","hitl_paused":true}"""), "t"))
    }

    @Test
    fun argsThatAreOneQuestion() {
        val request = ServerProtocol.hitlRequest(
            Http.parse("""{"action_requests":[{"name":"ask_user_question","args":{"text":"Proceed?","options":[{"label":"Yes"},{"label":"No"}]}}]}"""),
        )!!
        assertNull(request.pendingId)
        assertEquals(listOf("Yes", "No"), request.actions.single().questions!!.single().options.map { it.label })
    }

    @Test
    fun approvalKeepsKeyArgsLabelAndAllowedDecisions() {
        val request = ServerProtocol.hitlRequest(
            Http.parse(
                """{"pending_id":7,"action_requests":[
                  {"name":"shell","description":"Clean the build","args":{"cmd":"rm -rf build","cwd":"/tmp","query":"x"}},
                  {"name":"write_file","args":{"file_path":"a.txt","content":"…"}}
                ],"review_configs":[{"action_name":"write_file","allowed_decisions":["approve"]}]}""",
            ),
            toolLabels = mapOf("shell" to "Run command"),
        )!!
        assertEquals("7", request.pendingId)
        assertFalse(request.isQuestion)
        val (shell, write) = request.actions
        assertEquals("Run command", shell.label)
        assertEquals("Clean the build", shell.description)
        assertEquals(listOf("cmd" to "rm -rf build", "query" to "x"), shell.details)
        assertEquals(listOf("file_path" to "a.txt"), write.details)
        assertTrue(shell.allows("reject"))
        assertFalse(write.allows("reject"))
        assertNull(ServerProtocol.hitlRequest(Http.parse("""{"action_requests":[]}""")))
        assertNull(ServerProtocol.hitlRequest(null))
    }

    @Test
    fun historyRestoresThePendingCard() {
        val page = ServerProtocol.historyPage(
            Http.parse("""{"messages":[],"hitl_pending":{"pending_id":"p","action_requests":[{"name":"shell","args":{"command":"ls"}}]}}"""),
        )
        assertEquals("p", page.pending?.pendingId)
        assertNull(ServerProtocol.historyPage(Http.parse("""{"messages":[],"hitl_pending":null}""")).pending)
    }

    @Test
    fun resumeStreamEndsOnDoneAndBodyHasOneDecisionPerAction() {
        val mapper = ServerProtocol.FrameMapper(endsOnDone = true)
        assertEquals(
            listOf(StreamEvent.Text("ok")),
            (mapper.map(obj("""{"type":"token","content":"ok"}"""), "t") as ServerProtocol.FrameMapper.Outcome.Events).events,
        )
        assertEquals(ServerProtocol.FrameMapper.Outcome.Finished, mapper.map(obj("""{"type":"done","hitl_paused":false}"""), "t"))
        // On the socket, `done` ends a segment, not the turn.
        assertEquals(
            ServerProtocol.FrameMapper.Outcome.Events(emptyList()),
            ServerProtocol.FrameMapper().map(obj("""{"type":"done"}"""), "t"),
        )
        val body = ServerProtocol.hitlResume(
            "t",
            "p",
            listOf(HitlDecision.Respond("City: Paris"), HitlDecision.Approve, HitlDecision.Reject()),
        )
        assertEquals(
            obj(
                """{"thread_id":"t","pending_id":"p","decisions":[{"type":"respond","message":"City: Paris"},{"type":"approve"},
                {"type":"reject","message":"Rejected by user"}]}""",
            ),
            body,
        )
        assertFalse(ServerProtocol.hitlResume("t", null, emptyList()).containsKey("pending_id"))
    }

    private val city = HitlQuestion("Which city?", "City", listOf(HitlOption("Paris", null), HitlOption("Rome", null)), false)
    private val extras = HitlQuestion("Which extras?", null, listOf(HitlOption("Museum", null), HitlOption("Food", null)), true)

    @Test
    fun answersFormatOneLinePerQuestion() {
        assertEquals(
            "City: Rome\nWhich extras?: Museum; Food; late checkout",
            HitlAnswers.format(listOf(city, extras), listOf(HitlAnswer(setOf(1)), HitlAnswer(setOf(1, 0), " late checkout "))),
        )
        assertEquals("Which extras?: Food", HitlAnswers.format(listOf(city, extras), listOf(HitlAnswer(), HitlAnswer(setOf(1)))))
    }

    @Test
    fun composerTextAnswersTheOpenQuestion() {
        assertEquals("City: Berlin", HitlAnswers.withComposerText(listOf(city), emptyList(), " Berlin "))
        // Fills the first unanswered question.
        assertEquals(
            "City: Paris\nWhich extras?: spa",
            HitlAnswers.withComposerText(listOf(city, extras), listOf(HitlAnswer(setOf(0))), "spa"),
        )
        // Nothing picked and several questions: sent as typed.
        assertEquals("Paris, no extras", HitlAnswers.withComposerText(listOf(city, extras), emptyList(), "Paris, no extras"))
    }

    @Test
    fun composerTextDeclinesAnApproval() {
        val approval = ServerProtocol.hitlRequest(Http.parse("""{"action_requests":[{"name":"shell","args":{"command":"ls"}}]}"""))!!
        assertEquals(listOf(HitlDecision.Reject("Use git clean instead")), HitlAnswers.fromComposer(approval, "Use git clean instead", emptyList()))
        val question = HitlRequest("p", listOf(approval.actions[0].copy(name = "ask_user_question", questions = listOf(city))))
        assertEquals(listOf(HitlDecision.Respond("City: Oslo")), HitlAnswers.fromComposer(question, "Oslo", emptyList()))
    }

    @Test
    fun fixedRepliesAndReview() {
        val mixed = HitlRequest(
            "p",
            listOf(
                ServerProtocol.hitlRequest(Http.parse("""{"action_requests":[{"name":"shell","args":{}}]}"""))!!.actions[0],
                ServerProtocol.hitlRequest(Http.parse("""{"action_requests":[{"name":"ask_user_question","args":{"question":"Q?"}}]}"""))!!.actions[0],
            ),
        )
        assertEquals(listOf(HitlDecision.Approve, HitlDecision.Respond("decide")), HitlAnswers.review(mixed, approve = true, questionReply = "decide"))
        assertEquals(listOf(HitlDecision.Reject(), HitlDecision.Respond("closed")), HitlAnswers.review(mixed, approve = false, questionReply = "closed"))
        assertEquals(List(2) { HitlDecision.Respond("You decide") }, HitlAnswers.respondAll(mixed, "You decide"))
    }
}
