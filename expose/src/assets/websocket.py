#!/usr/bin/env python3
"""WebSocket echo server for expose --websocket"""
import struct, hashlib, base64, sys, os, socket

PORT = int(os.environ.get('EXPOSE_PORT', 9090))
BIND = os.environ.get('EXPOSE_BIND', '0.0.0.0')

GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

def accept_key(key):
    sha1 = hashlib.sha1(key.encode() + GUID).digest()
    return base64.b64encode(sha1).decode()

def read_frame(sock):
    data = sock.recv(2)
    if len(data) < 2:
        return None, b''
    opcode = data[0] & 0x0F
    masked = (data[1] & 0x80) != 0
    length = data[1] & 0x7F
    if length == 126:
        data = sock.recv(2)
        length = struct.unpack('>H', data)[0]
    elif length == 127:
        data = sock.recv(8)
        length = struct.unpack('>Q', data)[0]
    mask_key = sock.recv(4) if masked else b''
    payload = bytearray()
    while len(payload) < length:
        chunk = sock.recv(min(length - len(payload), 4096))
        if not chunk:
            break
        payload.extend(chunk)
    if masked:
        payload = bytearray(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    return opcode, bytes(payload)

def send_frame(sock, opcode, payload):
    frame = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        frame.append(length)
    elif length < 65536:
        frame.append(126)
        frame.extend(struct.pack('>H', length))
    else:
        frame.append(127)
        frame.extend(struct.pack('>Q', length))
    frame.extend(payload)
    sock.sendall(bytes(frame))

def handle_client(conn):
    try:
        data = b''
        while b'\r\n\r\n' not in data:
            chunk = conn.recv(4096)
            if not chunk:
                return
            data += chunk

        headers = {}
        for line in data.decode('utf-8', 'replace').split('\r\n')[1:]:
            if ':' in line:
                k, v = line.split(':', 1)
                headers[k.strip().lower()] = v.strip()

        key = headers.get('sec-websocket-key', '')
        if not key:
            conn.sendall(b'HTTP/1.1 400 Bad Request\r\n\r\n')
            return

        accept = accept_key(key)
        resp = (
            'HTTP/1.1 101 Switching Protocols\r\n'
            'Upgrade: websocket\r\n'
            'Connection: Upgrade\r\n'
            f'Sec-WebSocket-Accept: {accept}\r\n'
            '\r\n'
        )
        conn.sendall(resp.encode())

        while True:
            opcode, payload = read_frame(conn)
            if opcode is None:
                break
            if opcode == 0x8:  # Close
                send_frame(conn, 0x8, b'')
                break
            elif opcode == 0x9:  # Ping
                send_frame(conn, 0xA, payload)  # Pong
            elif opcode == 0x1:  # Text
                send_frame(conn, 0x1, b'Echo: ' + payload)
            elif opcode == 0x2:  # Binary
                send_frame(conn, 0x2, payload)
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((BIND, PORT))
    srv.listen(5)
    print(f'WebSocket echo server: ws://{BIND}:{PORT}', file=sys.stderr)
    try:
        while True:
            conn, addr = srv.accept()
            print(f'  {addr[0]}:{addr[1]} connected', file=sys.stderr)
            handle_client(conn)
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()

if __name__ == '__main__':
    main()