"""Reads the browser's half of an RFB (VNC) stream so the screen relay can hold back input.

The viewer is view-only until the user takes over, but that is only a client setting; the relay
must not trust it. This follows the client-to-server messages (RFC 6143 §7.5 plus the extensions
noVNC sends) across WebSocket frames, passes the handshake and the screen requests through, and
drops keyboard, mouse and clipboard messages while input is not allowed. A message it does not
know cannot be skipped safely, so it raises and the relay closes.
"""

from __future__ import annotations

import struct

# Client message types that act on the desktop.
_INPUT = {4, 5, 6, 255}  # KeyEvent, PointerEvent, ClientCutText, QEMU extended key event


class RfbClientFilter:
    def __init__(self) -> None:
        self._buffer = b""
        # Handshake: version (12 bytes), security type (1), then ClientInit (1).
        self._stage = "version"

    def feed(self, data: bytes, *, allow_input: bool) -> tuple[bytes, bool]:
        """Bytes to forward, and whether any input message came in (allowed or not)."""
        self._buffer += data
        out = bytearray()
        saw_input = False
        while True:
            size = self._next_size()
            if size is None or len(self._buffer) < size:
                break
            message, self._buffer = self._buffer[:size], self._buffer[size:]
            if self._stage == "messages" and message[0] in _INPUT:
                saw_input = True
                if not allow_input:
                    continue
            out += message
            self._advance(message)
        return bytes(out), saw_input

    def _advance(self, message: bytes) -> None:
        if self._stage == "version":
            self._stage = "security"
        elif self._stage == "security":
            # VNC authentication (type 2) answers a 16-byte challenge first.
            self._stage = "challenge" if message[0] == 2 else "init"
        elif self._stage == "challenge":
            self._stage = "init"
        elif self._stage == "init":
            self._stage = "messages"

    def _next_size(self) -> int | None:
        """Length of the next whole message, or None until enough bytes arrive to tell."""
        buf = self._buffer
        fixed = {"version": 12, "security": 1, "challenge": 16, "init": 1}
        if self._stage in fixed:
            return fixed[self._stage]
        if not buf:
            return None
        kind = buf[0]
        simple = {0: 20, 3: 10, 4: 8, 5: 6, 150: 10, 250: 4, 255: 12}
        if kind in simple:
            return simple[kind]
        if kind == 2:  # SetEncodings
            return None if len(buf) < 4 else 4 + 4 * int(struct.unpack("!H", buf[2:4])[0])
        if kind == 6:  # ClientCutText; a negative length is the extended clipboard
            if len(buf) < 8:
                return None
            return 8 + abs(int(struct.unpack("!i", buf[4:8])[0]))
        if kind == 248:  # ClientFence
            return None if len(buf) < 9 else 9 + buf[8]
        if kind == 251:  # SetDesktopSize
            return None if len(buf) < 8 else 8 + 16 * buf[6]
        raise ValueError(f"unknown RFB client message type {kind}")
