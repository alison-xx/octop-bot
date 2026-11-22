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
| Sign in | `POST /api/auth/password-login` `{account, password}` (account = phone or email) | `{accessToken, refreshToken, user:{id, displayName?}}` |
| Refresh (on any 401, once) | `POST /api/auth/refresh` `{refreshToken}` | `{accessToken, refreshToken?}` |
| Sign out | `POST /api/auth/logout` `{}` | — |
| Balance | `GET /api/user/quota` | object; show the first numeric of `balance`/`credits`/`remaining`/`points` |
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
| Probe | `GET /api/setup/status` | `{setup_required, lynxce_login, local_account, …}` |
| Lynxce identity state | `GET /api/auth/lynxce/status` | `{enabled, claimed}` |
| Sign in with Lynxce (web build) | `POST /api/auth/lynxce/login` `{account, password, locale}` | `{access_token, expires_in, user}`; 403 `LYNXCE_OWNER_MISMATCH` if another account owns the server |
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
  - Block: `{type:"text",text}` · `{type:"thinking",thinking}` · `{type:"tool_use",id,name}`; skip `role:"tool"` rows.
  - `history_loading=true` → retry after `history_retry_after_ms`.
- `DELETE /api/agents/{id}/threads/{tid}`

**Send / stream (WebSocket)** `wss://…/api/agents/{id}/chat/ws?token=<jwt>`

- Send `{"type":"user_turn","thread_id":tid,"text":t,"messages":[{"role":"user","content":t | [Block]}]}`.
- Receive, until `turn.ended`:
  - `turn.started {turn_id, thread_id}`
  - `token {content}` → text; `reasoning {content}` → thinking
  - `tool_call_chunk {id, name?, display_name?}` → tool step running; `tool_result {messages:[{tool_call_id|id,…}]}` → step done
  - `error {message, error_code}` → failed reply
  - `done` (may repeat per segment); `turn.ended {failed?}` = finished
- Stop: `{"type":"cancel","thread_id":tid}`. Keep-alive: `{"type":"ping"}` every 25 s.
- Close codes: 4001 token, 4003 forbidden, 4404 no such Bot.

**Images.** Upload first: `POST /api/agents/{id}/upload` multipart field `file` →
`{workspace_path, url, filename, media_type}`. Then content blocks
`[{"type":"text","text":…},{"type":"image","source":{"type":"url","url":url,"media_type":mt},"workspace_path":wp,"filename":fn}]`.

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

**Not available to phones** (desktop-shell + loopback only): `/api/octop-bot/lynxce/*`, `/wallet`,
`/cloud/*`, `/api/auth/device/*`, Bot computer control.
