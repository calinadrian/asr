"""Verify native TLS rooms and relay traffic without launching a game."""
import argparse
import base64
import hashlib
import os
from pathlib import Path
import socket
import ssl
import struct

from native_lobby import Reader, blob, number, string


class Client:
    def __init__(self, host, port, certificate):
        context = ssl.create_default_context(cafile=str(certificate))
        self.socket = context.wrap_socket(socket.create_connection((host, port), timeout=5), server_hostname=host)
        self.socket.settimeout(5)
        self.reader = self.socket.makefile('rb')
        key = base64.b64encode(os.urandom(16)).decode()
        self.socket.sendall((f'GET /coop/lobby/ HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n'
                             f'Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n\r\n').encode())
        status = self.reader.readline()
        assert status.startswith(b'HTTP/1.1 101 '), status
        headers = {}
        while True:
            line = self.reader.readline()
            if line == b'\r\n':
                break
            name, value = line.decode().strip().split(':', 1)
            headers[name.lower()] = value.strip()
        expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        assert headers['sec-websocket-accept'] == expected
        self.send(bytes.fromhex('010300000007000000302e3132302e310000000001'))

    def send(self, message):
        mask = os.urandom(4)
        length = bytes([128 | len(message)]) if len(message) < 126 else b'\xfe' + struct.pack('!H', len(message))
        self.socket.sendall(b'\x82' + length + mask + bytes(v ^ mask[i % 4] for i, v in enumerate(message)))

    def receive(self):
        header = self.reader.read(2)
        assert len(header) == 2 and header[0] == 130 and not header[1] & 128, header
        size = header[1]
        if size == 126:
            size = struct.unpack('!H', self.reader.read(2))[0]
        elif size == 127:
            size = struct.unpack('!Q', self.reader.read(8))[0]
        assert size <= 1024 * 1024
        data = self.reader.read(size)
        assert len(data) == size
        return data

    def close(self):
        self.reader.close()
        self.socket.close()


def verify(host, port, certificate):
    clients = []
    try:
        def connect():
            client = Client(host, port, certificate)
            clients.append(client)
            return client
        owner = connect()
        hero = string('Verification host') + b'\x01' + string('elwynn') + b'\x01' + blob(b'\x01') + b'\x05'
        owner.send(b'\x03' + string('Native server verification') + b'\x01' + string('Temporary test room') + string('') + hero)
        response = Reader(owner.receive())
        assert response.byte() == 21
        code = response.string()
        guests = []
        for peer in range(1, 4):
            guest = connect()
            guest.send(b'\x05' + string(code) + string(''))
            assert guest.receive() == b'\x16' + string(code)
            assert owner.receive() == b'\x18' + number(peer)
            guests.append(guest)
        fifth = connect()
        fifth.send(b'\x05' + string(code) + string(''))
        assert fifth.receive() == b'\x17' + string('the party is full')
        guests[0].send(b'\x06' + number(0) + blob(b'guest-to-host'))
        assert owner.receive() == b'\x1a' + number(1) + blob(b'guest-to-host')
        owner.send(b'\x06' + number(1) + blob(b'host-to-guest'))
        assert guests[0].receive() == b'\x1a' + number(0) + blob(b'host-to-guest')
        owner.send(b'\x08')
        assert owner.receive() == b'\x1b' + string('you left the run')
        for guest in guests:
            assert guest.receive() == b'\x1b' + string('the host closed the party')
        print('PASS: native TLS upgrade, hosting, joining, four-player cap, bidirectional relay, room cleanup')
    finally:
        for client in clients:
            client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=47770)
    args = parser.parse_args()
    verify(args.host, args.port, Path(__file__).resolve().parent / 'state/server-cert.pem')
