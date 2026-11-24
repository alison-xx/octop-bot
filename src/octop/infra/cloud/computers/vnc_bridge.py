"""VNC over WebSocket inside a Bot's cloud computer (uploaded to and run in the sandbox).

The OSWorld desktop runs x11vnc on localhost:5900, but the sandbox only exposes a few ports to
the outside (5000, 8080, 9222). This bridge listens on 8080, speaks just enough WebSocket for
noVNC (binary frames, ping/close), and relays bytes to the VNC server. Standard library only,
so it runs on the stock image without installing anything.

    python3 vnc_bridge.py [listen_port] [vnc_port]
"""

import base64
import contextlib
import hashlib
import socket
import struct
import sys
import threading

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _read_exact(conn: socket.socket, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk:
            raise ConnectionError("closed")
        data += chunk
    return data


def _send_frame(conn: socket.socket, opcode: int, payload: bytes) -> None:
    head = bytes([0x80 | opcode])
    size = len(payload)
    if size < 126:
        head += bytes([size])
    elif size < 1 << 16:
        head += bytes([126]) + struct.pack("!H", size)
    else:
        head += bytes([127]) + struct.pack("!Q", size)
    conn.sendall(head + payload)


def _handshake(conn: socket.socket) -> bool:
    request = b""
    while b"\r\n\r\n" not in request:
        chunk = conn.recv(4096)
        if not chunk or len(request) > 16384:
            return False
        request += chunk
    headers = {}
    for line in request.split(b"\r\n")[1:]:
        if b":" in line:
            name, value = line.split(b":", 1)
            headers[name.strip().lower()] = value.strip()
    key = headers.get(b"sec-websocket-key")
    if not key:
        conn.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
        return False
    accept = base64.b64encode(hashlib.sha1(key + GUID.encode()).digest())
    response = (
        b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        b"Sec-WebSocket-Accept: " + accept + b"\r\n"
    )
    if b"binary" in headers.get(b"sec-websocket-protocol", b""):
        response += b"Sec-WebSocket-Protocol: binary\r\n"
    conn.sendall(response + b"\r\n")
    return True


def _client_to_vnc(client: socket.socket, vnc: socket.socket) -> None:
    try:
        while True:
            first, second = _read_exact(client, 2)
            opcode = first & 0x0F
            size = second & 0x7F
            if size == 126:
                size = struct.unpack("!H", _read_exact(client, 2))[0]
            elif size == 127:
                size = struct.unpack("!Q", _read_exact(client, 8))[0]
            mask = _read_exact(client, 4) if second & 0x80 else b"\0\0\0\0"
            payload = bytearray(_read_exact(client, size))
            for i in range(len(payload)):
                payload[i] ^= mask[i % 4]
            if opcode == 0x8:  # close
                break
            if opcode == 0x9:  # ping
                _send_frame(client, 0xA, bytes(payload))
                continue
            if opcode in (0x0, 0x1, 0x2):
                vnc.sendall(payload)
    except (OSError, ConnectionError):
        pass
    finally:
        for sock in (client, vnc):
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)


def _vnc_to_client(client: socket.socket, vnc: socket.socket) -> None:
    try:
        while True:
            data = vnc.recv(65536)
            if not data:
                break
            _send_frame(client, 0x2, data)
    except OSError:
        pass
    finally:
        for sock in (client, vnc):
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)


def _serve(client: socket.socket, vnc_port: int) -> None:
    try:
        if not _handshake(client):
            client.close()
            return
        vnc = socket.create_connection(("127.0.0.1", vnc_port))
    except OSError:
        client.close()
        return
    threading.Thread(target=_client_to_vnc, args=(client, vnc), daemon=True).start()
    _vnc_to_client(client, vnc)


def main() -> None:
    listen_port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    vnc_port = int(sys.argv[2]) if len(sys.argv) > 2 else 5900
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", listen_port))
    server.listen(16)
    while True:
        client, _ = server.accept()
        threading.Thread(target=_serve, args=(client, vnc_port), daemon=True).start()


if __name__ == "__main__":
    main()
