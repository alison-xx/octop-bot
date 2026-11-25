import CryptoKit
import SwiftUI
import XCTest
@testable import OctopBot

@MainActor
final class CharacterTests: XCTestCase {
    func testComputerCreditCodesAreRecognized() {
        XCTAssertTrue(APIError.isCreditsRequired(APIError.computerCreditsRequired))
        XCTAssertTrue(APIError.isCreditsRequired(APIError.computerPausedNoCredits))
        XCTAssertFalse(APIError.isCreditsRequired(nil))
    }

    func testCreditScenariosAndErrorDetails() {
        for kind in ["text", "image", "video"] {
            let details = CreditDetails(["need": 12.2, "balance": 3, "kind": kind])
            XCTAssertEqual(creditScenario(code: APIError.creditsRequired, details: details)?.kind.rawValue, kind)
        }
        let details = CreditDetails(["need": 12.2, "balance": 3])
        XCTAssertEqual(creditScenario(code: APIError.computerCreditsRequired, details: details)?.kind, .computer)
        XCTAssertEqual(creditScenario(code: APIError.computerPausedNoCredits, details: details)?.kind, .paused)
        XCTAssertNil(creditScenario(code: APIError.creditsRequired, details: CreditDetails(["balance": 3, "kind": "text"])))
        XCTAssertNil(creditScenario(code: APIError.creditsRequired, details: CreditDetails(["need": 1, "kind": "text"])))
        XCTAssertNil(creditScenario(code: APIError.creditsRequired, details: CreditDetails(["need": 1, "balance": 2, "kind": "unknown"])))
        // A paused computer needs no figures; starting one needs only `need`.
        XCTAssertEqual(creditScenario(code: APIError.computerPausedNoCredits, details: nil)?.kind, .paused)
        XCTAssertEqual(creditScenario(code: APIError.computerCreditsRequired, details: CreditDetails(["need": 9]))?.need, 9)
        XCTAssertNil(creditScenario(code: APIError.computerCreditsRequired, details: CreditDetails(["balance": 2])))
        let data = Data(#"{"error":{"code":"BOT_CLOUD_CREDITS_REQUIRED","details":{"need":12.2,"balance":3,"kind":"image"}}}"#.utf8)
        let http = APIError.from(status: 402, message: nil, code: HTTP.errorCode(data), details: HTTP.errorDetails(data))
        let frame = ServerFrameMapper.error(["error_code": APIError.creditsRequired, "error_details": ["need": 12.2, "balance": 3, "kind": "image"]])
        let provider = ServerFrameMapper.error(["error_code": "insufficient_balance"])
        XCTAssertEqual(provider.kind, .server)
        XCTAssertEqual(provider.message, L("error.providerBalance"))
        XCTAssertEqual(http.details, frame.details)
        XCTAssertEqual(creditScenario(code: frame.code, details: frame.details)?.kind, .image)
    }

    func testLowBalanceDismissalLasts24Hours() {
        XCTAssertTrue(AppModel.lowBalanceIsDismissed(at: 1_000, now: 1_000 + 86_399))
        XCTAssertFalse(AppModel.lowBalanceIsDismissed(at: 1_000, now: 1_000 + 86_400))
        XCTAssertFalse(AppModel.lowBalanceIsDismissed(at: 0, now: 1_000))
    }

    func testEveryShapeParsesInsideTheViewBox() {
        let library = Characters.library
        XCTAssertGreaterThanOrEqual(library.order.count, 19)
        XCTAssertEqual(Characters.shapeIds.first, "octop")
        for id in library.order {
            let shape = try! XCTUnwrap(library.shapes[id])
            let box = shape.body.boundingRect
            XCTAssertFalse(shape.body.isEmpty, id)
            XCTAssertGreaterThan(box.width, 40, id)
            XCTAssertGreaterThan(box.height, 40, id)
            XCTAssertGreaterThanOrEqual(box.minX, -1, id)
            XCTAssertLessThanOrEqual(box.maxX, 101, id)
            XCTAssertGreaterThanOrEqual(box.minY, -1, id)
            XCTAssertLessThanOrEqual(box.maxY, 101, id)
            XCTAssertFalse(shape.eyes.isEmpty, id)
        }
        XCTAssertEqual(library.inkOrder.first, "red")
        XCTAssertEqual(library.aurora.count, 3)
    }

    func testCompactPathNumbers() {
        // "1.5-.4" is two numbers, ".1.2" is two numbers, and pairs after M are linetos.
        let path = SVGPath.parse("M10 10l1.5-.4 .1.2z M50 50 60 60")
        let box = path.boundingRect
        XCTAssertEqual(box.minX, 10, accuracy: 0.001)
        XCTAssertEqual(box.maxX, 60, accuracy: 0.001)
        XCTAssertEqual(box.minY, 9.6, accuracy: 0.001)
    }

    func testCurvesAndArcs() {
        // A circle drawn with two arcs, and a heart with cubic curves (the soft character style).
        let circle = SVGPath.parse("M50 8a42 42 0 1 1 0 84a42 42 0 1 1 0-84z").boundingRect
        XCTAssertEqual(circle.minX, 8, accuracy: 0.5)
        XCTAssertEqual(circle.maxX, 92, accuracy: 0.5)
        XCTAssertEqual(circle.maxY, 92, accuracy: 0.5)
        let heart = SVGPath.parse("M50 90C28 78 8 62 8 40C8 24 20 12 34 12C42 12 47 16 50 22C53 16 58 12 66 12C80 12 92 24 92 40C92 62 72 78 50 90Z").boundingRect
        XCTAssertEqual(heart.minX, 8, accuracy: 0.5)
        XCTAssertEqual(heart.maxY, 90, accuracy: 0.5)
        XCTAssertEqual(SVGPath.parse("M0 0H10V10h-10z").boundingRect.size, CGSize(width: 10, height: 10))
    }

    func testPoseBlinksAndBobs() {
        XCTAssertLessThan(CharacterPose(time: 0.06, motion: .idle, size: 100).blink, 0.2)
        XCTAssertEqual(CharacterPose(time: 1, motion: .idle, size: 100).blink, 1)
        XCTAssertLessThan(CharacterPose(time: 0.525, motion: .working, size: 100).offsetY, -3.9)
    }
}

@MainActor
final class StreamTests: XCTestCase {
    func testSSEParserJoinsDataAndSplitsOnBlankLines() {
        var parser = SSEParser()
        XCTAssertNil(parser.feed("event: chunk"))
        XCTAssertNil(parser.feed("data: {\"a\":1}"))
        XCTAssertNil(parser.feed(": keep-alive"))
        XCTAssertEqual(parser.feed(""), SSEEvent(event: "chunk", data: "{\"a\":1}"))
        XCTAssertNil(parser.feed("data: [DONE]\r"))
        XCTAssertEqual(parser.finish(), SSEEvent(event: nil, data: "[DONE]"))
    }

    func testLynxceChunks() throws {
        let text = try LynxceBackend.parseChunk(#"{"choices":[{"delta":{"content":"你好"}}]}"#)
        guard case .text(let value) = text.first else { return XCTFail() }
        XCTAssertEqual(value, "你好")
        let thinking = try LynxceBackend.parseChunk(#"{"choices":[{"delta":{"reasoning_content":"hmm"}}]}"#)
        guard case .thinking(let thought) = thinking.first else { return XCTFail() }
        XCTAssertEqual(thought, "hmm")
        XCTAssertTrue(try LynxceBackend.parseChunk(#"{"usage":{"prompt_tokens":3}}"#).isEmpty)
        XCTAssertThrowsError(try LynxceBackend.parseChunk(#"{"error":{"message":"quota"}}"#)) { error in
            XCTAssertEqual((error as? APIError)?.message, "quota")
        }
    }

    func testLynxceEnvelope() throws {
        let data = try LynxceBackend.unwrap(Data(#"{"code":0,"data":{"x":1}}"#.utf8), status: 200)
        XCTAssertEqual((data as? [String: Any])?["x"] as? Int, 1)
        XCTAssertThrowsError(try LynxceBackend.unwrap(Data(#"{"code":402,"message":"no credits"}"#.utf8), status: 200)) { error in
            XCTAssertEqual((error as? APIError)?.kind, .credits)
        }
        XCTAssertThrowsError(try LynxceBackend.unwrap(Data(#"{"code":401}"#.utf8), status: 401)) { error in
            XCTAssertEqual((error as? APIError)?.kind, .unauthorized)
        }
    }

    func testLynxceChatBodyCarriesPersonaHistoryAndImages() {
        let bot = BotProfile(id: "x", name: "X", look: .fallback, isChief: false, systemPrompt: "Be brief")
        let history = [ChatMessage(role: .user, text: "hi"), ChatMessage(role: .assistant, text: "", status: .failed("x"))]
        let body = LynxceBackend.chatBody(text: "look", images: [Data([1, 2])], bot: bot, history: history, sessionId: "octop-bot-v1-a", model: nil)
        let messages = body["messages"] as! [[String: Any]]
        XCTAssertEqual(messages.count, 3)
        XCTAssertEqual(messages[0]["role"] as? String, "system")
        XCTAssertEqual((messages[2]["content"] as? [[String: Any]])?.count, 2)
        XCTAssertNil(body["model"])
        XCTAssertEqual(body["sessionId"] as? String, "octop-bot-v1-a")
    }

    func testDesktopRoleBlockIsHidden() {
        XCTAssertEqual(LynxceBackend.stripRole("hello\n\n[Octop Bot role/v1] {\"name\":\"R\"}"), "hello")
        XCTAssertEqual(LynxceBackend.stripRole("plain"), "plain")
    }
}

@MainActor
final class LynxceCodeLoginTests: XCTestCase {
    func testTargetIsEmailWithAtSignOtherwisePhone() {
        XCTAssertEqual(LynxceBackend.CodeTarget("  a@b.cn \n"), .email("a@b.cn"))
        XCTAssertEqual(LynxceBackend.CodeTarget(" 138 0013 8000 "), .phone("138 0013 8000"))
        XCTAssertEqual(LynxceBackend.CodeTarget("+8613800138000"), .phone("+8613800138000"))
        XCTAssertNil(LynxceBackend.CodeTarget("   "))
        XCTAssertTrue(LynxceBackend.CodeTarget("a@b.cn")!.isEmail)
        XCTAssertFalse(LynxceBackend.CodeTarget("13800138000")!.isEmail)
    }

    func testSignInPointsAtTheAccountFirstThenTheCodeOrPassword() {
        XCTAssertEqual(OnboardingView.missingField(account: "  ", usePassword: false), .account)
        XCTAssertEqual(OnboardingView.missingField(account: "138 0013 8000", usePassword: false), .code)
        XCTAssertEqual(OnboardingView.missingField(account: "a@b.cn", usePassword: false), .code)
        XCTAssertEqual(OnboardingView.missingField(account: " ", usePassword: true), .account)
        XCTAssertEqual(OnboardingView.missingField(account: "alice", usePassword: true), .password)
    }

    func testARealAccountCardShowsOnlyTheTotalUntilTheMemberProfileComes() {
        let card = AccountSummary(name: "alice", credits: 120)
        XCTAssertNil(card.tier)
        XCTAssertNil(card.accountHint)
        XCTAssertNil(card.expiring)
        XCTAssertNil(card.permanent)
        XCTAssertEqual(card.credits, 120)
    }

    func testCodeMustBeSixDigits() {
        XCTAssertTrue(LynxceBackend.isCode("012345"))
        XCTAssertFalse(LynxceBackend.isCode("12345"))
        XCTAssertFalse(LynxceBackend.isCode("1234567"))
        XCTAssertFalse(LynxceBackend.isCode("12a456"))
        XCTAssertFalse(LynxceBackend.isCode("١٢٣٤٥٦"))
    }

    func testRequestBodies() {
        let phone = LynxceBackend.CodeTarget.phone("13800138000")
        let email = LynxceBackend.CodeTarget.email("a@b.cn")
        XCTAssertEqual(phone.codeRequest(chinese: true).path, "/api/auth/phone-code")
        XCTAssertEqual(phone.codeRequest(chinese: true).body, ["phone": "13800138000"])
        XCTAssertEqual(email.codeRequest(chinese: true).path, "/api/auth/email-code")
        XCTAssertEqual(email.codeRequest(chinese: true).body, ["email": "a@b.cn", "locale": "zh-CN"])
        XCTAssertEqual(email.codeRequest(chinese: false).body["locale"], "en")
        XCTAssertEqual(phone.loginRequest(code: "123456").path, "/api/auth/phone-login")
        XCTAssertEqual(phone.loginRequest(code: "123456").body, ["phone": "13800138000", "code": "123456"])
        XCTAssertEqual(email.loginRequest(code: "123456").path, "/api/auth/email-login")
        XCTAssertEqual(email.loginRequest(code: "123456").body, ["email": "a@b.cn", "code": "123456"])
    }

    func testServerCodeBodies() {
        XCTAssertEqual(ServerBackend.lynxceCodeBody(target: " a@b.cn ", chinese: true), ["target": "a@b.cn", "locale": "zh"])
        XCTAssertEqual(
            ServerBackend.lynxceCodeBody(target: "13800138000", code: "123456", chinese: false),
            ["target": "13800138000", "code": "123456", "locale": "en"]
        )
    }

    func testCodeEntryCountsDownOnlyAfterASuccessfulSend() async {
        let entry = CodeEntry()
        XCTAssertFalse(entry.canSend(to: "  "))
        XCTAssertTrue(entry.canSend(to: "13800138000"))
        let failure = await entry.send { throw APIError(kind: .rejected, status: 429, message: nil) }
        XCTAssertEqual((failure as? APIError)?.status, 429)
        XCTAssertEqual(entry.countdown, 0)
        XCTAssertFalse(entry.sent)
        let none = await entry.send {}
        XCTAssertNil(none)
        XCTAssertEqual(entry.countdown, 60)
        XCTAssertFalse(entry.canSend(to: "13800138000"))
        entry.reset()
        XCTAssertTrue(entry.canSend(to: "13800138000"))
    }

    func testErrorMapping() throws {
        let preferences = Preferences.shared
        let original = preferences.language
        defer { preferences.language = original }
        preferences.language = .chinese
        func error(_ status: Int, _ body: String) -> Error {
            do { _ = try LynxceBackend.unwrap(Data(body.utf8), status: status) } catch { return error }
            XCTFail("expected a throw")
            return APIError.network
        }
        let wrong = error(401, #"{"error":{"code":"email_code_invalid","message":"邮箱验证码错误或已失效,请重新获取。"},"statusCode":401}"#)
        XCTAssertEqual(LynxceBackend.codeMessage(for: wrong), "验证码错误或已过期，请重新获取")
        let tooMany = error(429, #"{"error":{"code":"rate_limited","message":"Too Many Requests"}}"#)
        XCTAssertEqual(LynxceBackend.codeMessage(for: tooMany), "发送太频繁，请稍后再试")
        let invalid = error(400, #"{"error":{"code":"validation_error","message":"手机号：至少需要 6 个字符"},"message":"手机号：至少需要 6 个字符"}"#)
        XCTAssertEqual(LynxceBackend.codeMessage(for: invalid), "手机号：至少需要 6 个字符")
        XCTAssertEqual(LynxceBackend.codeMessage(for: APIError.network), APIError.network.localizedDescription)
        preferences.language = .english
        XCTAssertEqual(LynxceBackend.codeMessage(for: wrong), "The code is wrong or has expired. Please get a new one.")
    }
}

@MainActor
final class ServerTests: XCTestCase {
    func testBotPreparationFieldsAndPolling() throws {
        let legacy = try XCTUnwrap(ServerBackend.bot(["agent_id": "old"]))
        let starting = try XCTUnwrap(ServerBackend.bot(["agent_id": "new", "state": "starting", "preparing": true]))
        let failed = try XCTUnwrap(ServerBackend.bot(["agent_id": "bad", "state": "failed", "preparing": false, "last_error": "problem"]))
        XCTAssertTrue(legacy.canSend)
        XCTAssertNil(legacy.state)
        XCTAssertFalse(starting.canSend)
        XCTAssertEqual(starting.state, "starting")
        XCTAssertFalse(failed.canSend)
        XCTAssertEqual(failed.lastError, "problem")
        XCTAssertTrue(shouldPollBots([legacy, starting, failed]))
        XCTAssertFalse(shouldPollBots([legacy, failed]))
        let oldJSON = #"{"id":"old","name":"Old","look":{"shape":"gumdrop","color":"blue"},"isChief":false}"#.data(using: .utf8)!
        XCTAssertTrue(try JSONDecoder().decode(BotProfile.self, from: oldJSON).canSend)
    }

    func testAddressNormalization() {
        XCTAssertEqual(ServerBackend.normalize("nas.local:8080/")?.absoluteString, "https://nas.local:8080")
        XCTAssertEqual(ServerBackend.normalize("http://10.0.0.2:8080")?.absoluteString, "http://10.0.0.2:8080")
        XCTAssertNil(ServerBackend.normalize("ftp://x"))
        XCTAssertNil(ServerBackend.normalize(""))
    }

    func testLooksFollowTheDashboard() {
        XCTAssertEqual(ServerBackend.normalizedLook(shape: "whale", color: "deepseek", chief: true), .chief)
        XCTAssertEqual(ServerBackend.normalizedLook(shape: "whale", color: "deepseek", chief: false), Look(shape: "gumdrop", color: "blue"))
        XCTAssertEqual(ServerBackend.normalizedLook(shape: "acorn", color: "green", chief: false), Look(shape: "acorn", color: "green"))
        XCTAssertEqual(ServerBackend.normalizedLook(shape: nil, color: nil, chief: true), .chief)
    }

    func testHistoryFoldsToolRowsAndSegments() {
        let rows: [[String: Any]] = [
            ["role": "user", "content": [["type": "text", "text": "find it"]], "timestamp": 1_700_000_000_000.0],
            ["role": "assistant", "content": [["type": "thinking", "thinking": "plan"], ["type": "tool_use", "id": "t1", "name": "web_search"]]],
            ["role": "tool", "content": [["type": "tool_result", "id": "t1", "output": "…"]]],
            ["role": "assistant", "content": [["type": "text", "text": "Found."]]],
        ]
        let messages = ServerBackend.history(rows, labels: ["web_search": "联网搜索"])
        XCTAssertEqual(messages.count, 2)
        XCTAssertEqual(messages[1].text, "Found.")
        XCTAssertEqual(messages[1].thinking, "plan")
        XCTAssertEqual(messages[1].tools.map(\.name), ["联网搜索"])
    }

    func testPausedTurnSummaryRowIsNotRepeated() {
        func row(_ id: String?, _ text: String) -> [String: Any] {
            var row: [String: Any] = ["role": "assistant", "content": [["type": "text", "text": text]]]
            if let id { row["id"] = id }
            return row
        }
        let rows: [[String: Any]] = [
            ["role": "user", "content": "plan my day"],
            row("a", "First part."), row("b", "Second part."), row(nil, "First part.Second part."),
        ]
        let messages = ServerBackend.history(rows)
        XCTAssertEqual(messages.count, 2)
        XCTAssertEqual(messages[1].text, "First part.\n\nSecond part.")
    }

    func testHitlParsingAndAnswers() throws {
        let frame: [String: Any] = ["value": [
            "pending_id": "p1",
            "action_requests": [[
                "name": "ask_user_question",
                "args": #"{"questions":[{"header":"Focus","question":"What matters today?","multi_select":true,"options":[{"label":"Ship"},{"label":"Learn"}]},{"question":"Fixed times?"}]}"#,
            ]],
        ]]
        let pause = try XCTUnwrap(HitlPause.parse(frame))
        XCTAssertEqual(pause.pendingId, "p1")
        XCTAssertTrue(pause.isQuestion)
        XCTAssertEqual(pause.questions.count, 2)
        XCTAssertTrue(pause.questions[0].multiSelect)
        XCTAssertEqual(pause.questions[0].options.map(\.label), ["Ship", "Learn"])
        XCTAssertNil(HitlPause.answerMessage(pause.questions, [.init(picked: ["Ship"]), .init()]))
        XCTAssertEqual(
            HitlPause.answerMessage(pause.questions, [.init(picked: ["Ship", "Learn"]), .init(other: "none")]),
            "Focus: Ship; Learn\nFixed times?: none"
        )

        let approval = try XCTUnwrap(HitlPause.parse(
            ["action_requests": [["name": "execute", "args": ["command": "rm -rf build"], "description": "Clean"]]],
            labels: ["execute": "Run command"]
        ))
        XCTAssertFalse(approval.isQuestion)
        XCTAssertEqual(approval.actions[0].label, "Run command")
        XCTAssertEqual(approval.actions[0].details, [.init(key: "command", value: "rm -rf build")])

        var mapper = ServerFrameMapper()
        guard case .events(let events) = try mapper.map(["type": "hitl_required", "request": frame]),
              case .pause(let mapped)? = events.first else { return XCTFail("expected a pause") }
        XCTAssertEqual(mapped.pendingId, "p1")
        guard case .finished = try mapper.map(["type": "turn.ended", "hitl_paused": true]) else { return XCTFail() }
        var resume = ServerFrameMapper(endsOnDone: true)
        guard case .finished = try resume.map(["type": "done"]) else { return XCTFail() }
    }

    func testFrameMapping() throws {
        var mapper = ServerFrameMapper()
        guard case .events(let start) = try mapper.map(["type": "tool_call_chunk", "id": "c1", "display_name": "Search"]) else { return XCTFail() }
        XCTAssertEqual(start.count, 1)
        guard case .events(let again) = try mapper.map(["type": "tool_call_chunk", "id": "c1", "args": "{"]) else { return XCTFail() }
        XCTAssertTrue(again.isEmpty)
        guard case .events(let done) = try mapper.map(["type": "tool_result", "messages": [["tool_call_id": "c1"]]]) else { return XCTFail() }
        guard case .tool(_, let name, let finished) = done.first else { return XCTFail() }
        XCTAssertEqual(name, "Search")
        XCTAssertTrue(finished)
        guard case .events(let token) = try mapper.map(["type": "token", "content": "hi"]), case .text("hi") = token.first else { return XCTFail() }
        XCTAssertThrowsError(try mapper.map(["type": "error", "message": "boom"]))
        guard case .finished = try mapper.map(["type": "turn.ended"]) else { return XCTFail() }
    }

    func testMentions() {
        let members = [
            BotProfile(id: "a1", name: "Ann", look: .fallback, isChief: false),
            BotProfile(id: "a2", name: "Ann Lee", look: .fallback, isChief: false),
            BotProfile(id: "b1", name: "Bob", look: .fallback, isChief: false),
        ]
        XCTAssertEqual(GroupRoom.mentions(in: "@Ann Lee please check", members: members), ["a2"])
        XCTAssertEqual(Set(GroupRoom.mentions(in: "@Ann and @Bob", members: members)), ["a1", "b1"])
        XCTAssertEqual(GroupRoom.mentions(in: "> @Bob said\nok", members: members), [])
        XCTAssertEqual(GroupRoomView.mentionQuery("hey @An"), "An")
        XCTAssertNil(GroupRoomView.mentionQuery("mail@x"))
    }
}

@MainActor
final class TextTests: XCTestCase {
    func testMarkdownBlocks() {
        let blocks = MarkdownBlock.parse("# Title\n\nSome **bold** text\n\n- one\n- two\n\n```swift\nlet a = 1\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |")
        XCTAssertEqual(blocks.count, 5)
        XCTAssertEqual(blocks[0], .heading(1, "Title"))
        XCTAssertEqual(blocks[3], .code("swift", "let a = 1"))
        XCTAssertEqual(blocks[4], .table([["a", "b"], ["1", "2"]]))
    }

    func testSpeechChunks() {
        XCTAssertEqual(Speaker.plain("**Hi** [link](http://x) `code`"), "Hi link code")
        let chunks = Speaker.chunks(String(repeating: "这是一句话。", count: 40))
        XCTAssertGreaterThan(chunks.count, 1)
        XCTAssertLessThanOrEqual(chunks[0].count, 80)
    }
}

@MainActor
final class LanguageTests: XCTestCase {
    func testInAppLanguageSwitchesStrings() {
        let preferences = Preferences.shared
        let original = preferences.language
        defer { preferences.language = original }
        preferences.language = .chinese
        XCTAssertEqual(L("common.copy"), "复制")
        XCTAssertEqual(L("error.server %lld", 502), "服务器出错（502），请稍后再试。")
        XCTAssertEqual(preferences.language.httpTag, "zh-CN")
        preferences.language = .english
        XCTAssertEqual(L("common.copy"), "Copy")
        XCTAssertEqual(LocalBots.builtIns[1].name, "Researcher")
    }
}

@MainActor
final class DirectoryTests: XCTestCase {
    private func bot(_ id: String, chief: Bool = false) -> BotProfile {
        BotProfile(id: id, name: id, look: .fallback, isChief: chief)
    }

    func testChiefPinnedThenNewestReplyThenDirectoryOrder() {
        let bots = [bot("a"), bot("chief", chief: true), bot("b"), bot("c"), bot("d")]
        let now = Date()
        let previews: [String: AppModel.Preview] = [
            "c": .init(text: "x", date: now.addingTimeInterval(-60)),
            "d": .init(text: "y", date: now),
            "chief": .init(text: "z", date: now.addingTimeInterval(10)),
        ]
        XCTAssertEqual(AppModel.order(bots, previews: previews).map(\.id), ["chief", "d", "c", "a", "b"])
    }
}

@MainActor
final class TimeTests: XCTestCase {
    private var calendar: Calendar {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "Asia/Shanghai")!
        return c
    }

    private func date(_ y: Int, _ m: Int, _ d: Int, _ h: Int, _ min: Int) -> Date {
        calendar.date(from: DateComponents(year: y, month: m, day: d, hour: h, minute: min))!
    }

    func testSeparatorGap() {
        let start = date(2026, 11, 23, 14, 0)
        XCTAssertTrue(TimeLabel.needsSeparator(start, after: nil))
        XCTAssertFalse(TimeLabel.needsSeparator(start.addingTimeInterval(600), after: start))
        XCTAssertTrue(TimeLabel.needsSeparator(start.addingTimeInterval(601), after: start))
    }

    func testSeparatorText() {
        let preferences = Preferences.shared
        let original = preferences.language
        defer { preferences.language = original }
        preferences.language = .chinese
        let now = date(2026, 11, 23, 15, 0)
        XCTAssertEqual(TimeLabel.text(date(2026, 11, 23, 14, 5), now: now, calendar: calendar), "14:05")
        XCTAssertEqual(TimeLabel.text(date(2026, 11, 22, 9, 30), now: now, calendar: calendar), "昨天 09:30")
        XCTAssertTrue(TimeLabel.text(date(2026, 11, 20, 14, 5), now: now, calendar: calendar).contains("11月20日"))
        XCTAssertTrue(TimeLabel.text(date(2025, 3, 1, 8, 0), now: now, calendar: calendar).contains("2025"))
        preferences.language = .english
        XCTAssertEqual(TimeLabel.text(date(2026, 11, 22, 9, 30), now: now, calendar: calendar), "Yesterday 09:30")
    }

    func testHistoryBuckets() {
        let now = date(2026, 11, 23, 15, 0)
        XCTAssertEqual(DateBucket.of(date(2026, 11, 23, 0, 1), now: now, calendar: calendar), .today)
        XCTAssertEqual(DateBucket.of(date(2026, 11, 22, 23, 0), now: now, calendar: calendar), .yesterday)
        XCTAssertEqual(DateBucket.of(date(2026, 11, 17, 12, 0), now: now, calendar: calendar), .week)
        XCTAssertEqual(DateBucket.of(date(2026, 11, 1, 12, 0), now: now, calendar: calendar), .earlier)
        XCTAssertEqual(DateBucket.of(nil, now: now, calendar: calendar), .earlier)
    }
}

/// A backend whose replies the test finishes by hand.
@MainActor
private final class FakeBackend: ChatBackend {
    var supportsGroups: Bool { false }
    var accountName: String { "tester" }
    var photo: AccountPhoto?
    var delayPhoto = false
    var pendingPhoto: CheckedContinuation<Void, Never>?
    func accountPhoto() async -> AccountPhoto? {
        if delayPhoto { await withCheckedContinuation { pendingPhoto = $0 } }
        return photo
    }
    var sent: [String] = []
    var replies: [AsyncThrowingStream<StreamEvent, Error>.Continuation] = []

    func bots() async throws -> [BotProfile] { [BotProfile(id: "b", name: "B", look: .fallback, isChief: true)] }
    var listFailures = 0
    var directory: [ConversationSummary] = []
    func conversations(for bot: BotProfile) async throws -> [ConversationSummary] {
        if listFailures > 0 { listFailures -= 1; throw APIError.network }
        return directory
    }
    func messages(in conversation: ConversationSummary, bot: BotProfile) async throws -> [ChatMessage] { [] }
    func models() async throws -> [ModelOption] { [] }
    func send(_ text: String, messageId: String, images: [Data], to bot: BotProfile, conversation: String?, history: [ChatMessage], model: String?) -> AsyncThrowingStream<StreamEvent, Error> {
        sent.append(text)
        return AsyncThrowingStream { replies.append($0) }
    }
    func stop(conversation: String, bot: BotProfile) async {}
    func deleteConversation(_ conversation: ConversationSummary, bot: BotProfile) async throws {}
    func transcribe(_ audio: Data) async throws -> String? { nil }
    func speech(for text: String) async throws -> Data? { nil }
    func registerPush(token: String) async {}
    func signOut() async {}
}

@MainActor
final class QueueTests: XCTestCase {
    func testPersonalDefaultSkipsSharedAndUnknownOwnershipAndPrefersActivePersonalThread() {
        func row(_ id: String, _ owned: Bool?, _ active: Bool) -> ConversationSummary {
            ConversationSummary(id: id, title: "", updatedAt: nil, botId: nil, owned: owned, active: active)
        }
        let shared = row("shared", false, true), old = row("unknown", nil, true)
        XCTAssertNil(ConversationSummary.personalDefault([shared, old]))
        let recent = row("recent", true, false), active = row("active", true, true)
        XCTAssertEqual(ConversationSummary.personalDefault([shared, recent, active])?.id, active.id)
    }

    func testUncommittedObservedRowsSurviveAHistoryReadAndDoNotDuplicateTheSavedUser() {
        let previous = ChatMessage(id: "old", role: .assistant, text: "previous")
        let user = ChatMessage(id: "u", role: .user, text: "question")
        let partial = ChatMessage(id: "reply", role: .assistant, text: "prefix", status: .streaming)
        let current = ChatSession.ObservedTurn(id: "turn", anchor: previous, rows: [user, partial])
        XCTAssertEqual(current.merged([previous]).map(\.id), ["old", "u", "reply"])
        XCTAssertEqual(current.merged([previous, user]).map(\.id), ["old", "u", "reply"])
        XCTAssertTrue(current.committedTail([previous, user]).allSatisfy { $0.role != .assistant })
        XCTAssertEqual(current.committedTail([previous, user, partial]).map(\.id), ["u", "reply"])
    }

    func testFirstDirectoryFailureRetriesButExplicitlyNewChatRemainsEmpty() async throws {
        let app = AppModel(), backend = FakeBackend()
        await app.use(backend)
        let bot = try XCTUnwrap(app.bots.first)
        let session = app.session(for: bot)
        backend.directory = [.init(id: "only", title: "Saved", updatedAt: nil, botId: bot.id)]
        backend.listFailures = 1
        await session.showConversation()
        XCTAssertNil(session.conversationId)
        await session.showConversation()
        XCTAssertEqual(session.conversationId, "only")
        session.newChat()
        await session.showConversation()
        XCTAssertNil(session.conversationId)
    }

    func testInterruptedSenderUsesTheDurableAnchorAndCompletesOnItsOwnUserTurn() throws {
        var mapper = ServerFrameMapper()
        guard case .events(let events) = try mapper.map(["type": "turn.started", "turn_id": "run"]),
              case .turnStarted("run")? = events.first else { return XCTFail("Missing sender turn ID") }
        let prior = ChatMessage(id: "prior", role: .assistant, text: "previous")
        let question = ChatMessage(id: "local-user", role: .user, text: "question")
        let partial = ChatMessage(id: "local-reply", role: .assistant, text: "prefix", status: .streaming)
        let turn = ChatSession.ObservedTurn(id: "run", anchor: prior, rows: [question, partial])
        let other = ChatMessage(id: "other", role: .assistant, text: "previous completed turn")
        let savedUser = ChatMessage(id: "saved-user", role: .user, text: "question")
        let savedReply = ChatMessage(id: "saved-reply", role: .assistant, text: "prefix and complete response")
        XCTAssertFalse(turn.hasCommittedReply([prior, other, savedUser]))
        XCTAssertEqual(turn.merged([prior, savedUser]).last?.id, "local-reply")
        XCTAssertTrue(turn.hasCommittedReply([prior, savedUser, savedReply]))
    }

    func testInterruptedDecisionCompletesWithoutAPersistedAnswerBubble() {
        let baseline = ChatMessage(id: "saved", role: .assistant, text: "Question")
        let partial = ChatMessage(id: "live", role: .assistant, text: "The ans", status: .streaming)
        let turn = ChatSession.ObservedTurn(id: "run", anchor: baseline, rows: [partial], ended: true, resumed: true)
        XCTAssertFalse(turn.hasCommittedReply([baseline]))
        var extended = baseline
        extended.text += "\n\nThe answer"
        XCTAssertTrue(turn.hasCommittedReply([extended]))
        XCTAssertTrue(turn.hasCommittedReply([baseline, ChatMessage(id: "new", role: .assistant, text: "The answer")]))
    }

    func testIdleBeforeFirstTokenSettlesEmptyPlaceholderOnlyAfterHistoryRetries() {
        let user = ChatMessage(id: "q", role: .user, text: "question")
        let empty = ChatMessage(id: "reply", role: .assistant, text: "", status: .streaming)
        var turn = ChatSession.ObservedTurn(id: "run", anchor: nil, rows: [user, empty], ended: true)
        XCTAssertFalse(turn.hasCommittedReply([user]))
        turn.lastHistoryRetry = true
        XCTAssertTrue(turn.hasCommittedReply([user]))
        turn.rows[1].thinking = "already received"
        XCTAssertFalse(turn.hasCommittedReply([user]))
    }

    func testHistoryPageOverlapPreservesOrderAndReplacesTheCurrentVersion() {
        let old: [[String: Any]] = [["id": "a"], ["history_seq": 2, "content": "partial"]]
        let new: [[String: Any]] = [["history_seq": 2, "content": "finished"], ["id": "b"]]
        let rows = ChatSession.joinHistory(older: old, newer: new)
        XCTAssertEqual(rows.count, 3)
        XCTAssertEqual(rows[1]["content"] as? String, "finished")
        XCTAssertEqual(rows[2]["id"] as? String, "b")
    }

    func testAccountPhotoBelongsToTheActiveSession() async {
        let app = AppModel()
        let first = FakeBackend()
        first.photo = AccountPhoto.direct(["id": "a", "displayName": "  林一 ", "avatarUrl": "https://photos.example/a"], accountId: "a")
        await app.use(first)
        await app.photoRefresh?.value
        let local = AccountPhoto.localAvatar(["id": 7, "avatar_url": "/api/users/7/avatar?v=123"])
        XCTAssertEqual(local?.path, "/api/users/7/avatar")
        XCTAssertEqual(local?.query, ["v": "123"])
        for wrong in ["/api/users/8/avatar?v=123", "//elsewhere.example/api/users/7/avatar", "/api/users/7/avatar?v=1&u=2"] {
            XCTAssertNil(AccountPhoto.localAvatar(["id": 7, "avatar_url": wrong]))
        }
        XCTAssertEqual(app.accountSummary.name, "林一")
        XCTAssertEqual(app.accountSummary.avatarURL?.host, "photos.example")
        XCTAssertNil(AccountPhoto.direct(["id": "a", "avatarUrl": "https://photos.example/a"], accountId: "b"))

        let next = FakeBackend()
        next.photo = AccountPhoto.cloud(["connected": true, "display_name": "Zoe", "avatar_url": "file:///private/a"])
        await app.use(next)
        await app.photoRefresh?.value
        XCTAssertEqual(app.accountSummary.name, "Zoe")
        XCTAssertNil(app.accountSummary.avatarURL)
        next.photo = AccountPhoto.cloud(["connected": true, "display_name": "Zoe", "avatar_url": "https://photos.example/b"])
        await app.refresh()
        await app.photoRefresh?.value
        XCTAssertEqual(app.accountSummary.avatarURL?.path, "/b")
        next.photo = AccountPhoto.cloud(["connected": false, "avatar_url": "https://photos.example/b"])
        await app.refresh()
        await app.photoRefresh?.value
        XCTAssertNil(app.accountSummary.avatarURL)
        await app.signOut()
        XCTAssertNil(app.accountPhotoURL)
    }

    func testSlowPhotoDoesNotBlockAccountStartupOrLeakIntoNextSession() async {
        let app = AppModel()
        let first = FakeBackend()
        first.delayPhoto = true
        first.photo = AccountPhoto(name: "first", url: "https://photos.example/first")
        await app.use(first)
        XCTAssertEqual(app.phase, .ready)
        XCTAssertFalse(app.bots.isEmpty)
        XCTAssertNil(app.accountPhotoURL)
        let oldRequest = app.photoRefresh
        let second = FakeBackend()
        second.photo = AccountPhoto(name: "next", url: nil)
        await app.use(second)
        await app.photoRefresh?.value
        first.pendingPhoto?.resume()
        await oldRequest?.value
        XCTAssertEqual(app.accountName, "next")
        XCTAssertNil(app.accountPhotoURL)
    }

    func testPreparingAndFailedBotsDoNotSend() async {
        let app = AppModel()
        let backend = FakeBackend()
        await app.use(backend)
        let chat = app.session(for: app.bots[0])
        chat.bot.preparing = true
        chat.send("preparing")
        chat.bot.preparing = false
        chat.bot.state = "failed"
        chat.send("failed")
        XCTAssertTrue(backend.sent.isEmpty)
        XCTAssertTrue(chat.messages.isEmpty)
        XCTAssertTrue(chat.queued.isEmpty)
    }

    func testMessagesWrittenDuringAReplyAreSentInOrderAfterIt() async throws {
        let app = AppModel()
        let backend = FakeBackend()
        await app.use(backend)
        app.notifyOnReply = false
        let chat = app.session(for: app.bots[0])
        chat.send("one")
        XCTAssertTrue(chat.isStreaming)
        chat.send("two")
        chat.send("three")
        XCTAssertEqual(chat.queued.map(\.text), ["two", "three"])
        XCTAssertEqual(backend.sent, ["one"])

        backend.replies[0].yield(.text("hi"))
        backend.replies[0].finish()
        for _ in 0..<50 where backend.sent.count < 2 { try await Task.sleep(for: .milliseconds(20)) }
        XCTAssertEqual(backend.sent, ["one", "two"])
        XCTAssertEqual(chat.queued.map(\.text), ["three"])

        chat.unqueue(chat.queued[0])
        backend.replies[1].finish()
        for _ in 0..<50 where chat.isStreaming { try await Task.sleep(for: .milliseconds(20)) }
        XCTAssertEqual(backend.sent, ["one", "two"])
        XCTAssertEqual(chat.messages.filter { $0.role == .user }.map(\.text), ["one", "two"])
    }
}

@MainActor
final class SoftCharacterTests: XCTestCase {
    func testSoftCharactersMergeLikeTheDashboard() throws {
        let url = try XCTUnwrap(Bundle(for: SoftCharacterTests.self).url(forResource: "soft-characters", withExtension: "json")
            ?? Bundle.main.url(forResource: "soft-characters", withExtension: "json"))
        let soft = Characters.parse(try Data(contentsOf: url))
        XCTAssertEqual(soft.order, ["orb", "heart", "sparkle", "drop", "cloud", "bean"])
        let drop = try XCTUnwrap(soft.shapes["drop"])
        XCTAssertTrue(drop.flat)
        XCTAssertNil(drop.shade)
        XCTAssertEqual(drop.eyes.count, 2)
        XCTAssertFalse(drop.body.boundingRect.isEmpty)
        let merged = Characters.library
        XCTAssertEqual(Array(merged.order.prefix(6)), soft.order)
        XCTAssertNotNil(merged.shapes["acorn"])
        XCTAssertEqual(Array(merged.inkOrder.prefix(6)), ["red", "orange", "green", "blue", "violet", "black"])
        XCTAssertNotEqual(Characters.ink("black", dark: true), Characters.ink("black", dark: false))
    }
}

@MainActor
final class StarsTests: XCTestCase {
    func testStarCountsReadLikeTheWebsite() {
        XCTAssertEqual(GitHubStars.format(6), "6")
        XCTAssertEqual(GitHubStars.format(999), "999")
        XCTAssertEqual(GitHubStars.format(1000), "1k")
        XCTAssertEqual(GitHubStars.format(1234), "1.23k")
        XCTAssertEqual(GitHubStars.format(12_400), "12.4k")
        XCTAssertEqual(GitHubStars.format(12_000), "12k")
    }
}

@MainActor
final class AppUpdaterTests: XCTestCase {
    private let key = Curve25519.Signing.PrivateKey()

    private func signed(_ manifest: [String: Any]) throws -> (Data, String) {
        let body = try JSONSerialization.data(withJSONObject: manifest)
        return (body, try key.signature(for: body).base64EncodedString())
    }

    private var publicKey: String { key.publicKey.rawRepresentation.base64EncodedString() }

    private func manifest(stable: String?, beta: String?, rollout: Int = 100, minimum: String? = nil) -> [String: Any] {
        func entry(_ v: String) -> [String: Any] {
            var ios: [String: Any] = ["url": "https://apps.apple.com/app/id1", "version": v]
            if let minimum { ios["min_version"] = minimum }
            return ["version": "1.0.\(v.split(separator: ".").last ?? "0")", "rollout": rollout, "assets": ["ios": ios]]
        }
        var channels: [String: Any] = [:]
        if let stable { channels["stable"] = entry(stable) }
        if let beta { channels["beta"] = entry(beta) }
        return ["schema": 1, "product": "octop-bot", "channels": channels]
    }

    func testSignatureMustMatchTheExactBytes() throws {
        let (body, signature) = try signed(manifest(stable: "0.2.0", beta: nil))
        XCTAssertNotNil(try AppUpdater.verify(body, signature: signature, publicKey: publicKey))
        XCTAssertThrowsError(try AppUpdater.verify(body + Data(" ".utf8), signature: signature, publicKey: publicKey))
        XCTAssertThrowsError(try AppUpdater.verify(body, signature: signature, publicKey: AppUpdater.publicKey))
        XCTAssertThrowsError(try AppUpdater.verify(body, signature: "nope", publicKey: publicKey))
    }

    func testSelectionFollowsChannelVersionAndRollout() {
        let m = manifest(stable: "0.2.0", beta: "0.3.0")
        XCTAssertEqual(AppUpdater.select(m, installed: "0.1.0", receiveBeta: false, installId: "a")?.version, "0.2.0")
        XCTAssertEqual(AppUpdater.select(m, installed: "0.1.0", receiveBeta: true, installId: "a")?.version, "0.3.0")
        XCTAssertNil(AppUpdater.select(m, installed: "0.2.0", receiveBeta: false, installId: "a"))
        XCTAssertNil(AppUpdater.select(manifest(stable: "0.2.0", beta: nil, rollout: 0), installed: "0.1.0", receiveBeta: false, installId: "a"))
        XCTAssertEqual(AppUpdater.select(manifest(stable: "0.2.0", beta: nil, minimum: "0.1.5"), installed: "0.1.0", receiveBeta: false, installId: "a")?.urgent, true)
        XCTAssertEqual(AppUpdater.compare("0.10.0", "0.9.1"), .orderedDescending)
        XCTAssertEqual(AppUpdater.bucket(installId: "a", version: "1.0.4"), AppUpdater.bucket(installId: "a", version: "1.0.4"))
        let inside = (0..<1000).filter { AppUpdater.bucket(installId: "id-\($0)", version: "1.0.4") < 30 }.count
        XCTAssertTrue((220...380).contains(inside), "about 30 % expected, got \(inside)")
    }
}

/// A Lynxce wallet that sells packs and has App Store purchases switched on, counting what is asked.
private final class SellingAccount: CreditAccount {
    var signupCredits: Double?
    var signupExpiryDay: String?
    var packRequests = 0
    var intents = 0

    func wallet() async throws -> Wallet { Wallet(credits: 50, accountId: "a1") }
    func creditPacks() async throws -> (packs: [LynxceBackend.CreditPack], enabled: Bool) {
        packRequests += 1
        return ([LynxceBackend.CreditPack(id: "p1", name: "Small", credits: 1000, productId: "cn.lynxce.octopbot.credits.1000")], true)
    }
    func purchaseIntent(packId: String) async throws -> (productId: String, accountToken: UUID) {
        intents += 1
        return ("cn.lynxce.octopbot.credits.1000", UUID())
    }
    func submitTransaction(_ signedTransaction: String) async throws {}
    func requestDeletion() async throws -> Int? { nil }
}

@MainActor
final class CloudComputerTests: XCTestCase {
    /// A file on a cloud computer that is off, and no computer slot free: the phone's own words, which
    /// point at the computer icon, rather than whatever the server sent.
    func testComputerOffAndBusyHaveTheirOwnText() {
        XCTAssertEqual(APIError.from(status: 409, message: "server text", code: "BOT_COMPUTER_OFF").errorDescription, L("error.computerOff"))
        XCTAssertEqual(APIError.from(status: 503, message: "server text", code: "BOT_COMPUTER_BUSY").errorDescription, L("error.computerBusy"))
        XCTAssertEqual(APIError.from(status: 409, message: "server text", code: "OTHER").errorDescription, "server text")
        XCTAssertNotEqual(L("computer.starting"), "computer.starting")
    }
}

@MainActor
final class CreditTests: XCTestCase {
    /// 1.0.1 ships before the credit packs have been through App Review: the app must not offer them
    /// even when Lynxce says purchases are on, and must not show "top up" copy with no way to do it.
    func testCreditPacksStayHiddenWhateverLynxceSays() async {
        XCTAssertFalse(CreditPurchases.inApp)
        let account = SellingAccount()
        let store = CreditStore()
        store.start(account: { account }, credited: {})
        await store.load()
        XCTAssertEqual(store.phase, .unavailable)
        XCTAssertTrue(store.offers.isEmpty)
        XCTAssertEqual(account.packRequests, 0)
        XCTAssertEqual(APIError(kind: .credits, status: 402, message: nil).errorDescription, L("error.creditsNoPurchase"))
        XCTAssertFalse(L("credits.titleNoPurchase").isEmpty)
    }

    func testBalanceIsTheWalletNotAMemberAllowance() {
        XCTAssertEqual(LynxceBackend.credits(inQuota: ["creditsRemaining": 1280.5, "effectiveCreditsRemaining": 10]), 1280.5)
        XCTAssertNil(LynxceBackend.credits(inQuota: ["balance": 3]))
        XCTAssertEqual(LynxceBackend.formatCredits(12800), "12,800")
        XCTAssertEqual(LynxceBackend.formatCredits(12.5), "12.50")
        XCTAssertEqual(LynxceBackend.formatCredits(12), "12")
        XCTAssertEqual(LynxceBackend.formatCredits(0.29), "0.29")
        XCTAssertEqual(LynxceBackend.formatCredits(999.99), "999.99")
        XCTAssertEqual(LynxceBackend.formatCredits(4_454_029.04), "4,454,029")
        XCTAssertEqual(LynxceBackend.formatCredits(1000.99), "1,000")
    }

    func testOutOfCreditsIsToldApartFromFailures() {
        XCTAssertEqual(ServerFrameMapper.error(["type": "error", "message": "x", "error_code": "BOT_CLOUD_CREDITS_REQUIRED"]).kind, .credits)
        XCTAssertEqual(ServerFrameMapper.error(["type": "error", "message": "x"]).kind, .server)
        var mapper = ServerFrameMapper()
        XCTAssertThrowsError(try mapper.map(["type": "error", "error_code": "BOT_CLOUD_CREDITS_REQUIRED"])) { error in
            XCTAssertEqual((error as? APIError)?.kind, .credits)
        }
        XCTAssertEqual(APIError.from(status: 402, message: nil).kind, .credits)
        XCTAssertEqual(APIError.from(status: 400, message: nil, code: "BOT_CLOUD_CREDITS_REQUIRED").kind, .credits)
        XCTAssertEqual(HTTP.errorCode(Data(#"{"error":{"code":"BOT_CLOUD_CREDITS_REQUIRED","message":"m"}}"#.utf8)), "BOT_CLOUD_CREDITS_REQUIRED")
        XCTAssertTrue(LynxceBackend.isCreditError(["code": 402, "message": "no credits"]))
        XCTAssertFalse(LynxceBackend.isCreditError(["code": "rate_limited"]))

        let rows: [[String: Any]] = [
            ["role": "user", "content": "go"],
            ["role": "assistant", "content": [], "status": "error", "error_code": "BOT_CLOUD_CREDITS_REQUIRED"],
        ]
        let messages = ServerBackend.history(rows)
        XCTAssertEqual(messages.count, 2)
        XCTAssertEqual(messages[1].status, .outOfCredits)
    }

    func testDailyLimitIsNotOutOfCredits() {
        XCTAssertEqual(ServerFrameMapper.error(["type": "error", "error_code": "BOT_LYNXCE_DAILY_LIMIT"]).kind, .dailyLimit)
        XCTAssertEqual(APIError.from(status: 429, message: nil, code: "BOT_LYNXCE_DAILY_LIMIT").kind, .dailyLimit)
        // Direct Lynxce can send the cap as a 402; it must not become "out of credits".
        let body = Data(#"{"code":402,"message":"limit","data":{"code":"api_key_credit_limit_reached"}}"#.utf8)
        XCTAssertThrowsError(try LynxceBackend.unwrap(body, status: 200)) { XCTAssertEqual(($0 as? APIError)?.kind, .dailyLimit) }
        XCTAssertThrowsError(try LynxceBackend.unwrap(body, status: 402)) { XCTAssertEqual(($0 as? APIError)?.kind, .dailyLimit) }
        XCTAssertThrowsError(try LynxceBackend.parseChunk(#"{"error":{"code":"api_key_credit_limit_reached","message":"m"}}"#)) {
            XCTAssertEqual(($0 as? APIError)?.kind, .dailyLimit)
        }
        XCTAssertEqual(APIError.from(status: 402, message: nil, code: nil).kind, .credits)
        let rows: [[String: Any]] = [
            ["role": "user", "content": "go"],
            ["role": "assistant", "content": [], "status": "error", "error_code": "BOT_LYNXCE_DAILY_LIMIT"],
        ]
        XCTAssertEqual(ServerBackend.history(rows).last?.status, .dailyLimit)
    }

    func testServerMessageLinksAreTappable() {
        let message = "灵策积分不足，到 https://admin.lynxce.cn/recharge 充值后就能继续。"
        let links = LinkedText.links(in: message)
        XCTAssertEqual(links.map(\.url.absoluteString), ["https://admin.lynxce.cn/recharge"])
        XCTAssertEqual(String(LinkedText.attributed(message).characters), message)
        XCTAssertFalse(LinkedText.hasLink("灵策积分不足"))
    }

    func testUsageSummaryParses() {
        let usage = ServerBackend.UsageSummary.parse([
            "total_tokens": 1500, "model_calls": 3,
            "buckets": [["key": "a1", "label": "Chief", "total_tokens": 1200], ["key": "a2", "label": "", "total_tokens": 300], ["key": "z", "total_tokens": 0]],
        ])
        XCTAssertEqual(usage.totalTokens, 1500)
        XCTAssertEqual(usage.modelCalls, 3)
        XCTAssertEqual(usage.buckets.map(\.label), ["Chief", "a2"])
        XCTAssertEqual(LynxceBackend.formatCount(1_234_567), "1,234,567")
    }

    func testNamesNeverShowInternalIds() {
        XCTAssertEqual(ServerBackend.displayName(["username": "sso_abc"]), "")
        XCTAssertEqual(ServerBackend.displayName(["username": "owner", "display_name": "138****5678"]), "138****5678")
        let server = ServerBackend(session: .init(baseURL: URL(string: "https://bot.lynxce.cn")!, token: "t", displayName: "", cloud: true))
        XCTAssertEqual(server.accountName, L("account.genericName"))
        let lynxce = LynxceBackend(grant: .init(accountId: "acc_123", displayName: nil, accessToken: "a", refreshToken: "r"))
        XCTAssertEqual(lynxce.accountName, L("account.genericName"))
    }

    func testOnlyPacksWithAnAppStoreProductAreListed() {
        let data: [String: Any] = [
            "packages": [
                ["id": "p1", "name": "Small", "credits": 1000, "appleProductId": "cn.lynxce.octopbot.credits.1000"],
                ["id": "p2", "name": "Web only", "credits": 5000],
            ],
            "payment": ["apple": ["enabled": true]],
        ]
        let (packs, enabled) = LynxceBackend.creditPacks(from: data)
        XCTAssertTrue(enabled)
        XCTAssertEqual(packs, [LynxceBackend.CreditPack(id: "p1", name: "Small", credits: 1000, productId: "cn.lynxce.octopbot.credits.1000")])
        XCTAssertFalse(LynxceBackend.creditPacks(from: ["packages": []]).enabled)
    }

    func testOnlyThisAppsProductsAreDelivered() {
        XCTAssertTrue(CreditStore.isCreditPack("cn.lynxce.octopbot.credits.1000"))
        XCTAssertFalse(CreditStore.isCreditPack("cn.lynxce.omni.credits.1000"))
        XCTAssertFalse(CreditStore.isCreditPack("cn.lynxce.octopbot"))
    }

    func testOnlyFinalRefusalsFinishATransaction() throws {
        let body = #"{"error":{"code":"apple_sandbox_rejected","message":"no sandbox"}}"#
        var refused: APIError?
        XCTAssertThrowsError(try LynxceBackend.unwrap(Data(body.utf8), status: 403)) { refused = $0 as? APIError }
        XCTAssertEqual(refused?.code, "apple_sandbox_rejected")
        XCTAssertTrue(CreditStore.isFinalRefusal(try XCTUnwrap(refused)))
        // Bought while another Lynxce account was signed in: stays queued for that account.
        let otherAccount = APIError(kind: .rejected, status: 403, message: nil, code: "apple_account_token_mismatch")
        XCTAssertFalse(CreditStore.isFinalRefusal(otherAccount))
        let noToken = APIError(kind: .rejected, status: 409, message: nil, code: "apple_account_token_missing")
        XCTAssertTrue(CreditStore.isFinalRefusal(noToken))
        // Not configured yet, or offline: tried again later.
        XCTAssertFalse(CreditStore.isFinalRefusal(APIError(kind: .rejected, status: 409, message: nil, code: "apple_product_unknown")))
        XCTAssertFalse(CreditStore.isFinalRefusal(.network))
    }
}

@MainActor
final class CloudTests: XCTestCase {
    func testCloudIsRecognisedFromServerInfo() {
        XCTAssertTrue(ServerBackend.isCloudInfo(["product": "octop-bot", "edition": "cloud"]))
        XCTAssertFalse(ServerBackend.isCloudInfo(["product": "octop-bot", "edition": "web"]))
        XCTAssertFalse(ServerBackend.isCloudInfo(["edition": "cloud"]))
    }

    func testOnlyWorkspaceDownloadsAreOpenedWithTheSession() {
        XCTAssertTrue(ServerBackend.isWorkspaceDownload(URL(string: "/api/agents/AbC123/workspace/download?path=outbound/a.pdf")!))
        XCTAssertFalse(ServerBackend.isWorkspaceDownload(URL(string: "https://example.com/api/agents/A/workspace/download?path=x")!))
        XCTAssertFalse(ServerBackend.isWorkspaceDownload(URL(string: "/api/agents/A/workspace/tree")!))
    }

    func testIntentsParseFromEitherRoute() throws {
        let token = UUID()
        let intent = try LynxceBackend.intent(from: ["productId": "cn.lynxce.octopbot.credits.1000", "appAccountToken": token.uuidString])
        XCTAssertEqual(intent.productId, "cn.lynxce.octopbot.credits.1000")
        XCTAssertEqual(intent.accountToken, token)
        XCTAssertThrowsError(try LynxceBackend.intent(from: ["productId": "x"]))
    }
}

@MainActor
final class ComputerTests: XCTestCase {
    func testComputerStatusParses() throws {
        let running = try ServerBackend.ComputerStatus.parse(["state": "running", "spec": "standard", "running_since": 1_700_000_000.0])
        XCTAssertEqual(running.state, .running)
        XCTAssertEqual(running.runningSince, Date(timeIntervalSince1970: 1_700_000_000))
        XCTAssertEqual(try ServerBackend.ComputerStatus.parse(["state": "none", "spec": "standard"]).state, .none)
        XCTAssertThrowsError(try ServerBackend.ComputerStatus.parse(["state": "melted"]))
    }
}

@MainActor
final class ScreenTests: XCTestCase {
    func testScreenPageCarriesTheTicketAndControl() {
        let url = ServerBackend.screenPage(
            base: URL(string: "https://bot.lynxce.cn")!, agentId: "AbC123", ticket: "t-1", screenSession: "s-1", control: true)
        XCTAssertEqual(url.absoluteString, "https://bot.lynxce.cn/octop-bot/screen/AbC123?ticket=t-1&session=s-1&control=1")
        let older = ServerBackend.screenPage(
            base: URL(string: "https://bot.lynxce.cn")!, agentId: "AbC123", ticket: "t-1", screenSession: nil, control: false)
        XCTAssertEqual(older.absoluteString, "https://bot.lynxce.cn/octop-bot/screen/AbC123?ticket=t-1&control=0")
        let status = try? ServerBackend.ComputerStatus.parse(["state": "running", "takeover": true])
        XCTAssertEqual(status?.takeover, true)
    }
}

@MainActor
final class FileAttachmentTests: XCTestCase {
    func testKindByExtensionThenMime() {
        XCTAssertEqual(FileKind.of(name: "Report.PDF", mime: nil), .pdf)
        XCTAssertEqual(FileKind.of(name: "a.docx", mime: nil), .word)
        XCTAssertEqual(FileKind.of(name: "dec2026.csv", mime: nil), .spreadsheet)
        XCTAssertEqual(FileKind.of(name: "deck.pptx", mime: nil), .presentation)
        XCTAssertEqual(FileKind.of(name: "logs.tar.gz", mime: nil), .archive)
        XCTAssertEqual(FileKind.of(name: "shot.png", mime: nil), .image)
        XCTAssertEqual(FileKind.of(name: "notes.txt", mime: nil), .other)
        XCTAssertEqual(FileKind.of(name: "download", mime: "application/pdf"), .pdf)
        XCTAssertEqual(FileKind.of(name: "x", mime: "image/*"), .image)
        XCTAssertEqual(FileKind.pdf.bandHex, 0xE5484D)
        XCTAssertEqual(FileKind.other.bandHex, FileKind.image.bandHex)
        XCTAssertEqual(Set(FileKind.allCases.map(\.bandHex)).count, 6)
    }

    func testTypeLabel() {
        XCTAssertEqual(FileCardText.typeLabel("a.pdf"), "PDF")
        XCTAssertEqual(FileCardText.typeLabel("a.docx"), "DOCX")
        XCTAssertEqual(FileCardText.typeLabel("README"), L("file.generic"))
        XCTAssertEqual(FileCardText.typeLabel(".env"), L("file.generic"))
        XCTAssertEqual(FileCardText.typeLabel("a.numbers"), L("file.generic"))
    }

    func testMiddleEllipsisKeepsTheExtension() {
        XCTAssertEqual(FileCardText.middleEllipsis("dec2026.csv"), "dec2026.csv")
        let long = FileCardText.middleEllipsis("Octop-quarterly-business-review-2026-final.pdf")
        XCTAssertEqual(long, "Octop-quarterly-b…inal.pdf")
        XCTAssertEqual(long.count, 26)
        XCTAssertTrue(FileCardText.middleEllipsis("这是一个非常非常非常非常非常非常非常长的中文文件名称报告.docx").hasSuffix(".docx"))
        XCTAssertEqual(FileCardText.middleEllipsis(String(repeating: "x", count: 40)).count, 26)
    }

    func testFileSize() {
        XCTAssertEqual(FileCardText.formatFileSize(512), "512 B")
        XCTAssertEqual(FileCardText.formatFileSize(1536), "1.5 KB")
        XCTAssertEqual(FileCardText.formatFileSize(2 * 1024 * 1024), "2 MB")
        XCTAssertEqual(FileCardText.formatFileSize(12 * 1024 * 1024 + 300_000), "12 MB")
        XCTAssertEqual(FileCardText.formatFileSize(3 * 1024 * 1024 * 1024), "3 GB")
    }

    func testLinksInReplyText() {
        let text = "Here: [report](/api/agents/A1/workspace/download?path=output%2Freport%201.pdf) and "
            + "[again](/api/agents/A1/workspace/download?path=output%2Freport%201.pdf), [site](https://x.dev)."
        let files = FileAttachment.links(in: text)
        XCTAssertEqual(files.count, 1)
        XCTAssertEqual(files.first?.name, "report 1.pdf")
        XCTAssertEqual(files.first?.url, "/api/agents/A1/workspace/download?path=output%2Freport%201.pdf")
        var message = ChatMessage(role: .assistant, text: text)
        message.attachments = [FileAttachment(url: "/api/agents/A1/workspace/download?path=a.csv", name: "a.csv")]
        XCTAssertEqual(message.fileCards.map(\.name), ["a.csv", "report 1.pdf"])
        XCTAssertTrue(ChatMessage(role: .user, text: text).fileCards.isEmpty)
    }

    func testAttachmentFrame() throws {
        var mapper = ServerFrameMapper()
        let outcome = try mapper.map([
            "type": "attachment", "kind": "file", "path": "/tmp/out/dec2026.csv",
            "url": "/api/agents/A1/workspace/download?path=%2Ftmp%2Fout%2Fdec2026.csv", "mime_type": "text/csv",
        ])
        guard case .events(let events) = outcome, case .attachment(let file) = events.first else { return XCTFail() }
        XCTAssertEqual(file.name, "dec2026.csv")
        XCTAssertEqual(file.kind, .spreadsheet)
        XCTAssertTrue(file.isWorkspaceDownload)
        let image = FileAttachment.fromFrame(["kind": "image", "url": "/api/agents/A1/media/preview?source=x.png"])
        XCTAssertEqual(image?.isImage, true)
        XCTAssertNil(FileAttachment.fromFrame(["kind": "file", "url": "https://evil.example/x"]))
    }

    func testHistoryAttachesDeliveredFiles() {
        let output = #"{"type":"file","path":"out/a&b.pdf","filename":"a&b.pdf","media_type":"application/pdf"}"#
        let rows: [[String: Any]] = [
            ["role": "user", "content": "make a pdf"],
            ["role": "assistant", "content": [["type": "tool_use", "id": "t1", "name": "send_file_to_user"]]],
            ["role": "tool", "content": [["type": "tool_result", "id": "t1", "name": "send_file_to_user", "output": output]]],
            ["role": "tool", "content": [["type": "tool_result", "id": "t2", "name": "write_file", "output": output]]],
            ["role": "assistant", "content": [["type": "text", "text": "Done."]]],
        ]
        let messages = ServerBackend.history(rows, agent: "A1")
        XCTAssertEqual(messages.count, 2)
        XCTAssertEqual(messages[1].text, "Done.")
        XCTAssertEqual(messages[1].attachments.map(\.name), ["a&b.pdf"])
        XCTAssertEqual(messages[1].attachments.first?.url, "/api/agents/A1/workspace/download?path=out/a%26b.pdf")
        let link = URL(string: messages[1].attachments[0].url)!
        XCTAssertEqual(FileAttachment.fromLink(link)?.name, "a&b.pdf")

        let orphan = ServerBackend.history([
            ["role": "tool", "content": [["type": "tool_result", "name": "mcp/send_file", "output": #"[{"type":"image","preview_url":"/api/agents/A1/media/preview?source=s.png","filename":"s.png"}]"#]]],
        ], agent: "A1")
        XCTAssertEqual(orphan.count, 1)
        XCTAssertEqual(orphan[0].role, .assistant)
        XCTAssertTrue(orphan[0].attachments[0].isImage)
    }

    func testHistoryAttachesGeneratedImagesAndVideos() {
        let image = #"{"type":"image_gen_tool_result","images":[{"path":"generated/images/cat.png","mediaType":"image/png"}]}"#
        let video = #"{"type":"video_gen_tool_result","videos":[{"path":"generated/videos/sea.mp4","mediaType":"video/mp4"}]}"#
        let messages = ServerBackend.history([
            ["role": "user", "content": "画一只猫，再做一段海浪的视频"],
            ["role": "tool", "content": [["type": "tool_result", "name": "generate_image", "output": image]]],
            ["role": "tool", "content": [["type": "tool_result", "name": "generate_video", "output": video]]],
            ["role": "assistant", "content": [["type": "text", "text": "好了。"]]],
        ], agent: "A1")
        XCTAssertEqual(messages[1].attachments.map(\.name), ["cat.png", "sea.mp4"])
        XCTAssertEqual(messages[1].attachments.map(\.url), [
            "/api/agents/A1/workspace/download?path=generated/images/cat.png",
            "/api/agents/A1/workspace/download?path=generated/videos/sea.mp4",
        ])
        XCTAssertTrue(messages[1].attachments[0].isImage)
        XCTAssertEqual(messages[1].attachments[1].mime, "video/mp4")
    }
}

@MainActor
final class DeviceConnectorTests: XCTestCase {
    func testToolCallDeltasJoinByIndex() {
        var calls = ToolCallAccumulator()
        calls.add(#"{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","type":"function","function":{"name":"device_calendar_create_event","arguments":"{\"title\":"}}]}}]}"#)
        calls.add(#"{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\"开会\",\"start\":\"2026-11-25T14:00\"}"}}]}}]}"#)
        calls.add(#"{"choices":[{"delta":{"tool_calls":[{"index":1,"id":"c2","function":{"name":"device_reminders","arguments":"{}"}}]}}]}"#)
        calls.add(#"{"choices":[{"delta":{"content":"hi"}}]}"#)
        XCTAssertEqual(calls.calls.map(\.id), ["c1", "c2"])
        XCTAssertEqual(calls.calls[0].name, "device_calendar_create_event")
        XCTAssertEqual(DeviceArgs.object(calls.calls[0].arguments)["title"] as? String, "开会")
        let message = ToolCallAccumulator.assistantMessage(text: "", calls: calls.calls)
        XCTAssertTrue(message["content"] is NSNull)
        XCTAssertEqual((message["tool_calls"] as? [[String: Any]])?.count, 2)
    }

    func testDatesWithoutOffsetAreLocalAndBareDatesAreDays() throws {
        let shanghai = try XCTUnwrap(TimeZone(identifier: "Asia/Shanghai"))
        let local = try XCTUnwrap(DeviceDates.parse("2026-11-25T14:00", zone: shanghai))
        XCTAssertFalse(local.dateOnly)
        XCTAssertEqual(DeviceDates.stamp(local.date, zone: shanghai), "2026-11-25T14:00:00+08:00")
        let zoned = try XCTUnwrap(DeviceDates.parse("2026-11-25T06:00:00Z", zone: shanghai))
        XCTAssertEqual(zoned.date, local.date)
        let day = try XCTUnwrap(DeviceDates.parse("2026-11-25", zone: shanghai))
        XCTAssertTrue(day.dateOnly)
        XCTAssertNil(DeviceDates.parse("tomorrow"))
    }

    func testDevicePausesSplitReadsFromWrites() throws {
        let reads = try XCTUnwrap(HitlPause.parse([
            "action_requests": [["name": "device_health_summary", "args": #"{"metrics":["steps"]}"#, "description": "Runs on the user's phone."]],
        ]))
        XCTAssertTrue(reads.runsUnattended)
        XCTAssertNil(reads.actions[0].description)
        let write = try XCTUnwrap(HitlPause.parse([
            "action_requests": [
                ["name": "device_calendar_events", "args": ["start": "2026-11-25", "end": "2026-11-26"]],
                ["name": "device_calendar_create_event", "args": ["title": "评审会", "start": "2026-11-25T14:00", "end": "2026-11-25T15:00", "location": "3F"]],
            ],
        ]))
        XCTAssertFalse(write.runsUnattended)
        XCTAssertTrue(write.hasDeviceActions)
        let values = write.actions[1].details.map(\.value)
        XCTAssertTrue(values.contains("评审会"))
        XCTAssertTrue(values.contains("3F"))
        XCTAssertEqual(DeviceArgs.object(write.actions[1].args)["title"] as? String, "评审会")
    }

    func testDecisionsBecomeToolMessagesInOrder() {
        let messages: [[String: Any]] = [
            ["role": "user", "content": "x"],
            ToolCallAccumulator.assistantMessage(text: "", calls: [
                .init(id: "a", name: "device_reminders", arguments: "{}"),
                .init(id: "b", name: "device_reminder_create", arguments: #"{"title":"交报告"}"#),
            ]),
        ]
        let out = LynxceBackend.answering(messages, decisions: [
            ["type": "respond", "message": #"{"reminders":[]}"#],
            ["type": "reject", "message": "The user declined."],
        ])
        XCTAssertEqual(out.count, 4)
        XCTAssertEqual(out[2]["tool_call_id"] as? String, "a")
        XCTAssertEqual(out[2]["content"] as? String, #"{"reminders":[]}"#)
        XCTAssertEqual(out[3]["content"] as? String, #"{"error":"The user declined."}"#)
    }

    func testChatBodyOffersToolsWithTheTime() throws {
        let bot = BotProfile(id: "b", name: "Chief", look: .chief, isChief: true)
        let tools = DeviceConnectors.loadSpecs().filter { $0.capability == .calendar }.map(\.openAITool)
        XCTAssertEqual(tools.count, 3)
        let zone = try XCTUnwrap(TimeZone(identifier: "Asia/Shanghai"))
        let body = LynxceBackend.chatBody(
            text: "明天下午三点开会", images: [], bot: bot, history: [], sessionId: "s", model: nil,
            tools: tools, now: Date(timeIntervalSince1970: 1_795_000_000), zone: zone
        )
        XCTAssertEqual(body["tool_choice"] as? String, "auto")
        XCTAssertEqual((body["tools"] as? [[String: Any]])?.count, 3)
        let system = (body["messages"] as? [[String: Any]])?.first { ($0["content"] as? String)?.hasPrefix("Now:") == true }
        XCTAssertEqual(system?["content"] as? String, "Now: 2026-11-18T19:06:40+08:00 (Asia/Shanghai).")
        let plain = LynxceBackend.chatBody(text: "hi", images: [], bot: bot, history: [], sessionId: "s", model: nil)
        XCTAssertNil(plain["tools"])
    }

    #if HEALTH_CONNECTOR
    func testSleepIntervalsCountOverlapsOnce() {
        let t0 = Date(timeIntervalSince1970: 0)
        let hours = HealthMetric.union([
            DateInterval(start: t0, duration: 3 * 3600),
            DateInterval(start: t0.addingTimeInterval(2 * 3600), duration: 2 * 3600),
            DateInterval(start: t0.addingTimeInterval(6 * 3600), duration: 3600),
        ]) / 3600
        XCTAssertEqual(hours, 5)
    }
    #endif

    /// 1.0.1 ships without HealthKit (no entitlement on the App Store profile): no Health switch, no
    /// health tool offered to the Bot, and no Health purpose string in Info.plist.
    func testHealthIsLeftOutOfThisBuild() {
        XCTAssertFalse(DeviceConnectors.healthAvailable)
        XCTAssertEqual(DeviceConnectors.shared.isAvailable[.health], false)
        XCTAssertFalse(DeviceConnectors.shared.isOn(.health))
        XCTAssertFalse(DeviceConnectors.shared.offeredTools.contains("device_health_summary"))
        XCTAssertNil(Bundle.main.object(forInfoDictionaryKey: "NSHealthShareUsageDescription"))
    }
}

@MainActor
final class BotActivityTests: XCTestCase {
    func testUpcomingKeepsServerOrderAndSchedules() {
        let jobs = ServerBackend.UpcomingJob.parse([
            "timezone": "Asia/Shanghai",
            "jobs": [
                ["id": "a", "name": "Morning brief", "enabled": true, "schedule": "工作日 8:50", "can_toggle": true],
                ["id": "b", "name": "Script", "enabled": false, "schedule": "自定义", "can_toggle": false],
                ["name": "no id"],
            ],
        ])
        XCTAssertEqual(jobs.map(\.id), ["a", "b"])
        XCTAssertEqual(jobs[0].schedule, "工作日 8:50")
        XCTAssertTrue(jobs[0].enabled && jobs[0].canToggle)
        XCTAssertFalse(jobs[1].canToggle)
        XCTAssertFalse(jobs[0].with(enabled: false).enabled)
    }

    func testLibraryGroupsByRecencyInServerOrder() {
        func row(_ name: String, _ period: String) -> [String: Any] {
            ["name": name, "path": "outbound/" + name, "period": period, "mime": NSNull(),
             "url": "/api/agents/A/workspace/download?path=outbound%2F" + name]
        }
        let files = ServerBackend.LibraryFile.parse(["files": [
            row("new.pdf", "today"), row("old.xlsx", "older"), row("mid.md", "week"), row("b.png", "today"),
        ]])
        let groups = ServerBackend.LibraryFile.grouped(files)
        XCTAssertEqual(groups.map(\.0), [.today, .week, .older])
        XCTAssertEqual(groups[0].1.map(\.name), ["new.pdf", "b.png"])
        XCTAssertTrue(ServerBackend.isWorkspaceDownload(URL(string: files[0].url)!))
        XCTAssertEqual(ServerBackend.LibraryFile.grouped([]).count, 0)
    }

    func testLibraryIcons() {
        func file(_ name: String, _ mime: String? = nil) -> ServerBackend.LibraryFile {
            .init(name: name, path: name, mime: mime, period: .today, url: "")
        }
        XCTAssertEqual(file("a.png", "image/png").symbol, "photo")
        XCTAssertEqual(file("deck.KEY").symbol, "rectangle.on.rectangle")
        XCTAssertEqual(file("sheet.csv").symbol, "tablecells")
        XCTAssertEqual(file("blob.bin").symbol, "doc")
    }
}

@MainActor
final class ModelSourceTests: XCTestCase {
    func testBundledCatalogGroupsCompaniesFeaturedFirst() {
        let vendors = VendorCatalog.bundled.vendors
        XCTAssertFalse(vendors.isEmpty)
        // Phones call vendors themselves over the OpenAI-compatible protocol only.
        XCTAssertFalse(vendors.contains { $0.id == "anthropic" })
        let companies = VendorCompany.group(vendors)
        XCTAssertEqual(Array(companies.prefix(8).map(\.id)), VendorCompany.featured)
        // The preferred plan comes first: Tencent Cloud TokenHub, Bailian's main endpoint.
        XCTAssertEqual(companies.first { $0.id == "tencent" }?.plans.first?.id, "tencent-tokenhub")
        XCTAssertEqual(companies.first { $0.id == "aliyun" }?.plans.first?.id, "dashscope")
        XCTAssertTrue(vendors.allSatisfy { $0.baseURL.hasPrefix("https://") })
    }

    func testGroupKeepsCatalogOrderAfterFeatured() {
        let vendors = [
            KeyVendor(id: "x-1", name: "X", vendor: "xco", baseURL: "https://x"),
            KeyVendor(id: "kimi-intl", name: "Kimi intl", vendor: "kimi", baseURL: "https://k2"),
            KeyVendor(id: "kimi-cn", name: "Kimi", vendor: "kimi", baseURL: "https://k1"),
            KeyVendor(id: "y-1", name: "Y", vendor: "yco", baseURL: "https://y"),
        ]
        let companies = VendorCompany.group(vendors)
        XCTAssertEqual(companies.map(\.id), ["kimi", "xco", "yco"])
        XCTAssertEqual(companies[0].plans.map(\.id), ["kimi-cn", "kimi-intl"])
    }

    func testCompanyNamesAreLocalized() {
        Preferences.shared.language = .chinese
        defer { Preferences.shared.language = .system }
        XCTAssertEqual(VendorCompany(id: "volcengine", plans: []).name, "火山方舟")
        XCTAssertEqual(VendorCompany.name(of: "unknown-co", fallback: "Unknown"), "Unknown")
    }

    func testOwnKeyListParsesTheServerShape() throws {
        let list = OwnKeyList.parse([
            "keys": [[
                "id": "k1", "vendor": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
                "key_hint": "****7f3a", "models": [["id": "deepseek-flash", "name": "DeepSeek Flash"]], "created_at": 1.0,
            ]],
            "in_use": "k1", "selected_model": "deepseek-flash",
        ])
        XCTAssertEqual(list.keys.count, 1)
        XCTAssertEqual(list.keys[0].keyHint, "****7f3a")
        XCTAssertEqual(list.keys[0].models.first?.label, "DeepSeek Flash")
        XCTAssertEqual(list.keys[0].company, "deepseek")
        XCTAssertEqual(list.inUse, "k1")
        XCTAssertEqual(list.selectedModel, "deepseek-flash")
        XCTAssertEqual(OwnKeyList.parse(["keys": [], "in_use": NSNull()]), .empty)
    }

    func testServerCatalogKeepsCustomFlagAndAddsDocs() throws {
        let data = Data(#"{"vendors":[{"id":"deepseek","name":"DeepSeek","vendor":"deepseek","logo_id":"deepseek","base_url":"https://api.deepseek.com/v1","protocol":"openai","api_key_prefix":"sk-","models":[]}],"custom_allowed":false}"#.utf8)
        let catalog = try ServerModelKeys.catalog(data)
        XCTAssertFalse(catalog.customAllowed)
        XCTAssertEqual(catalog.vendors.first?.apiKeyPrefix, "sk-")
        XCTAssertEqual(catalog.vendors.first?.docs, "https://platform.deepseek.com/api_keys")
    }

    func testLocalAddressesAndCustomBases() {
        XCTAssertEqual(PhoneModels.localBase("192.168.1.8")?.absoluteString, "http://192.168.1.8:11434/v1")
        XCTAssertEqual(PhoneModels.localBase(" 192.168.1.8:1234/ ")?.absoluteString, "http://192.168.1.8:1234/v1")
        XCTAssertEqual(PhoneModels.localBase("http://mac.local:11434/v1")?.absoluteString, "http://mac.local:11434/v1")
        XCTAssertNil(PhoneModels.localBase("  "))
        XCTAssertEqual(PhoneModels.normalizedBase("https://api.example.com/v1/chat/completions"), "https://api.example.com/v1")
        XCTAssertEqual(PhoneModels.normalizedBase("https://api.example.com/v1/"), "https://api.example.com/v1")
        XCTAssertNil(PhoneModels.normalizedBase("ftp://x"))
        XCTAssertNil(PhoneModels.normalizedBase("not a url"))
    }

    func testModelListsFromVendorsAndOllama() {
        let openAI = PhoneModels.parseModels(Data(#"{"object":"list","data":[{"id":"a"},{"id":"b"},{"id":"a"}]}"#.utf8))
        XCTAssertEqual(openAI.map(\.id), ["a", "b"])
        let other = PhoneModels.parseModels(Data(#"{"models":[{"name":"qwen3:14b"}]}"#.utf8))
        XCTAssertEqual(other.map(\.id), ["qwen3:14b"])
        XCTAssertTrue(PhoneModels.parseModels(Data("nope".utf8)).isEmpty)
    }

    func testPhoneSelectionPicksTheEndpointAndForgetsRemovedKeys() async throws {
        let defaults = UserDefaults(suiteName: "phone-models-test")!
        defaults.removePersistentDomain(forName: "phone-models-test")
        var secrets: [String: String] = [:]
        let phone = PhoneModels(defaults: defaults, secrets: { secrets[$0] }, saveSecret: { value, id in secrets[id] = value })
        XCTAssertNil(phone.endpoint())
        XCTAssertFalse(phone.hasModel)
        phone.useLocal("missing", model: "m")
        XCTAssertNil(phone.endpoint(), "an unknown local server is no endpoint")
        phone.useLynxce()
        XCTAssertNil(phone.selection)
        // Keys are only added after the vendor accepts them, which needs the network; removing is local.
        try await phone.remove("nothing")
        XCTAssertTrue(phone.keys.isEmpty)
        XCTAssertTrue(secrets.isEmpty)
    }

    func testVendorBodyDropsLynxceFields() {
        let bot = BotProfile(id: "chief", name: "Chief", look: .chief, isChief: true, systemPrompt: "Be brief.")
        let body = LynxceBackend.chatBody(text: "hi", images: [], bot: bot, history: [], sessionId: "s", model: nil)
        let vendor = CompletionChat.vendorBody(body, model: "deepseek-flash")
        XCTAssertEqual(vendor["model"] as? String, "deepseek-flash")
        XCTAssertNil(vendor["sessionId"])
        XCTAssertNil(vendor["metadata"])
        XCTAssertNil(vendor["stream_options"])
        XCTAssertEqual(vendor["stream"] as? Bool, true)
        XCTAssertEqual((vendor["messages"] as? [[String: Any]])?.count, 2)
    }

    func testVendorErrorsNeverSignOutOrAskForCredits() {
        let refused = CompletionChat.vendorError(status: 401, data: Data())
        XCTAssertEqual(refused.kind, .rejected)
        XCTAssertEqual(refused.status, 401)
        let quota = CompletionChat.vendorError(status: 402, data: Data(#"{"error":{"message":"Insufficient Balance"}}"#.utf8))
        XCTAssertEqual(quota.kind, .rejected)
        XCTAssertTrue(quota.localizedDescription.contains("Insufficient Balance"))
        XCTAssertEqual(CompletionChat.vendorError(status: 500, data: Data()).kind, .server)
        XCTAssertEqual(CompletionChat.finishReason(#"{"choices":[{"delta":{},"finish_reason":"stop"}]}"#), "stop")
        XCTAssertNil(CompletionChat.finishReason(#"{"choices":[{"delta":{"content":"x"}}]}"#))
    }

    func testDeviceConversationsKeepTurnsPerBot() {
        let file = FileManager.default.temporaryDirectory.appending(path: "device-conv-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: file) }
        let store = DeviceConversations(file: file)
        store.create("c1", bot: "chief", title: "  第一行\n第二行")
        store.append(to: "c1", user: "第一行\n第二行", startedAt: .now, answer: "好的", thinking: "想一下")
        store.create("c2", bot: "writer", title: "draft")
        XCTAssertEqual(store.conversations(for: "chief").map(\.title), ["第一行"])
        let reloaded = DeviceConversations(file: file)
        let messages = reloaded.messages(in: "c1")
        XCTAssertEqual(messages.map(\.role), [.user, .assistant])
        XCTAssertEqual(messages.last?.thinking, "想一下")
        reloaded.delete("c1")
        XCTAssertTrue(reloaded.conversations(for: "chief").isEmpty)
        XCTAssertEqual(reloaded.conversations(for: "writer").count, 1)
    }
}

@MainActor
final class LynxceSignupSourceTests: XCTestCase {
    func testEveryLynxceCallNamesOctopBotAsTheSignupSite() {
        let signIn = LynxceBackend.headers(nil)
        XCTAssertEqual(signIn["X-Lynxce-Signup-Site"], "octop-bot")
        XCTAssertEqual(signIn["X-Lynxce-App"], "octopbot")
        XCTAssertEqual(signIn["X-Lynxce-Client"], "web")
        XCTAssertNil(signIn["Authorization"])
        let signedIn = LynxceBackend.headers("t", iap: true)
        XCTAssertEqual(signedIn["X-Lynxce-Signup-Site"], "octop-bot")
        XCTAssertEqual(signedIn["Authorization"], "Bearer t")
        XCTAssertEqual(signedIn["X-Lynxce-Iap-App"], "cn.lynxce.octopbot")
    }
}

@MainActor
final class SignupCreditNoticeTests: XCTestCase {
    func testOnlyGrantedCreditsOnNewAccountsAreShown() {
        let grant = ["credits": 125.5]
        XCTAssertEqual(newSignupCredits(["isNewUser": true, "signupGrant": grant]), 125.5)
        XCTAssertNil(newSignupCredits(["isNewUser": false, "signupGrant": grant]))
        XCTAssertNil(newSignupCredits(["isNewUser": 1, "signupGrant": grant]))
        XCTAssertNil(newSignupCredits(["isNewUser": true]))
        XCTAssertEqual(signupExpiryDayUTC(["isNewUser": true, "signupGrant": ["credits": 100, "expiresAt": "2026-12-09T01:00:00+08:00"]]), "2026-12-08")
        XCTAssertNil(signupExpiryDayUTC(["isNewUser": true, "signupGrant": grant]))
        for invalid: Any in [true, "100", -1, 0, Double.infinity] as [Any] {
            XCTAssertNil(newSignupCredits(["isNewUser": true, "signupGrant": ["credits": invalid]]))
        }
    }
}
