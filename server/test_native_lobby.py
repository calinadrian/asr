import io
import struct
import unittest

from native_lobby import NOTICE_JOIN, NOTICE_NAME, NOTICE_TEXT, Lobby, Reader, blob, number, string
from native_websocket import MAX_MESSAGE, ProtocolError, WebSocket


HELLO = bytes.fromhex('010300000007000000302e3132302e310000000001')


def hero(name='Hero', maximum=4, accepting=1):
    return string(name) + b'\x08' + string('elwynn') + bytes([accepting]) + blob(b'\x08') + bytes([maximum])


class Wire:
    def __init__(self):
        self.messages = []

    def send(self, data):
        self.messages.append(data)

    def close(self):
        pass


class LobbyTests(unittest.TestCase):
    def setUp(self):
        self.lobby = Lobby()

    def player(self):
        player = self.lobby.connect(Wire())
        self.lobby.handle(player, HELLO)
        return player

    def test_blood_elf_release_version_can_connect(self):
        player = self.lobby.connect(Wire())
        self.lobby.handle(player, b'\x01' + number(3) + string('0.124.4') + number(0) + b'\x01')
        self.assertEqual(player.version, '0.124.4')

    def room(self, password='', private=False, maximum=5):
        host = self.player()
        self.lobby.handle(host, b'\x03' + string('Test room') + bytes([not private])
                          + string('Survive together') + string(password) + hero(maximum=maximum))
        return host, host.room.code

    def join(self, code, password=''):
        guest = self.player()
        self.lobby.handle(guest, b'\x05' + string(code) + string(password))
        return guest

    def test_capacity_is_four_even_when_client_requests_five(self):
        host, code = self.room()
        guests = [self.join(code) for _ in range(4)]
        self.assertEqual(len(host.room.members), 4)
        self.assertIsNone(guests[-1].room)
        self.assertEqual(guests[-1].wire.messages[-1], b'\x17' + string('the party is full'))
        self.assertEqual(host.room.host.hero.maximum, 4)

    def test_native_list_has_real_room_metadata_and_capacity(self):
        host, code = self.room()
        host.resumable = True  # the update notice is covered separately
        self.lobby.handle(host, b'\x02')
        reader = Reader(host.wire.messages[-1])
        self.assertEqual((reader.byte(), reader.integer()), (20, 1))
        self.assertEqual([reader.string() for _ in range(4)],
                         [code, 'Test room', 'Survive together', 'Hero'])
        self.assertEqual(reader.byte(), 8)
        self.assertEqual(reader.string(), 'elwynn')
        self.assertEqual(reader.take(3), b'\x01\x00\x01')
        self.assertEqual(reader.string(), '')
        self.assertEqual(reader.blob(), b'\x08')
        self.assertEqual(reader.string(), '')
        self.assertEqual(reader.byte(), 4)
        reader.finish()

    def test_games_without_play_asr_see_the_update_notice_first(self):
        host, code = self.room()
        player = self.player()
        self.lobby.handle(player, b'\x02')
        reader = Reader(player.wire.messages[-1])
        self.assertEqual((reader.byte(), reader.integer()), (20, 2))
        self.assertEqual([reader.string() for _ in range(4)], ['UPDATE', NOTICE_NAME, NOTICE_TEXT, 'ASR'])
        self.assertEqual(reader.byte(), 1)
        self.assertEqual(reader.string(), 'elwynn')
        self.assertEqual(reader.take(3), b'\x00\x00\x01')
        self.assertEqual((reader.string(), reader.blob(), reader.string()), ('', b'\x01', ''))
        self.assertEqual(reader.string(), code)
        reader.take(len(player.wire.messages[-1]) - reader.offset - 2)
        self.assertEqual(reader.take(2), b'\x04\x04')
        reader.finish()
        self.lobby.handle(player, b'\x05' + string('update') + string(''))
        self.assertIsNone(player.room)
        self.assertEqual(player.wire.messages[-1], b'\x17' + string(NOTICE_JOIN))
        player.resumable = True
        self.lobby.handle(player, b'\x02')
        self.assertEqual(Reader(player.wire.messages[-1]).take(5), b'\x14' + number(1))
        self.lobby.handle(player, b'\x05' + string('UPDATE') + string(''))
        self.assertEqual(player.wire.messages[-1], b'\x17' + string('no lobby with that code'))

    def test_private_and_password_rooms(self):
        host, code = self.room('secret', private=True)
        self.assertEqual(self.lobby.listing(host.version), b'\x14' + number(0))
        self.assertIsNone(self.join(code, 'wrong').room)
        self.assertIsNotNone(self.join(code, 'secret').room)

    def test_authenticated_host_guest_routes_and_room_isolation(self):
        host, code = self.room()
        guest = self.join(code)
        other_host, other_code = self.room()
        other = self.join(other_code)
        self.assertEqual(host.wire.messages[-1], b'\x18' + number(1))
        self.lobby.handle(guest, b'\x06' + number(0) + blob(b'guest hello'))
        self.assertEqual(host.wire.messages[-1], b'\x1a' + number(1) + blob(b'guest hello'))
        self.lobby.handle(host, b'\x06' + number(1) + blob(b'world data'))
        self.assertEqual(guest.wire.messages[-1], b'\x1a' + number(0) + blob(b'world data'))
        self.assertNotIn(b'world data', b''.join(other.wire.messages))
        with self.assertRaises(ProtocolError):
            self.lobby.handle(guest, b'\x06' + number(1) + blob(b'cross-peer'))
        outsider = self.player()
        with self.assertRaises(ProtocolError):
            self.lobby.handle(outsider, b'\x06' + number(0) + blob(b'outsider'))
        self.assertEqual(other_host.room.code, other_code)

    def test_host_disconnect_closes_room_and_guest_departure_frees_slot(self):
        host, code = self.room()
        guest = self.join(code)
        self.lobby.disconnect(guest)
        self.assertEqual(host.wire.messages[-1], b'\x19' + number(1))
        replacement = self.join(code)
        self.assertEqual(replacement.peer, 2)
        self.lobby.disconnect(host)
        self.assertIsNone(replacement.room)
        self.assertNotIn(code, self.lobby.rooms)

    def test_kick_and_started_run(self):
        host, code = self.room()
        guest = self.join(code)
        with self.assertRaises(ProtocolError):
            self.lobby.handle(guest, b'\x07' + number(0))
        self.lobby.handle(host, b'\x07' + number(guest.peer))
        self.assertIsNone(guest.room)
        self.lobby.handle(host, b'\x04' + hero(accepting=0))
        self.assertIsNone(self.join(code).room)

    def test_unmodified_desktop_host_form_capture(self):
        host = self.player()
        # Captured from the real 0.120.1 Host form: blank name uses its placeholder,
        # Public is true, the class list contains Warrior, and capacity is four.
        packet = bytes.fromhex('030000000001000000000000000005000000566f7279610106000000656c77796e6e01010000000104')
        self.lobby.handle(host, packet)
        self.assertEqual(host.room.name, "Vorya's run")
        self.assertFalse(host.room.private)
        self.assertTrue(host.hero.accepting)
        self.assertEqual(host.hero.classes, b'\x01')
        self.assertIsNotNone(self.join(host.room.code).room)

    def test_malformed_and_unsupported_clients(self):
        for message in (b'', b'\x02', b'\x01' + number(9), HELLO[:-1]):
            with self.subTest(message=message):
                player = self.lobby.connect(Wire())
                with self.assertRaises(ProtocolError):
                    self.lobby.handle(player, message)
        player = self.player()
        for message in (b'\xff', b'\x02trailing', b'\x05' + number(999999)):
            with self.assertRaises(ProtocolError):
                self.lobby.handle(player, message)

    def test_ping_and_host_snapshot(self):
        host, code = self.room()
        guest = self.join(code)
        self.lobby.handle(guest, b'\x09')
        self.assertEqual(guest.wire.messages[-1], b'\x1c')
        snapshot = string('run') + struct.pack('<Q', 10) + number(4) + string('elwynn') + struct.pack('<Q', 11) + blob(b'snapshot')
        self.lobby.handle(host, b'\x0b' + snapshot)
        self.assertEqual(guest.wire.messages[-1], b'\x1e' + string(code) + snapshot)


def frame(payload, opcode=2, final=True):
    mask = b'ABCD'
    size = len(payload)
    length = bytes([128 | size]) if size < 126 else b'\xfe' + struct.pack('!H', size)
    return bytes([(128 if final else 0) | opcode]) + length + mask + bytes(v ^ mask[i % 4] for i, v in enumerate(payload))


class TransportTests(unittest.TestCase):
    def wire(self, data):
        return WebSocket(io.BytesIO(data), io.BytesIO(), None)

    def test_fragmentation_with_interleaved_ping(self):
        wire = self.wire(frame(b'hello ', final=False) + frame(b'p', opcode=9) + frame(b'world', opcode=0))
        self.assertEqual(wire.receive(), b'hello world')
        self.assertEqual(wire.writer.getvalue(), b'\x8a\x01p')

    def test_invalid_frames(self):
        for data in (b'\x82\x00', frame(b'bad', opcode=1), frame(b'bad', opcode=0),
                     b'\x82\xff' + struct.pack('!Q', MAX_MESSAGE + 1),
                     frame(b'bad', opcode=9, final=False)):
            with self.subTest(data=data), self.assertRaises(ProtocolError):
                self.wire(data).receive()

    def test_truncated_frame_and_server_binary_encoding(self):
        with self.assertRaises(EOFError):
            self.wire(frame(b'hello')[:-1]).receive()
        wire = self.wire(b'')
        wire.send(b'x' * 200)
        self.assertEqual(wire.writer.getvalue(), b'\x82\x7e\x00\xc8' + b'x' * 200)


if __name__ == '__main__':
    unittest.main()
