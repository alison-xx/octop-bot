"""Capture the current turn from harness stream state for cheap UI history."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from langchain_core.messages import AIMessage, convert_to_messages, message_to_dict

from octop.infra.db.repos._base import now_ts
from octop.infra.db.repos.thread_messages import ThreadMessageInput, ThreadMessageRow
from octop.infra.gateway.process.message_keys import (
    CHECKPOINT_TS_KEY,
    STREAM_ERROR_CODE_KEY,
    STREAM_ERROR_FLAG,
    parse_checkpoint_ts_ms,
)

_USER_ROLES = frozenset({"human", "user"})
_ASSISTANT_ROLES = frozenset({"ai", "assistant"})
_TURN_DURATION_KEY = "turn_duration_ms"
_UTF16_SURROGATE = re.compile(r"[\ud800-\udfff]")
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


def _repair_surrogates(text: str) -> str:
    """Rejoin split surrogate pairs and replace unpaired halves with U+FFFD."""
    if _UTF16_SURROGATE.search(text) is None:
        return text
    return text.encode("utf-16-le", errors="surrogatepass").decode("utf-16-le", errors="replace")


def _stamp_duration(items: list[ThreadMessageInput], duration_ms: int) -> list[ThreadMessageInput]:
    """Put the turn wall time on the last assistant reply in this projection."""
    fallback: int | None = None
    for index in range(len(items) - 1, -1, -1):
        item = items[index]
        if item.role not in _ASSISTANT_ROLES:
            continue
        try:
            wire = json.loads(item.message_json)
        except json.JSONDecodeError:
            return items
        data = wire.get("data") if isinstance(wire, dict) else None
        if not isinstance(data, dict):
            return items
        if data.get("tool_calls"):
            if fallback is None:
                fallback = index
            continue
        fallback = index
        break
    if fallback is None:
        return items
    item = items[fallback]
    wire = json.loads(item.message_json)
    data = wire["data"]
    extra = data.get("additional_kwargs")
    if not isinstance(extra, dict):
        extra = {}
        data["additional_kwargs"] = extra
    extra[_TURN_DURATION_KEY] = duration_ms
    items[fallback] = replace(
        item,
        message_json=json.dumps(wire, ensure_ascii=False, default=str),
    )
    return items


# deepagents ``read_file`` on an image or video answers with a ToolMessage plus a
# synthetic HumanMessage carrying the media for the model. That message is not
# the user speaking: it must not start a turn or show up as a user bubble.
# Octop Bot cloud computer screenshots (``cloud_computer``) arrive the same way.
_TOOL_MEDIA_SOURCES = frozenset({"read_file_media", "cloud_computer"})
_TOOL_MEDIA_ROLE = "tool_media"


def _is_tool_media(message: Any) -> bool:
    if isinstance(message, dict):
        inner = message.get("data")
        data: dict[str, Any] = inner if isinstance(inner, dict) else message
        extra = data.get("additional_kwargs")
    else:
        extra = getattr(message, "additional_kwargs", None)
    return isinstance(extra, dict) and extra.get("lc_source") in _TOOL_MEDIA_SOURCES


def _role(message: Any) -> str:
    if _is_tool_media(message):
        return _TOOL_MEDIA_ROLE
    if isinstance(message, dict):
        return str(message.get("role") or message.get("type") or "").lower()
    return str(getattr(message, "type", None) or getattr(message, "role", "")).lower()


def _chunk_messages(chunk: dict[str, Any]) -> list[Any]:
    data = chunk.get("data")
    if isinstance(data, dict) and isinstance(data.get("messages"), list):
        return list(data["messages"])
    if isinstance(data, list):
        return list(data)
    return []


def checkpoint_ts_ms(message: Any) -> int | None:
    kwargs = getattr(message, "additional_kwargs", None)
    if not isinstance(kwargs, dict):
        return None
    return parse_checkpoint_ts_ms(kwargs.get(CHECKPOINT_TS_KEY))


def _ensure_checkpoint_ts(message: Any, *, now_ms: int | None = None) -> Any:
    """Stamp ``checkpoint_ts`` on a live copy. Existing stamps are left alone."""
    if checkpoint_ts_ms(message) is not None:
        return message
    copy = getattr(message, "model_copy", None)
    if not callable(copy):
        return message
    kwargs = dict(getattr(message, "additional_kwargs", None) or {})
    kwargs[CHECKPOINT_TS_KEY] = now_ms if now_ms is not None else int(time.time() * 1000)
    return copy(update={"additional_kwargs": kwargs})


def _convert_message(message: Any) -> Any:
    return convert_to_messages([message])[0] if isinstance(message, dict) else message


def message_input(message: Any) -> ThreadMessageInput | None:
    """Serialize one LangChain/dict message. Never invents ``checkpoint_ts``."""
    try:
        converted = _convert_message(message)
        wire = message_to_dict(converted)
        role = _role(converted)
        if role in ("", "system", _TOOL_MEDIA_ROLE):
            return None
        ts_ms = checkpoint_ts_ms(converted)
        # Repair after assembly so paired halves from different deltas survive
        # as one character and the projected JSON can be stored as UTF-8.
        message_json = _repair_surrogates(json.dumps(wire, ensure_ascii=False, default=str))
        return ThreadMessageInput(
            message_id=str(getattr(converted, "id", "") or "") or None,
            role=role,
            message_json=message_json,
            created_at=(ts_ms // 1000) if ts_ms is not None else now_ts(),
        )
    except Exception:
        return None


def live_message_input(message: Any, *, now_ms: int | None = None) -> ThreadMessageInput | None:
    """Serialize a current-turn message, stamping ``checkpoint_ts`` if missing."""
    try:
        return message_input(_ensure_checkpoint_ts(_convert_message(message), now_ms=now_ms))
    except Exception:
        return None


def message_inputs(
    messages: list[Any],
    *,
    dedupe_missing_ids: bool = False,
) -> list[ThreadMessageInput]:
    """Serialize and de-duplicate replays within one stream/backfill batch."""
    out: list[ThreadMessageInput] = []
    seen: set[str] = set()
    for message in messages:
        item = message_input(message)
        if item is None:
            continue
        key = f"id:{item.message_id}" if item.message_id else ""
        if not key and dedupe_missing_ids:
            key = "wire:" + hashlib.sha256(item.message_json.encode()).hexdigest()
        if not key:
            out.append(item)
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def live_message_inputs(
    messages: list[Any],
    *,
    dedupe_missing_ids: bool = False,
    now_ms: int | None = None,
) -> list[ThreadMessageInput]:
    """Like ``message_inputs``, but stamps missing ``checkpoint_ts`` on this turn."""
    prepared: list[Any] = []
    for message in messages:
        try:
            prepared.append(_ensure_checkpoint_ts(_convert_message(message), now_ms=now_ms))
        except Exception:
            continue
    return message_inputs(prepared, dedupe_missing_ids=dedupe_missing_ids)


def _wire_text(item: ThreadMessageInput | ThreadMessageRow) -> str:
    try:
        wire = json.loads(item.message_json)
    except json.JSONDecodeError:
        return ""
    data = wire.get("data") if isinstance(wire, dict) else None
    content = data.get("content") if isinstance(data, dict) else None
    if content is None and isinstance(wire, dict):
        content = wire.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return ""


def _squash(text: str) -> str:
    return "".join(text.split())


def _assistant_text(items: Sequence[ThreadMessageInput | ThreadMessageRow]) -> str:
    return "".join(_wire_text(item) for item in items if item.role in _ASSISTANT_ROLES)


def uncovered_stream_text(stream: str, said: str) -> str:
    """The part of a turn's streamed text that no stored assistant step holds.

    Tokens of every model step arrive as one stream, so a multi-step reply is
    covered by its steps together, never by one of them. Whitespace is ignored:
    stored steps keep separators the stream does not have, and the other way
    round. A turn stopped mid-reply leaves the text after the last stored step.
    Stored steps may also keep a ``<think>`` block the stream never carried, so
    the steps are tried with and without it and the shorter remainder wins.
    An emoji split across two tokens is rejoined before comparing.
    """
    stream = _repair_surrogates(stream)
    raw = _uncovered(stream, said)
    visible = _uncovered(stream, _THINK_BLOCK.sub(" ", said))
    return raw if len(raw) <= len(visible) else visible


def _uncovered(stream: str, said: str) -> str:
    key = _squash(said)
    if _squash(stream) in key:
        return ""
    if not key:
        return stream
    matched = 0
    for index, char in enumerate(stream):
        if char.isspace():
            continue
        if matched == len(key):
            return stream[index:]
        if char != key[matched]:
            return stream
        matched += 1
    return ""


def _stream_copy_candidate(row: ThreadMessageRow) -> bool:
    if row.message_id or row.role not in _ASSISTANT_ROLES:
        return False
    try:
        data = json.loads(row.message_json).get("data")
    except (json.JSONDecodeError, AttributeError):
        return False
    if not isinstance(data, dict) or data.get("tool_calls"):
        return False
    extra = data.get("additional_kwargs")
    if isinstance(extra, dict) and extra.get(STREAM_ERROR_FLAG):
        return False
    return bool(_squash(_wire_text(row)))


def drop_stream_copies(
    rows: list[ThreadMessageRow],
    turn_before: Callable[[int], list[ThreadMessageRow]],
) -> list[ThreadMessageRow]:
    """Hide id-less rows that repeat a turn's whole streamed reply.

    Older builds stored every multi-step turn's token stream once more after
    its steps. ``turn_before(seq)`` returns the stored rows of that turn
    before ``seq``, starting with its user message.
    """
    kept: list[ThreadMessageRow] = []
    for row in rows:
        if _stream_copy_candidate(row):
            said = _assistant_text(turn_before(row.seq))
            if said and not uncovered_stream_text(_wire_text(row), said):
                continue
        kept.append(row)
    return kept


def compaction_boundary(state: Any) -> str | None:
    """Identify the first original message retained by a native compaction."""
    event = state.get("_summarization_event") if isinstance(state, dict) else None
    if not isinstance(event, dict):
        return None
    boundary = event.get("cutoff_message_id")
    if isinstance(boundary, str) and boundary:
        return boundary
    index = event.get("cutoff_index")
    messages = state.get("messages")
    if isinstance(index, int) and isinstance(messages, list) and 0 <= index < len(messages):
        first = messages[index]
        boundary = first.get("id") if isinstance(first, dict) else getattr(first, "id", None)
        if isinstance(boundary, str) and boundary:
            return boundary
    return None


@dataclass
class TurnHistoryTracker:
    """Keep only the current user turn from replay-prone state chunks."""

    seed_messages: list[Any] = field(default_factory=list)
    compaction_boundaries: set[str] = field(default_factory=set, init=False)
    _state_messages: list[Any] = field(default_factory=list, init=False)
    _stream_text: str = field(default="", init=False)
    _reasoning_text: str = field(default="", init=False)
    _error_message: str = field(default="", init=False)
    _error_code: str | None = field(default=None, init=False)
    _turn_duration_ms: int | None = field(default=None, init=False)

    def note_turn_duration(self, duration_ms: int) -> None:
        if duration_ms < 0:
            return
        self._turn_duration_ms = int(duration_ms)

    @classmethod
    def from_request(cls, request: dict[str, Any]) -> TurnHistoryTracker:
        raw = request.get("messages")
        return cls(seed_messages=list(raw) if isinstance(raw, list) else [])

    def observe(self, chunk: dict[str, Any]) -> None:
        kind = chunk.get("type")
        if kind in ("state_snapshot", "state_update"):
            messages = _chunk_messages(chunk)
            if boundary := compaction_boundary(chunk.get("data")):
                self.compaction_boundaries.add(boundary)
            if not messages:
                return
            last_user = max(
                (index for index, msg in enumerate(messages) if _role(msg) in _USER_ROLES),
                default=-1,
            )
            if last_user >= 0:
                self._state_messages = messages[last_user:]
            else:
                self._state_messages.extend(messages)
            return
        if kind == "token":
            self._stream_text += str(chunk.get("content") or "")
            return
        if kind == "reasoning":
            self._reasoning_text += str(chunk.get("content") or "")
            return
        if kind == "error":
            text = str(chunk.get("message") or chunk.get("content") or "")
            if text:
                self._error_message = text
            code = chunk.get("error_code")
            if code:
                self._error_code = str(code)

    def _stream_message(self, text: str) -> ThreadMessageInput | None:
        if not text and not self._reasoning_text:
            return None
        extra: dict[str, Any] = {}
        if self._reasoning_text:
            extra["reasoning_content"] = self._reasoning_text
        return live_message_input(AIMessage(content=text, additional_kwargs=extra))

    def _error_input(self) -> ThreadMessageInput | None:
        if not self._error_message:
            return None
        extra: dict[str, Any] = {STREAM_ERROR_FLAG: True}
        if self._error_code:
            extra[STREAM_ERROR_CODE_KEY] = self._error_code
        return live_message_input(AIMessage(content=self._error_message, additional_kwargs=extra))

    @property
    def inputs(self) -> list[ThreadMessageInput]:
        state_has_user = any(_role(msg) in _USER_ROLES for msg in self._state_messages)
        source = (
            self._state_messages if state_has_user else [*self.seed_messages, *self._state_messages]
        )
        items = live_message_inputs(
            source,
            dedupe_missing_ids=True,
        )
        rest = uncovered_stream_text(self._stream_text, _assistant_text(items))
        if rest or not self._stream_text:
            streamed = self._stream_message(rest)
            if streamed is not None:
                items.append(streamed)
        error = self._error_input()
        if error is not None:
            items.append(error)
        if isinstance(self._turn_duration_ms, int):
            items = _stamp_duration(items, self._turn_duration_ms)
        return items
