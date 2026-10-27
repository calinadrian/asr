"""Bounded RFC 6455 transport for the desktop game's binary lobby connection."""
import base64
import hashlib
import socket
import struct
import threading


MAX_MESSAGE = 1024 * 1024


class ProtocolError(ValueError):
    pass


class WebSocket:
    def __init__(self, reader, writer, connection):
        self.reader, self.writer, self.connection = reader, writer, connection
        self.lock = threading.Lock()
        self.closed = False

    @classmethod
    def upgrade(cls, handler):
        headers = handler.headers
        if (headers.get('Upgrade', '').lower() != 'websocket'
                or 'upgrade' not in {v.strip().lower() for v in headers.get('Connection', '').split(',')}
                or headers.get('Sec-WebSocket-Version') != '13'):
            raise ProtocolError('A version 13 WebSocket upgrade is required')
        try:
            key = headers['Sec-WebSocket-Key']
            if len(base64.b64decode(key, validate=True)) != 16:
                raise ValueError()
        except (KeyError, TypeError, ValueError) as error:
            raise ProtocolError('Invalid WebSocket key') from error
        # Native clients do not send Origin. Browsers cannot use this endpoint cross-site.
        origin = headers.get('Origin')
        if origin:
            from urllib.parse import urlsplit
            if urlsplit(origin).netloc != headers.get('Host'):
                raise ProtocolError('Cross-origin connections are unavailable')
        accept = base64.b64encode(hashlib.sha1(
            (key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode('ascii')).digest()).decode('ascii')
        # BaseHTTPRequestHandler defaults to HTTP/1.0; tungstenite correctly
        # rejects an upgrade response unless it uses HTTP/1.1.
        handler.protocol_version = 'HTTP/1.1'
        handler.send_response(101)
        handler.send_header('Upgrade', 'websocket')
        handler.send_header('Connection', 'Upgrade')
        handler.send_header('Sec-WebSocket-Accept', accept)
        handler.end_headers()
        handler.wfile.flush()
        handler.close_connection = True
        handler.connection.settimeout(60)
        return cls(handler.rfile, handler.wfile, handler.connection)

    def read(self, count):
        result = bytearray()
        while len(result) < count:
            chunk = self.reader.read(count - len(result))
            if not chunk:
                raise EOFError('WebSocket disconnected')
            result.extend(chunk)
        return bytes(result)

    def receive(self):
        chunks, length, active = [], 0, False
        while not self.closed:
            first, second = self.read(2)
            final, opcode = bool(first & 128), first & 15
            if first & 112 or not second & 128:
                raise ProtocolError('Unsupported extension or unmasked client frame')
            size = second & 127
            if size == 126:
                size = struct.unpack('!H', self.read(2))[0]
                if size < 126:
                    raise ProtocolError('Noncanonical frame length')
            elif size == 127:
                size = struct.unpack('!Q', self.read(8))[0]
                if size < 65536:
                    raise ProtocolError('Noncanonical frame length')
            if opcode >= 8:
                if not final or size > 125 or opcode not in (8, 9, 10):
                    raise ProtocolError('Invalid control frame')
            elif opcode not in (0, 2) or (opcode == 0) != active:
                raise ProtocolError('Expected binary message or continuation')
            if size > MAX_MESSAGE or (opcode < 8 and length + size > MAX_MESSAGE):
                raise ProtocolError('Message exceeds limit')
            mask = self.read(4)
            payload = bytes(value ^ mask[i % 4] for i, value in enumerate(self.read(size)))
            if opcode == 8:
                if size == 1:
                    raise ProtocolError('Invalid close frame')
                self.close()
                return None
            if opcode == 9:
                self.send(payload, opcode=10)
                continue
            if opcode == 10:
                continue
            chunks.append(payload)
            length += size
            if final:
                return b''.join(chunks)
            active = True
        return None

    def send(self, payload, opcode=2):
        if len(payload) > MAX_MESSAGE:
            raise ProtocolError('Message exceeds limit')
        size = len(payload)
        header = bytes([128 | opcode])
        if size < 126:
            header += bytes([size])
        elif size < 65536:
            header += b'\x7e' + struct.pack('!H', size)
        else:
            header += b'\x7f' + struct.pack('!Q', size)
        with self.lock:
            if self.closed:
                raise EOFError('WebSocket closed')
            self.writer.write(header + payload)
            self.writer.flush()

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            try:
                self.writer.write(b'\x88\x02\x03\xe8')
                self.writer.flush()
            except (OSError, ValueError):
                pass
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
