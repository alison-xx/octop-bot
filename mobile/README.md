# Octop Bot for iOS and Android

Native phone clients for Octop Bot: SwiftUI (`ios/`) and Jetpack Compose (`android/`).
They share no code, only this design and the wire contract in [PROTOCOL.md](PROTOCOL.md).

## Ways to connect

The start page puts the Lynxce account first (a card with 验证码 / 密码 tabs, as on the web), then
"Use without signing in", with "Connect my own server" as a quiet link at the bottom.

1. **Lynxce account (default).** Sign in with a 灵策智算 phone/email and a code or password. When Octop Bot
   cloud (`https://bot.lynxce.cn`) answers, the phone signs in there and gets the cloud's Bots, groups and
   schedules; otherwise it talks to the Lynxce model gateway directly, with Bots defined on the phone and
   conversations synced to the account.
2. **Without signing in.** The user picks a model first (their own vendor API key, or Ollama / LM Studio
   on a computer on the same Wi-Fi), then gets the phone's Bots. The phone calls that OpenAI-compatible
   endpoint itself: nothing goes through Lynxce or the cloud, and conversations stay on the phone
   (`DeviceBackend`). The vendor list ships with the app (`own-key-vendors.json`, made from the server's
   catalog by `scripts/vendor-catalog.py`, OpenAI-protocol vendors only). Keys are sealed on the phone
   (iOS Keychain, Android Keystore) and checked with the vendor's `/models` before they are kept.
3. **Your own server.** Enter the URL of an Octop Bot web/NAS build and sign in with the Lynxce account
   that owns it (or the local password). You then get that server's Bots, their tools, skills, memory and
   MCP connectors, and Bot groups.

### Settings → Models

Three groups, like the desktop:

- **灵策智算 · 积分.** Direct Lynxce: "Auto" and the Lynxce models, plus 积分与充值 (App Store purchase on
  iOS, the recharge Custom Tab on Android). Octop Bot cloud: a line saying chats are paid with credits.
  Not signed in: "Sign in to Lynxce" (back to the start page; keys and chats stay).
- **我的 API Key · 厂商直接收费.** On Octop Bot cloud the keys live in the account
  (`/api/octop-bot/model-keys`, docs/octop-bot-cloud-plan.md §12.9; errors come back localized); otherwise
  they stay on the phone. Each row: vendor logo, name, `****` + last four and the model count, then the
  model in use (green dot) or "Use" with the key's models; swipe or the trash button removes it.
  "Add" opens the add sheet: vendors grouped by company (Tencent Cloud, Bailian, Ark, DeepSeek, Zhipu,
  Kimi, MiniMax, SiliconFlow first, "More vendors" for the rest, a custom OpenAI-compatible URL where
  allowed), then the plan and key with the endpoint and a "Get a key" link, then the models found.
  A key the vendor refuses (401/403) shows "The vendor rejected this key"; a vendor's quota error during
  a chat is an ordinary error, never the Lynxce top-up card, and never signs the user out.
- **本地模型 · 免费** (phone only). Ollama or LM Studio by address (`192.168.1.8` → `:11434/v1`); the
  phone talks to it directly. A self-hosted server manages its own models, so this page is not offered
  there.

The desktop app's built-in server listens on `127.0.0.1` only, so phones connect to a NAS/Docker
deployment (`deploy/docker`, `fnos/`), not to the desktop app.

## Design

Grok-style: dark-first, chat-first, one big character.

- **Colors.** Follow the system theme. Dark: background `#000000`, surface `#141416`, raised
  `#1E1E22`, hairline `#2A2A30`, text `#F4F4F5`, secondary `#9A9AA3`. Light: `#FFFFFF`, `#F4F4F5`,
  `#ECECEF`, `#E4E4E7`, `#111113`, `#6B6B73`. Accent = the current Bot's ink (`inks[color][0]`).
- **Launch.** One piece of art, `splash_art` (the coral octopus with the built-in role characters
  around it, generated with Lynxce `gpt-image-2.5`, transparent PNG), on the launch background
  (black in dark mode, white in light). iOS: `LaunchScreen.storyboard` shows the art at 240 pt,
  centered in the whole screen (plain bundled `Launch/LaunchSplash@Nx.png`: asset-catalog images did not
  render into the launch snapshot; the in-app screen uses the `LaunchArt` asset); Android 12+: `core-splashscreen` with `splash_art` as the icon (288 dp canvas, art
  inside the 192 dp circle, no icon background). The app's first screen then shows the same art in the
  same place and fades in "Octop Bot" and the tagline below it, while the directory loads (at most
  1.2 s, never an artificial delay), then crossfades to Home or the sign-in screen.
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
- **Settings.** A grouped list, top to bottom:
  - *Account card* (not a row): Chief character 56 pt, account name (headline), connection line
    ("Lynxce cloud" or the server's host:port), and on Lynxce a balance chip.
  - *General*: language (follow system / 简体中文 / English — switches live, also drives
    `Accept-Language` and speech recognition), appearance (follow system / dark / light), chat text
    size (small / standard / large = 0.9 / 1.0 / 1.15 × body), haptics (on by default).
  - *Chat*: model (Settings → Models above, with the model in use as the row's value;
    each model's name), expand reasoning by default (off), read replies aloud (off), speaking speed
    (slow / normal / fast = 0.85 / 1.0 / 1.2; applies to the backend voice and the system voice).
  - *Device connectors*: Health (read only), Calendar and Reminders (iOS; Android has Health and
    Calendar), each off until switched on, which asks for the system permission. Bots then read these
    on request and write only after a preview card is confirmed ([PROTOCOL.md](PROTOCOL.md) §C).
  - *Notifications*: notify when a reply finishes. If the system permission is denied, the footer
    says so and offers "Open system settings".
  - *Storage*: "Clear local cache" (reply previews, unread marks, temporary voice and image files;
    keeps sign-in and the remembered server address), with a confirmation.
  - *Account*: signed in as, connection (server: full address, tap to copy), "Switch account or
    server" (signs out and returns to the first screen; for a server, reopens the server sheet with
    the address filled), "Sign out" (destructive, confirmed; also clears previews and unread marks).
  - *About*: version "1.0.0 (1)", project page (GitHub), report a problem (GitHub new issue), Lynxce
    website.
- **Polish.** Home has a search field and swipe actions (edit look, voice, delete phone-local Bot) and an
  inline banner when a refresh fails. Chat shows a "jump to latest" button when scrolled up, follows the
  stream only while at the bottom, gives built-in Bots their own suggestion chips, collapses more than two
  tool steps into "Used N tools · M steps", and shows the server's localized tool names
  (`GET /api/i18n/tools`). Haptics on send / reply done / copy. The server sheet remembers the last
  address, tries https then http when no scheme is typed, and focuses the next field.
- **Details.**
  - *Directory order and unread.* Chief stays pinned; the other Bots sort by their last reply (newest
    first), then directory order. A reply that finishes while that Bot's chat is not on screen marks
    it unread: an accent dot after the time and the preview in the primary color, semibold. Opening
    the chat clears it. Unread marks are kept with the previews.
  - *Chat top bar.* Under the Bot's name: "Replying…" / "Thinking…" while it works, otherwise the open
    conversation's title (one line, secondary).
  - *Reply actions.* Under every finished assistant reply a row of small icon buttons (secondary
    color): copy, read aloud (becomes stop while speaking), share, and retry on the last reply.
    Long-press keeps the same menu. A user message long-press offers copy and "Edit" (puts the text
    back into the composer).
  - *Time separators.* Before the first message, and before any message more than 10 minutes after
    the previous one, a centered caption: today "14:05", yesterday "Yesterday 14:05", this year
    "Nov 20 14:05", older with the year. Same in group rooms.
  - *Images.* Tapping an image in a message opens a full-screen viewer (pinch to zoom, double-tap to
    zoom, share, close / swipe down).
  - *Files* (server mode). Files a Bot sends (`send_file_to_user`) or links to show under the reply as
    cards, like Grok: a page glyph whose bottom band is colored by type (red PDF, blue Word, green
    Excel/CSV, orange PowerPoint, purple archives, gray otherwise) with the type on it, the name
    shortened in the middle with the extension kept, and the size (`HEAD` on the download link).
    Pictures are the card themselves (rounded 16, at most 320 wide); a PDF shows its first page and a
    small CSV / text file its first lines (iOS draws thumbnails with Quick Look). Several files scroll
    sideways. Tap opens the file (iOS Quick Look, Android "Open with"); long-press offers share and
    save (Files on iOS, Downloads on Android).
  - *Errors.* The chat error banner hides by itself after 4 s or on tap; a microphone failure shown
    in the composer clears after 4 s too.
  - *History sheet.* A search field (titles), conversations grouped into Today / Yesterday / Previous
    7 days / Earlier, a checkmark on the open one, swipe to delete.
  - *Group room.* Time separators, long-press copy on any message, haptic on send. Sending is never
    disabled while earlier posts wait for replies; a post that fails stays in the timeline marked
    "Not sent — tap to retry" (same `request_id`, so the server never doubles it). Poll with
    `after_id` = the last server message id, never a local echo's id.
  - *Never block the user.* Typing and sending always work. While a reply streams, the send button
    shows when there is text (stop when the field is empty); the message is queued, shown as a dashed
    "Queued" bubble that can be cancelled, and sent when the reply ends. A newer reply run never lets
    a cancelled older one change its state.
  - *Questions and approvals* (server mode; PROTOCOL.md B "Questions and approvals"). A card docks
    above the composer: question card (choices / multi-choice / free text, "You decide", close) or
    approval card (action, description, key args, Approve / Reject). Typing in the composer answers an
    open question, or declines an open approval with that text as the reason. A centered caption notes
    "Approved: …" / "Declined: …". Paused or finished replies never leave a tool chip spinning.
  - *Bot editor.* A shuffle button under the preview picks a random shape and color; phone-local Bots
    get a "Delete Bot" button at the bottom (confirmed).
  - Text size, reasoning default, haptics and speaking speed from Settings apply everywhere at once.
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

### Soft characters

Servers built from the newer dashboard give Bots soft, flat characters (`orb`, `heart`, `sparkle`,
`drop`, `cloud`, `bean`, from `dashboard/src/pages/OctopBot/softShapes.ts`). `soft-characters.json`
(made by `scripts/soft-characters.py`, run by `sync-assets.sh`) holds them as `{shapes: {id: {body, eyes,
flat: true}}, inks: {id: [light, dark]}}`. Merge like the dashboard: soft shapes first, then DS shapes;
soft inks override DS inks of the same name and come first in pickers. A flat shape is the body in its
ink plus plain white capsule eyes (no shade, light or pupils). Every ink uses its second color in dark
mode (soft `black` is white there).

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

Application id / bundle id: iOS `cn.lynxce.octopbot`, Android `io.github.alisonxx.octopbot`.
