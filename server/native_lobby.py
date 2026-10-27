"""Independent desktop lobby for the protocol-3 binary client (games 0.120.1 and 0.120.4).

Each WebSocket owns its membership. Gameplay stays on the player host; payloads
can travel only between that host and the guests of the same four-player room.
"""
from dataclasses import dataclass, field
import secrets
import struct
import threading
import time

from native_websocket import ProtocolError, WebSocket

# Each verified with two real engines; rooms only list and admit their own version.
SUPPORTED_VERSIONS = ('0.120.1', '0.120.4', '0.120.5', '0.120.6', '0.120.7')


def number(value):
    return struct.pack('<I', value)


def blob(value):
    return number(len(value)) + value


def string(value):
    return blob(value.encode('utf-8'))


class Reader:
    def __init__(self, data):
        self.data, self.offset = data, 0

    def take(self, size):
        if size < 0 or size > len(self.data) - self.offset:
            raise ProtocolError('Truncated lobby message')
        value = self.data[self.offset:self.offset + size]
        self.offset += size
        return value

    def byte(self):
        return self.take(1)[0]

    def integer(self):
        return struct.unpack('<I', self.take(4))[0]

    def blob(self, limit=1024 * 1024 - 32):
        size = self.integer()
        if size > limit:
            raise ProtocolError('Lobby field exceeds limit')
        return self.take(size)

    def string(self, limit=256):
        try:
            value = self.blob(limit).decode('utf-8')
        except UnicodeDecodeError as error:
            raise ProtocolError('Invalid lobby text') from error
        if any(ord(c) < 32 for c in value):
            raise ProtocolError('Invalid lobby text')
        return value

    def finish(self):
        if self.offset != len(self.data):
            raise ProtocolError('Unexpected lobby fields')


@dataclass
class Hero:
    name: str
    class_id: int
    zone: str
    accepting: bool
    classes: bytes
    maximum: int

    @classmethod
    def read(cls, reader):
        name, class_id, zone = reader.string(96), reader.byte(), reader.string(64)
        accepting, classes, maximum = reader.byte(), reader.blob(5), reader.byte()
        valid_classes = (1, 2, 3, 4, 5, 7, 8, 9, 11)
        if (class_id not in valid_classes or accepting not in (0, 1)
                or any(value not in valid_classes for value in classes)):
            raise ProtocolError('Invalid hero')
        return cls(name, class_id, zone, bool(accepting), classes, min(4, max(1, maximum)))


@dataclass(eq=False)
class Player:
    wire: object
    version: str = ''
    room: object = None
    peer: int = 0
    hero: object = None
    status: bytes = b''
    control_times: list = field(default_factory=list)


@dataclass
class Room:
    code: str
    name: str
    private: bool
    password: str
    description: str
    host: Player
    members: dict = field(default_factory=dict)
    next_peer: int = 1


class Lobby:
    def __init__(self):
        self.lock = threading.RLock()
        self.rooms = {}
        self.players = set()

    def connect(self, wire):
        with self.lock:
            if len(self.players) >= 256:
                raise ProtocolError('Directory is full')
            player = Player(wire)
            self.players.add(player)
            return player

    def send(self, player, message):
        try:
            player.wire.send(message)
        except (OSError, EOFError, ValueError):
            player.wire.close()

    def deny(self, player, reason):
        self.send(player, b'\x17' + string(reason))

    def leave(self, player, reason='the host closed the party'):
        room = player.room
        if room is None:
            return
        if player is room.host:
            self.rooms.pop(room.code, None)
            for guest in list(room.members.values()):
                guest.room = None
                if guest is not player:
                    self.send(guest, b'\x1b' + string(reason))
            room.members.clear()
        else:
            room.members.pop(player.peer, None)
            self.send(room.host, b'\x19' + number(player.peer))
        player.room = None
        player.peer = 0

    def disconnect(self, player):
        with self.lock:
            self.leave(player, 'the host left')
            self.players.discard(player)

    def listing(self, version):
        rooms = [r for r in self.rooms.values() if not r.private and r.host.version == version]
        data = bytearray(b'\x14' + number(len(rooms)))
        for room in rooms:
            hero = room.host.hero
            data += (string(room.code) + string(room.name) + string(room.description)
                     + string(hero.name) + bytes([hero.class_id]) + string(hero.zone)
                     + bytes([len(room.members), bool(room.password), hero.accepting])
                     + string(''))  # No third-party IP geolocation service.
            data += blob(hero.classes) + string('')  # Optional host title follows the class list.
        # Newer clients append one capacity byte per record after the older list.
        data += bytes(room.host.hero.maximum for room in rooms)
        return bytes(data)

    def handle(self, player, message):
        with self.lock:
            reader = Reader(message)
            tag = reader.byte()
            if tag != 6:
                now = time.monotonic()
                player.control_times = [t for t in player.control_times if now - t < 1]
                if len(player.control_times) >= 30:
                    raise ProtocolError('Too many lobby requests')
                player.control_times.append(now)
            if tag == 1:
                if player.version or reader.integer() != 3:
                    raise ProtocolError('Unsupported lobby protocol')
                version = reader.string(32)
                reader.string(256)
                compression = reader.byte()
                reader.finish()
                if version not in SUPPORTED_VERSIONS or compression not in (0, 1):
                    raise ProtocolError('Unsupported game version')
                player.version = version
                return
            if not player.version:
                raise ProtocolError('Handshake is required')
            if tag == 2:
                reader.finish()
                self.send(player, self.listing(player.version))
            elif tag == 3:
                name, public = reader.string(128), reader.byte()
                description, password = reader.string(512), reader.string(128)
                hero = Hero.read(reader)
                reader.finish()
                if public not in (0, 1):
                    return self.deny(player, "that lobby name isn't allowed")
                if not name.strip():
                    name = (hero.name or 'Hero') + "'s run"
                if player.room:
                    return self.deny(player, 'already in a lobby')
                if len(self.rooms) >= 64:
                    return self.deny(player, 'too many lobbies open; try again later')
                code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(5))
                while code in self.rooms:
                    code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(5))
                room = Room(code, name, not bool(public), password, description, player)
                player.room, player.hero, player.peer = room, hero, 0
                room.members[0] = player
                self.rooms[code] = room
                self.send(player, b'\x15' + string(code))
            elif tag == 4:
                hero = Hero.read(reader)
                reader.finish()
                player.hero = hero
            elif tag == 5:
                code, password = reader.string(16).upper(), reader.string(128)
                reader.finish()
                if player.room:
                    return self.deny(player, 'already in a lobby')
                room = self.rooms.get(code)
                if room is None:
                    return self.deny(player, 'no lobby with that code')
                if room.host.version != player.version:
                    return self.deny(player, 'that lobby plays a different version of the game')
                if not secrets.compare_digest(password.encode(), room.password.encode()):
                    return self.deny(player, 'wrong password')
                if not room.host.hero.accepting:
                    return self.deny(player, 'the run is under way')
                if len(room.members) >= room.host.hero.maximum:
                    return self.deny(player, 'the party is full')
                player.room, player.peer = room, room.next_peer
                room.next_peer += 1
                room.members[player.peer] = player
                self.send(player, b'\x16' + string(code))
                self.send(room.host, b'\x18' + number(player.peer))
            elif tag == 6:
                target, payload = reader.integer(), reader.blob()
                reader.finish()
                room = player.room
                if room is None:
                    raise ProtocolError('Room membership is required')
                if player is not room.host and target != 0:
                    raise ProtocolError('Guests can send only to their host')
                destination = room.members.get(target)
                if destination is not None and destination is not player:
                    self.send(destination, b'\x1a' + number(player.peer) + blob(payload))
            elif tag == 7:
                target = reader.integer()
                reader.finish()
                room = player.room
                if room is None or player is not room.host or target == 0:
                    raise ProtocolError('Only the host can kick a guest')
                guest = room.members.get(target)
                if guest:
                    self.leave(guest)
                    self.send(guest, b'\x1b' + string('the host sent you away'))
            elif tag == 8:
                reader.finish()
                self.leave(player)
                self.send(player, b'\x1b' + string('you left the run'))
            elif tag == 9:
                reader.finish()
                self.send(player, b'\x1c')
            elif tag == 10:
                # Presence changes stay on this connection; no external presence service.
                reader.take(8)
                player.status = reader.blob(8192)
                reader.finish()
            elif tag == 11:
                # Preserve the host's opaque run snapshot and its native field order.
                room = player.room
                if room is None or player is not room.host:
                    raise ProtocolError('Only the host can publish the run snapshot')
                start = reader.offset
                reader.string(128)
                reader.take(8)
                reader.integer()
                reader.string(128)
                reader.take(8)
                reader.blob(65536)
                reader.finish()
                for guest in room.members.values():
                    if guest is not player:
                        self.send(guest, b'\x1e' + string(room.code) + message[start:])
            else:
                raise ProtocolError('Unknown lobby message')

    def serve(self, handler):
        wire = WebSocket.upgrade(handler)
        player = None
        try:
            player = self.connect(wire)
            while True:
                message = wire.receive()
                if message is None:
                    break
                self.handle(player, message)
        except (ProtocolError, EOFError, OSError):
            pass
        finally:
            if player is not None:
                self.disconnect(player)
            wire.close()
