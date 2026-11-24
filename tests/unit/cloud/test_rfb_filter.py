"""The screen relay holds the desktop's input back until the user takes over."""

from __future__ import annotations

import struct

import pytest

from octop.infra.cloud.computers.rfb import RfbClientFilter

HANDSHAKE = b"RFB 003.008\n" + b"\x01" + b"\x01"  # version, security None, shared ClientInit
ENCODINGS = b"\x02\x00" + struct.pack("!H", 2) + struct.pack("!ii", 0, -223)
UPDATE = b"\x03\x01" + struct.pack("!HHHH", 0, 0, 1920, 1080)
KEY = b"\x04\x01\x00\x00" + struct.pack("!I", 0x61)
POINTER = b"\x05\x01" + struct.pack("!HH", 10, 20)
CUT = b"\x06\x00\x00\x00" + struct.pack("!I", 2) + b"hi"


def test_view_only_drops_input_but_keeps_the_handshake_and_screen_requests() -> None:
    gate = RfbClientFilter()
    stream = HANDSHAKE + ENCODINGS + UPDATE + KEY + POINTER + CUT + UPDATE
    forwarded, saw_input = gate.feed(stream, allow_input=False)
    assert forwarded == HANDSHAKE + ENCODINGS + UPDATE + UPDATE
    assert saw_input


def test_messages_split_across_frames_are_reassembled() -> None:
    gate = RfbClientFilter()
    stream = HANDSHAKE + ENCODINGS + POINTER + UPDATE
    out = b""
    for i in range(0, len(stream), 3):
        forwarded, _ = gate.feed(stream[i : i + 3], allow_input=True)
        out += forwarded
    assert out == stream


def test_taken_over_input_passes_and_unknown_messages_close_the_relay() -> None:
    gate = RfbClientFilter()
    forwarded, saw_input = gate.feed(HANDSHAKE + KEY + POINTER, allow_input=True)
    assert forwarded == HANDSHAKE + KEY + POINTER and saw_input
    with pytest.raises(ValueError):
        gate.feed(b"\x63" + b"\x00" * 7, allow_input=True)
