# Octop Bot for iOS and Android

Native phone clients for Octop Bot: SwiftUI (`ios/`) and Jetpack Compose (`android/`).
They share no code, only this design and the wire contract in [PROTOCOL.md](PROTOCOL.md).

## Two ways to connect

1. **Lynxce account (default).** Sign in with a 灵策智算 phone/email and password and start chatting —
   no server needed. Replies stream from the Lynxce model gateway; conversations sync to the account
   and show up in the desktop Bot's cloud conversations too. Bots are defined on the phone (Chief plus
   built-in roles, and your own with a persona, shape and color).
2. **Your own server.** In Settings → Connection, enter the URL of an Octop Bot web/NAS build and sign
   in with the Lynxce account that owns it (or the local password). You then get that server's Bots,
   their tools, skills, memory and MCP connectors, and Bot groups.

The desktop app's built-in server listens on `127.0.0.1` only, so phones connect to a NAS/Docker
deployment (`deploy/docker`, `fnos/`), not to the desktop app.

## Design

Grok-style: dark-first, chat-first, one big character.

- **Colors.** Follow the system theme. Dark: background `#000000`, surface `#141416`, raised
  `#1E1E22`, hairline `#2A2A30`, text `#F4F4F5`, secondary `#9A9AA3`. Light: `#FFFFFF`, `#F4F4F5`,
  `#ECECEF`, `#E4E4E7`, `#111113`, `#6B6B73`. Accent = the current Bot's ink (`inks[color][0]`).
- **Home = Bot directory.** Like a messenger full of characters: large title "Octop Bot", account
  button (Settings) on the left, `+` on the right (New Bot; on a server also New group). Chief is
  pinned first, then the other Bots — each row is its animated character (52 pt, `working` while that
  Bot is replying), name, last reply snippet (cached on the device; else the Bot's subtitle) and time.
  Server mode adds a Groups section with member-character clusters. Long-press a row: edit look (and
  persona/delete for phone-local Bots), voice mode. A floating waveform button opens voice mode with
  the last Bot. Every Bot keeps its own live chat, so several can reply at once.
- **Chat screen** (pushed from the directory). Top bar: back · mini character + name ("Replying…"
  while it works; tap to edit the look) · history (that Bot's conversations as a sheet: New chat,
  swipe to delete) · voice · new chat.
  Empty conversation: the character at 168 pt breathing in the center, "I'm {name}" and its subtitle,
  then 3 suggestion chips.
  Messages: user = right-aligned bubble (surface color, 20 pt radius); assistant = no bubble,
  full-width Markdown with a 26 pt character beside the first line; a collapsible "Thought for a
  moment" row for reasoning; small chips for tool steps ("Using web_search…" / "Used web_search").
  Long-press a message: copy, read aloud, retry (assistant, last one).
- **Composer.** Floating pill at the bottom: `+` (photo library / camera) · multiline field ("Ask
  anything") · mic when empty / send (filled arrow) when there is text / stop (square) while
  streaming. Picked photos show as removable thumbnails above the field.
- **Character motion.** idle = breathe + blink; reply streaming = `working` (bob); reasoning =
  `thinking` (lean); voice listening = `searching` (scan + pupils look around); waiting for the user =
  `waiting` (nod). Chief is the octopus mascot bitmap (`octop-mascot.webp`) animated with the same
  transforms; every other Bot is drawn from `characters.json` (see below).
- **Bot editor.** Live character preview on top, name and persona (phone-local Bots, and any new Bot),
  shape grid (all shapes in `characters.json`), color swatches (all `inks`, `aurora` uses the gradient).
  On a server a new Bot is created there (`POST /api/agents`) and existing Bots change only their look.
- **Voice mode.** The waveform button in the top bar opens a full-screen view: the character large in
  the center, tap the big round button to talk, tap again to send. The transcript appears, the reply
  streams in and is read aloud; the character listens (`searching`) and talks (`working`).
- **Group room** (server mode). Timeline with each Bot's character and name over its messages, live
  drafts shown as streaming bubbles, `@` in the composer opens a member list and inserts `@Name`
  (sent as `mention_ids`). Header shows member characters; info sheet shows goal and shared memory.
  New group: name + pick members; Chief (or the first member) is the admin.
- **Settings.** General: language (follow system / 简体中文 / English — switches live, also drives
  `Accept-Language` and speech recognition) and appearance (follow system / dark / light). Account
  (name, Lynxce balance), connection (Lynxce / server host:port), model (Lynxce models; "Auto" = server
  routing), read replies aloud, notifications, about (version, GitHub link), sign out (also clears the
  cached reply previews).
- **Polish.** Home has a search field and swipe actions (edit look, voice, delete phone-local Bot) and an
  inline banner when a refresh fails. Chat shows a "jump to latest" button when scrolled up, follows the
  stream only while at the bottom, gives built-in Bots their own suggestion chips, collapses more than two
  tool steps into "Used N tools · M steps", and shows the server's localized tool names
  (`GET /api/i18n/tools`). Haptics on send / reply done / copy. The server sheet remembers the last
  address, tries https then http when no scheme is typed, and focuses the next field.
- **Notifications.** When a reply finishes while the app is in the background, post a local
  notification with the Bot's name and the first line. iOS registers its APNs token with Lynxce
  (`/api/user/push-devices`); remote delivery needs the Lynxce push service configured with this
  app's credentials. Android uses local notifications only (no Firebase in v1).

### Characters

`characters.json` (copied from `dashboard/src/vendor/ds-bot`, Apache-2.0, see
`dashboard/public/licenses/ds-bot.txt`) has `shapes`, `inks` and `gradients`. Each shape is drawn in
a 100×100 box, `evenodd` fill:

1. `body` filled with `inks[color][0]` (or the `aurora` linear gradient from (18,10) to (78,92));
2. each `paints` entry `[d, color, opacity]`;
3. `shade` in black at 7 %; `light` in white at 36 %;
4. for each eye `[x, y, w, h, angleDeg]`: translate (x,y), rotate angle, a capsule `w×h` (radius
   `w/2`) in `#FFFCF5`, and a pupil ellipse at (`0.07w`, `0.05h`) with radii (`0.28w`, `0.22h`) in
   `#2D2833` (pupils only when the character is ≥ 24 pt).

Paths use only absolute `M`, relative `l` and `z`, with compact numbers (`-.4`, `.1`).
Animations (period, transform-origin 50 % 84 %): breathe 3.8–4.9 s `translateY(-2%) scale(1.012,1.027)`;
blink every 5.8 s (eyes scaleY → 0.12 for ~120 ms); bob 1.05 s `translateY(-4%) scale(.99,1.025)`;
think 2.8 s rotate −4°; scan 2.2 s ±3 % x with pupils shifting; nod 3.8 s small rotate.
Seed the phase from the Bot id so a row of Bots doesn't move in lockstep.

### Built-in Bots (Lynxce mode)

| id | Name zh / en | Look | Persona (zh; en is the translation) |
|---|---|---|---|
| chief | Chief | octopus | 你是 Chief，Octop Bot 的主助理。回答准确、简洁、友好，需要时分步骤说明。 |
| researcher | 研究员 / Researcher | acorn · green | 你是研究员。先澄清问题，再给出有依据、结构清晰的分析，注明不确定之处。 |
| engineer | 工程师 / Engineer | beacon · cobalt | 你是资深软件工程师。给出可运行的代码和简明解释，指出边界情况。 |
| translator | 翻译官 / Translator | wave · sky | 你是专业翻译。中文译成地道英文，其他语言译成中文，保留格式，只输出译文。 |
| writer | 写作助手 / Writer | cushion · violet | 你是写作助手。帮用户起草、润色和改写文字，语气自然，贴合用户要的风格。 |
| companion | 小伙伴 / Buddy | bunny · tangerine | 你是一个温暖、幽默的聊天伙伴。像朋友一样轻松交流，记住对话里用户说过的事。 |

Subtitles: Chief "你的主助理 / Your main assistant"; researcher "查资料、做分析 / Research and
analysis"; engineer "写代码、排查问题 / Code and debugging"; translator "中英互译 / Translation";
writer "起草与润色 / Drafting and editing"; companion "随便聊聊 / Just chat".

## Build and run

```bash
mobile/scripts/sync-assets.sh          # after characters.json or the mascot changes
```

**iOS** (Xcode 26+, iOS 17+). The project is generated from `ios/project.yml` with XcodeGen and the
generated `OctopBot.xcodeproj` is committed.

```bash
cd mobile/ios && xcodegen generate
xcodebuild -project mobile/ios/OctopBot.xcodeproj -scheme OctopBot -destination 'platform=iOS Simulator,name=iPhone 17' test
```

**Android** (JDK 17, Android SDK 36, min SDK 26).

```bash
cd mobile/android && ./gradlew testDebugUnitTest assembleDebug
```

Application id / bundle id: `io.github.alisonxx.octopbot`.
