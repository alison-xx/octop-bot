# Octop Bot mobile — wire protocol

Both native apps (`ios/`, `android/`) speak to one of two backends. This file is the contract they
implement; keep it in sync with the backend when routes change.

## A. Lynxce account (default)

Origin `https://api.lynxce.cn`. Every request sends `X-Lynxce-Client: web` (Lynxce's multi-session
channel — signing in on the phone must not sign the user out elsewhere) and, when signed in,
`Authorization: Bearer <accessToken>`.

JSON responses are wrapped: `{"code": 0, "data": …}`. `code != 0` or a non-2xx status is a failure;
`message` carries the reason. HTTP or code `402` means the account is out of credits.

| Purpose | Request | `data` |
|---|---|---|
| Send sign-in code | `POST /api/auth/phone-code` `{phone}` (as typed, trimmed) or `POST /api/auth/email-code` `{email, locale:"zh-CN"\|"en"}`; email when the input has `@` | `{isRegister, devCode?}` — never show or log `devCode`. 400 `validation_error` (show `message`), 429 too many sends |
| Sign in with code (default) | `POST /api/auth/phone-login` `{phone, code}` or `POST /api/auth/email-login` `{email, code}`; code = 6 digits; new accounts are created | same as password sign-in; 401 `sms_code_invalid`/`sms_code_expired`/`email_code_invalid` → "code wrong or expired" |
| Sign in with password | `POST /api/auth/password-login` `{account, password}` (account = phone or email) | `{accessToken, refreshToken, user:{id, displayName?}}` |
| Refresh (on any 401, once) | `POST /api/auth/refresh` `{refreshToken}` | `{accessToken, refreshToken?}` |
| Sign out | `POST /api/auth/logout` `{}` | — |
| Balance | `GET /api/user/quota` | show `creditsRemaining` (the wallet a recharge adds to; `effectiveCreditsRemaining` can be an enterprise member's monthly allowance), up to 2 decimals |
| Recharge (Android) | `POST /api/billing/recharge/checkout-link` `{}` | `{url, token, expiresAt}`; open only if `url` is exactly `https://admin.lynxce.cn/recharge?token=<token>`, the token matches `x.`-style ticket shape and expires within 16 min; system browser; refresh balance on return |
| Credit packs (iOS) | `GET /api/billing/app/recharge-packages`, header `X-Lynxce-Iap-App: cn.lynxce.octopbot` | `{packages:[{id,name,credits,appleProductId?}], balance, payment:{apple:{enabled}}}`; list only packs with `appleProductId` |
| Buy a pack (iOS) | `POST /api/billing/apple/purchase-intents` `{packageId}` (same header) → StoreKit 2 `purchase(appAccountToken)` → `POST /api/billing/apple/transactions` `{signedTransaction}` | intent `{productId, appAccountToken}`; finish the transaction only after Lynxce accepts it; resend unfinished ones on launch. Lynxce (`submitTransaction` → `assertAppleTransactionBelongsToUser`) credits a transaction only to the account its `appAccountToken` was issued to: 403 `apple_account_token_mismatch` otherwise (keep it queued: that account may sign in on this phone later), 409 `apple_account_token_missing` when it has no token and no earlier order. Finish without crediting, and say why, when Lynxce refuses it for good: `apple_jws_malformed`, `apple_jws_invalid`, `apple_app_mismatch`, `apple_family_sharing_unsupported`, `apple_sandbox_rejected`, `apple_transaction_owned_by_other_account`, `apple_account_token_missing`. Anything else (offline, 5xx, `apple_product_unknown` before the operator maps the product) stays queued |
| Delete account | `POST /api/user/account/deletion-request` `{confirm:"注销账号"}` | `{status:"deactivated", coolingDays}`; signed out everywhere, then sign out locally |
| Models | `GET /api/models/available` | array (or `{items}`/`{models}`) of `{modelId, modelName, supportsImage?}`; no model = server routing ("智能路由") |
| Chat (stream) | `POST /api/proxy/v1/chat/completions` (see below) | raw SSE, not wrapped |
| List conversations | `GET /api/user/web-chat-sessions?limit=50` | `{items:[{id,title,model,updatedAt,messageCount}], nextCursor}` |
| Read conversation | `GET /api/user/web-chat-sessions/{id}` | `{id,title,model,updatedAt,items:[{role,content,thinking?,createdAt?,status?}]}` |
| Save a finished turn | `POST /api/user/web-chat-sessions/{id}/items` `{title(≤80), model, items:[{role,content,createdAt,thinking?,model?}]}` | idempotent append; creates the session |
| Delete conversation | `DELETE /api/user/web-chat-sessions/{id}` | — |
| Speech → text | `POST /api/asr/recognize` multipart, **`langType` (`zh`/`en`) before `file`** | `{text}` |
| Text → speech | `POST /api/tts/synthesize` `{text(≤600 per call), format:"mp3"}` | `{audioBase64, mimeType}` |
| Push device | `POST /api/user/push-devices` `{platform:"ios"|"android", token, bundleId, appVersion, deviceName}` | `{ok}` |

**Chat body**

```json
{"messages":[{"role":"system","content":"<bot persona>"}, …last ≤20 turns…, {"role":"user","content":"hi"}],
 "stream":true, "stream_options":{"include_usage":true},
 "sessionId":"octop-bot-v1-<uuid>", "model":"<optional>",
 "metadata":{"client":"octop-bot-ios|octop-bot-android","turnId":"<uuid>"}}
```

With images the user `content` is `[{"type":"text","text":…},{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,…"}}]`.
The reply is OpenAI SSE: `data: {"choices":[{"delta":{"content":"…","reasoning_content":"…"}}]}` … `data: [DONE]`.
A chunk with `error` is a failure; a stream that ends without `[DONE]` is an interrupted reply.

**Conversation ids** are `octop-bot-v1-<lowercase uuid>` — the same prefix the desktop Bot uses, so
phone and desktop list each other's conversations. The apps list only sessions with that prefix.
Which local Bot owns a conversation is remembered on the device; unknown ids belong to Chief.
Strip a trailing `\n\n[Octop Bot role/v1] {…}` block from user messages written by the desktop.

## B. Self-hosted Octop Bot server (NAS / Docker web build)

Base URL typed by the user (e.g. `https://nas.local:8080`). Errors are
`{"error":{"code","message","details"}}` (message localized by `Accept-Language`).

**Auth.** `Authorization: Bearer <jwt>`. There is no refresh endpoint: whenever a response carries
`X-Octop-Access-Token`, replace the stored token with it. WebSockets pass `?token=<jwt>`.

| Purpose | Request | Response |
|---|---|---|
| Describe (public) | `GET /api/octop-bot/server-info` | `{product:"octop-bot", version, edition:"desktop"\|"web"\|"server", setup_required, sign_in:["lynxce"?,"password"], capabilities:{wallet, cloud_computer, file_store}}`; older servers 404 |
| Probe | `GET /api/setup/status` | `{setup_required, lynxce_login, local_account, …}` |
| Lynxce identity state | `GET /api/auth/lynxce/status` | `{enabled, claimed}` |
| Send Lynxce sign-in code (web build) | `POST /api/auth/lynxce/code` `{target, locale?}` (target = phone or email) | `{channel:"phone"\|"email"}`; 422 `LYNXCE_CODE_TARGET_INVALID`, 429 `LYNXCE_CODE_THROTTLED` (5 sends / 10 min per IP, plus Lynxce's own limit) |
| Sign in with Lynxce code (web build, default) | `POST /api/auth/lynxce/code-login` `{target, code, locale?}` | same as `/lynxce/login`; 401 `LYNXCE_CODE_INVALID`, 403 `LYNXCE_OWNER_MISMATCH` |
| Sign in with Lynxce password (web build) | `POST /api/auth/lynxce/login` `{account, password, locale}` | `{access_token, expires_in, user}`; 403 `LYNXCE_OWNER_MISMATCH` if another account owns the server |
| Sign in with password | `POST /api/auth/login` `{username, password}` (Bot web build: username `local`) | same; `{mfa_required, mfa_token, methods}` → `POST /api/auth/mfa/verify {mfa_token, method:"totp", code}` |
| Me | `GET /api/auth/me` | `{id, username, display_name, …}` |

**Directory.** `GET /api/octop-bot/workspace` → `{chief_id, bots:[Bot], groups:[{group_id,name,admin_id,member_ids,reply_mode}], sections, pinned}`.
`Bot = {agent_id, name, description, icon_url, avatar:{shape,color,source}, is_main, enabled, default_model}`.
Normalize looks like the dashboard: `whale` → Chief? `octop/rose` : `gumdrop`; color `deepseek` → `blue`.
Change a look: `PUT /api/octop-bot/bots/{agent_id}/appearance {shape, color}`.
New Bot: `POST /api/agents {name, description, system_prompt}` → `{agent_id}`, then set its look.

**Threads.**
- `GET /api/agents/{id}/threads?limit=50` → `[{thread_id, title, last_active, has_messages, turn_active, …}]` (show `has_messages`, newest first)
- `POST /api/agents/{id}/threads` → `{thread_id}`
- `GET /api/agents/{id}/threads/{tid}/history?limit=50` → `{messages:[{role, content:[Block], timestamp}], history_loading, history_retry_after_ms, turn_active}`
  - Block: `{type:"text",text}` · `{type:"thinking",thinking}` · `{type:"tool_use",id,name}`; skip `role:"tool"` rows,
    except files a Bot sent: a `role:"tool"` row whose `tool_result` block `name` (after the last `/`) is
    `send_file` or `send_file_to_user` carries `output` = a JSON block or array of blocks;
    `{type:"file",path,filename?,media_type?}` → `/api/agents/{id}/workspace/download?path=<path>`,
    `{type:"image",preview_url|path,…}` → `preview_url` (or the download of `path`). Show them on that turn's reply.
  - `history_loading=true` → retry after `history_retry_after_ms`.
- `DELETE /api/agents/{id}/threads/{tid}`

**Send / stream (WebSocket)** `wss://…/api/agents/{id}/chat/ws?token=<jwt>`

- Send `{"type":"user_turn","thread_id":tid,"text":t,"messages":[{"role":"user","content":t | [Block]}]}`.
- Receive, until `turn.ended`:
  - `turn.started {turn_id, thread_id}`
  - `token {content}` → text; `reasoning {content}` → thinking
  - `tool_call_chunk {id, name?, display_name?}` → tool step running; `tool_result {messages:[{tool_call_id|id,…}]}` → step done
  - `attachment {kind:"file"|"image"|"video"|"audio", url, filename?, path?, mime_type?}` → a file the Bot sent
    (`url` is server-relative: a `…/workspace/download?path=…` or `…/media/preview?source=…` link)
  - `error {message, error_code}` → failed reply
  - `done` (may repeat per segment); `turn.ended {failed?}` = finished
- Stop: `{"type":"cancel","thread_id":tid}`. Keep-alive: `{"type":"ping"}` every 25 s.
- Close codes: 4001 token, 4003 forbidden, 4404 no such Bot.

**Questions and approvals (HITL).** A turn can pause for the user: frame
`hitl_required {request:{pending_id?, action_requests:[{name, args, description?}], review_configs?:[{action_name, allowed_decisions:[…]}]}}`
(unwrap `request.value` up to 3 times if `action_requests` is not top-level), then `turn.ended {hitl_paused:true}`.
This is not a failure: finish the reply normally and show a card.
- `name == "ask_user_question"` → a question. `args` (object or JSON string) holds `questions` (or is one
  question): `[{question | prompt | text, header?, options?:[{label, description?}], multi_select?}]`.
  Card: each question with its options as choices (one, or several when `multi_select`), plus a free-text
  "Something else" answer; questions without options are free text. Answer text: one line per question,
  `"{header or question}: {answer}"`, several choices joined with `"; "`. While a question is open, the
  composer's text is sent as the answer instead of starting a new turn. "You decide" sends
  "You decide — pick the best default and tell me what you assumed." (zh: "你决定吧——按最优默认方案继续，并告诉我你依据的假设。").
  Closing the card sends "The user closed these questions without answering. Do not ask again — wrap up this turn."
  (zh: "用户关闭了这些问题，没有作答。不要再追问，请就此结束本轮。").
- Any other name → an approval: show each action's name (localized via `/api/i18n/tools`), its `description`
  if any, and the key args (`command`/`cmd`, `url`, `path`/`file_path`, `query`), with Approve / Reject.
  Never block the composer: a new message written while an approval is open declines it with
  `{"type":"reject","message":<that text>}` so the Bot sees what the user wants instead.
- Answer: `POST /api/agents/{id}/chat/hitl/resume` `{thread_id, pending_id?, decisions:[…]}` with one
  decision per action: `{"type":"respond","message":answer}` (question), `{"type":"approve"}` or
  `{"type":"reject","message":"Rejected by user"}` (approval). The response is SSE: `event: chunk` with
  `data:` frames of the same types as the socket (`token`, `reasoning`, `tool_call_chunk`, `tool_result`,
  `hitl_required` for a follow-up pause, `error`), ending with `{"type":"done"}` (`hitl_paused:true` if
  paused again). Stream it into a new assistant reply.
- After reopening a conversation, `history.hitl_pending` (`{pending_id, action_requests, review_configs}` or
  null) restores the open card.

**Images.** Upload first: `POST /api/agents/{id}/upload` multipart field `file` →
`{workspace_path, url, filename, media_type}`. Then content blocks
`[{"type":"text","text":…},{"type":"image","source":{"type":"url","url":url,"media_type":mt},"workspace_path":wp,"filename":fn}]`.

**Files.** A file card needs the size: `HEAD /api/agents/{id}/workspace/download?path=…` (same query and auth
as the download) → `Content-Length`, no body; older servers answer 405 (show the type instead). To open or
thumbnail a file, fetch it with `GET` on that link (Octop Bot cloud: get a signed link first, see below).

**Groups** (`/api/octop-bot/groups`). Polled, no socket.
- `GET ""` → `[{group_id,name,admin_id,member_ids,reply_mode}]`; `POST ""` `{name, admin_id, member_ids, reply_mode}`
- `GET /{gid}/messages?after_id=<last message_id>` → `[{message_id, role:"user"|"assistant"|"error", agent_id, text, created_at}]` ascending
- `POST /{gid}/messages` `{request_id:<uuid>, text, mention_ids:[agent_id]}` — blocks until all replies finish (timeout ≥ 10 min); idempotent per `request_id`
- `GET /{gid}/drafts` → `[{agent_id, request_id, text}]` (live partial replies)
- `GET|PUT /{gid}/memory` `{text}`, `GET /{gid}/goal` → `{title, criteria, status, stages}` | null
- Poll messages + drafts every 2.5 s while drafts exist or right after sending, else every 10 s.

**Voice.** `GET /api/voice/active` → `{stt, tts}`. If `stt` is set: `POST /api/voice/stt` multipart
`audio` (file) + `language` (`zh-CN`/`en-US`) → `{text}`. If `tts` is set: `POST /api/voice/tts`
`{text}` → audio bytes. Otherwise use on-device speech recognition and synthesis.

**Octop Bot cloud** (`https://bot.lynxce.cn`, `edition:"cloud"` in server-info; `cloud:true` in `/api/auth/lynxce/status` and in the sign-in response). Every Lynxce account signs in with `/api/auth/lynxce/code` + `/code-login` (or `/login`) and gets its own account; probe it as `.lynxce(claimed: true)`. A phone's "Lynxce account" sign-in goes here when server-info answers `cloud`, otherwise straight to Lynxce (section A). The server keeps the Lynxce session, so the wallet goes through it:

| Purpose | Request | Response |
|---|---|---|
| Balance | `GET /api/octop-bot/wallet?source=cloud` | `{credits, account_id}` |
| Recharge (Android) | `POST /api/octop-bot/wallet/recharge` `{source:"cloud", expected_account_id}` | `{url, expires_at}`; open only `https://admin.lynxce.cn/recharge?token=…` |
| Credit packs (iOS) | `GET /api/octop-bot/wallet/packs` | Lynxce's recharge-packages body (section A) |
| Buy a pack (iOS) | `POST /api/octop-bot/wallet/apple/intent` `{package_id}` → StoreKit → `POST /api/octop-bot/wallet/apple/transaction` `{signed_transaction}` | Lynxce's `{productId, appAccountToken}` / transaction result |
| Delete account | `POST /api/octop-bot/account/delete` | `{cooling_days}`; the account is disabled on the server too |
| Open a file a Bot linked to | `POST /api/agents/{id}/workspace/download-link?path=…` (same query as the `…/workspace/download` link in the reply) | `{url, expires_in}`: a signed object-store URL, opened in the system browser |

**Not available to phones** (desktop-shell + loopback only): `/api/octop-bot/lynxce/*`, `/wallet`,
`/cloud/*`, `/api/auth/device/*`, Bot computer control.
