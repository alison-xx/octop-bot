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
    @Test fun signupNoticeUsesOnlyPositiveCreditsIssuedToANewAccount() {
        fun credits(json: String) = newSignupCredits(Http.parse(json).jsonObject)
        assertEquals(125.5, credits("""{"isNewUser":true,"signupGrant":{"credits":125.5}}""")!!, 0.0)
        assertNull(credits("""{"isNewUser":false,"signupGrant":{"credits":100}}"""))
        assertNull(credits("""{"isNewUser":true}"""))
        assertEquals("2026-12-08", signupExpiryDayUTC(Http.parse("""{"isNewUser":true,"signupGrant":{"credits":100,"expiresAt":"2026-12-09T01:00:00+08:00"}}""").jsonObject))
        assertNull(signupExpiryDayUTC(Http.parse("""{"isNewUser":true,"signupGrant":{"credits":100}}""").jsonObject))
        for (invalid in listOf("true", "\"100\"", "-1", "0", "1e999")) {
            assertNull(credits("""{"isNewUser":true,"signupGrant":{"credits":$invalid}}"""))
        }
    }

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
        val body = LynxceProtocol.chatBody("look", listOf(byteArrayOf(1, 2, 3)), bot, history, "octop-bot-v1-abc", "tencent/m1", turnId = "t")
        val messages = body["messages"]!!.jsonArray
        assertEquals("system", messages.first().jsonObject["role"]!!.jsonPrimitive.content)
        // System + the last 20 finished turns + the new user message.
        assertEquals(22, messages.size)
        assertEquals("m6", messages[1].jsonObject["content"]!!.jsonPrimitive.content)
        val content = messages.last().jsonObject["content"]!!.jsonArray
        assertEquals("look", content[0].jsonObject["text"]!!.jsonPrimitive.content)
        assertEquals("data:image/jpeg;base64,AQID", content[1].jsonObject["image_url"]!!.jsonObject["url"]!!.jsonPrimitive.content)
        assertEquals("octop-bot-v1-abc", body["sessionId"]!!.jsonPrimitive.content)
        assertEquals("tencent/m1", body["model"]!!.jsonPrimitive.content)
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

        // The wallet, not an enterprise member's monthly allowance.
        assertEquals(12800.5, LynxceProtocol.balance(Http.parse("""{"creditsRemaining":12800.5,"effectiveCreditsRemaining":3}""")))
        assertNull(LynxceProtocol.balance(Http.parse("""{"plan":"free","credits":12}""")))
    }

    @Test
    fun creditsShowDecimalsOnlyBelowOneThousand() {
        assertEquals("4,454,029", LynxceProtocol.formatCredits(4_454_029.04))
        assertEquals("12,800", LynxceProtocol.formatCredits(12_800.0))
        assertEquals("1,000", LynxceProtocol.formatCredits(1_000.99))
        assertEquals("12.50", LynxceProtocol.formatCredits(12.5))
        assertEquals("999.99", LynxceProtocol.formatCredits(999.999))
        assertEquals("100", LynxceProtocol.formatCredits(100.0))
        assertEquals("0", LynxceProtocol.formatCredits(0.0))
    }

    @Test
    fun midStreamQuotaErrorIsOutOfCredits() {
        fun kind(chunk: String) = try {
            LynxceProtocol.parseChunk(chunk)
            null
        } catch (error: ApiException) {
            error.kind
        }
        assertEquals(ApiException.Kind.Credits, kind("""{"error":{"code":"insufficient_quota","message":"no"}}"""))
        assertEquals(ApiException.Kind.Credits, kind("""{"error":{"message":"Insufficient credits"}}"""))
        assertEquals(ApiException.Kind.Server, kind("""{"error":{"message":"model overloaded"}}"""))
    }

    @Test
    fun checkoutOnlyOpensTheOfficialRechargePage() {
        val now = java.time.Instant.parse("2026-11-24T00:00:00Z")
        val ticket = "x." + "a".repeat(43)
        fun link(url: String, expires: String = "2026-11-24T00:15:00Z", token: String = ticket) =
            Http.parse("""{"url":"$url","token":"$token","expiresAt":"$expires"}""")
        val good = LynxceProtocol.CHECKOUT_PORTAL + ticket
        assertEquals(good, LynxceProtocol.checkoutUrl(link(good), now))
        val boost = LynxceProtocol.boostTab(good)
        assertEquals("$good&tab=boost", boost)
        assertEquals(boost, LynxceProtocol.checkoutUrl(link(boost), now))
        assertEquals(boost, LynxceProtocol.boostTab(boost))
        assertNull(LynxceProtocol.checkoutUrl(link("https://evil.example/recharge?token=$ticket&tab=boost"), now))
        assertNull(LynxceProtocol.checkoutUrl(link("https://evil.example/recharge?token=$ticket"), now))
        assertNull(LynxceProtocol.checkoutUrl(link(LynxceProtocol.CHECKOUT_PORTAL + "mcrt1." + "a".repeat(43)), now))
        assertNull(LynxceProtocol.checkoutUrl(link(good, token = "x." + "b".repeat(43)), now))
        assertNull(LynxceProtocol.checkoutUrl(link(good, expires = "2026-11-24T01:00:00Z"), now))
        assertNull(LynxceProtocol.checkoutUrl(link(good, expires = "2026-11-23T23:59:00Z"), now))
    }

    @Test
    fun codeTargetIsEmailWhenItHasAnAt() {
        assertEquals(LynxceProtocol.Target.Phone("13800138000"), LynxceProtocol.Target.of("  13800138000 "))
        assertEquals(LynxceProtocol.Target.Phone("+86 138 0013 8000"), LynxceProtocol.Target.of("+86 138 0013 8000"))
        assertEquals(LynxceProtocol.Target.Email("a@b.cn"), LynxceProtocol.Target.of(" a@b.cn"))
        assertNull(LynxceProtocol.Target.of("   "))
        assertTrue(LynxceProtocol.isValidCode("012345"))
        assertFalse(LynxceProtocol.isValidCode("12345"))
        assertFalse(LynxceProtocol.isValidCode("1234567"))
        assertFalse(LynxceProtocol.isValidCode("12a456"))
        assertFalse(LynxceProtocol.isValidCode("１２３４５６"))
    }

    @Test
    fun codeRequestAndLoginBodies() {
        val phone = LynxceProtocol.Target.Phone("13800138000")
        val email = LynxceProtocol.Target.Email("a@b.cn")
        assertEquals("/api/auth/phone-code", LynxceProtocol.codeRequestPath(phone))
        assertEquals("/api/auth/email-code", LynxceProtocol.codeRequestPath(email))
        assertEquals("/api/auth/phone-login", LynxceProtocol.codeLoginPath(phone))
        assertEquals("/api/auth/email-login", LynxceProtocol.codeLoginPath(email))
        assertEquals("""{"phone":"13800138000"}""", LynxceProtocol.codeRequestBody(phone, chinese = true).toString())
        assertEquals("""{"email":"a@b.cn","locale":"zh-CN"}""", LynxceProtocol.codeRequestBody(email, chinese = true).toString())
        assertEquals("""{"email":"a@b.cn","locale":"en"}""", LynxceProtocol.codeRequestBody(email, chinese = false).toString())
        assertEquals("""{"phone":"13800138000","code":"123456"}""", LynxceProtocol.codeLoginBody(phone, "123456").toString())
        assertEquals("""{"email":"a@b.cn","code":"000000"}""", LynxceProtocol.codeLoginBody(email, "000000").toString())
    }

    @Test
    fun codeLoginGrantMatchesPasswordLogin() {
        val data = LynxceProtocol.unwrap(
            200,
            """{"code":0,"data":{"accessToken":"a","refreshToken":"r","user":{"id":42,"displayName":" "}}}""",
        )
        val grant = LynxceProtocol.grant(data)
        assertEquals("42", grant.accountId)
        assertNull(grant.displayName)
        assertEquals("a", grant.accessToken)
        assertEquals("r", grant.refreshToken)
        assertFailure(ApiException.Kind.Server, 502) { LynxceProtocol.grant(Http.parse("""{"accessToken":"a","refreshToken":"r"}""")) }
    }

    @Test
    fun codeFailuresMapToFriendlyKinds() {
        fun failure(status: Int, body: String): ApiException =
            try {
                LynxceProtocol.unwrap(status, body)
                throw AssertionError("expected failure")
            } catch (error: ApiException) {
                error
            }
        val wrong = failure(401, """{"error":{"code":"sms_code_invalid","message":"验证码错误"},"message":"验证码错误"}""")
        assertEquals(LynxceProtocol.CodeFailure.InvalidCode, LynxceProtocol.codeFailure(wrong))
        val often = failure(429, """{"error":{"code":"rate_limited","message":"请求过于频繁"}}""")
        assertEquals(LynxceProtocol.CodeFailure.TooFrequent, LynxceProtocol.codeFailure(often))
        // Malformed input keeps the server's readable message.
        val invalid = failure(400, """{"error":{"code":"validation_error","message":"手机号格式不正确"},"message":"手机号格式不正确"}""")
        assertNull(LynxceProtocol.codeFailure(invalid))
        assertEquals(ApiException.Kind.Rejected, invalid.kind)
        assertEquals("手机号格式不正确", invalid.message)
        assertNull(LynxceProtocol.codeFailure(ApiException.network()))
        assertNull(LynxceProtocol.codeFailure(IllegalStateException()))
    }

    @Test
    fun everyLynxceCallNamesOctopBotAsTheSignupSite() {
        val signIn = LynxceProtocol.headers(null)
        assertEquals("octop-bot", signIn["X-Lynxce-Signup-Site"])
        assertEquals("octopbot", signIn["X-Lynxce-App"])
        assertEquals("web", signIn["X-Lynxce-Client"])
        assertEquals(null, signIn["Authorization"])
        val signedIn = LynxceProtocol.headers("t")
        assertEquals("octop-bot", signedIn["X-Lynxce-Signup-Site"])
        assertEquals("Bearer t", signedIn["Authorization"])
    }
}
