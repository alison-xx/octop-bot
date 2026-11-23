import CryptoKit
import SwiftUI
import XCTest
@testable import OctopBot

@MainActor
final class CharacterTests: XCTestCase {
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
    var sent: [String] = []
    var replies: [AsyncThrowingStream<StreamEvent, Error>.Continuation] = []

    func bots() async throws -> [BotProfile] { [BotProfile(id: "b", name: "B", look: .fallback, isChief: true)] }
    func conversations(for bot: BotProfile) async throws -> [ConversationSummary] { [] }
    func messages(in conversation: ConversationSummary, bot: BotProfile) async throws -> [ChatMessage] { [] }
    func models() async throws -> [ModelOption] { [] }
    func send(_ text: String, images: [Data], to bot: BotProfile, conversation: String?, history: [ChatMessage], model: String?) -> AsyncThrowingStream<StreamEvent, Error> {
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

@MainActor
final class CreditTests: XCTestCase {
    func testBalanceIsTheWalletNotAMemberAllowance() {
        XCTAssertEqual(LynxceBackend.credits(inQuota: ["creditsRemaining": 1280.5, "effectiveCreditsRemaining": 10]), 1280.5)
        XCTAssertNil(LynxceBackend.credits(inQuota: ["balance": 3]))
        XCTAssertEqual(LynxceBackend.formatCredits(12800), "12,800")
        XCTAssertEqual(LynxceBackend.formatCredits(12.5), "12.5")
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
