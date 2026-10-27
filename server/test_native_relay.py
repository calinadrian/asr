import struct
import time
import unittest

import native_relay
from native_lobby import Lobby, blob, number, string
from native_relay import Relay, u64
from test_native_lobby import HELLO, hero

HOST_ROOM = b'\x03' + string('Test room') + b'\x01' + string('') + string('') + hero()
DROP = object()


class Link:
    """One relay link: plays the queued messages, then drops (EOFError) or closes cleanly (None)."""

    def __init__(self, *incoming, end=DROP):
        self.incoming, self.end = list(incoming), end
        self.messages, self.closed = [], False

    def receive(self):
        if self.incoming:
            return self.incoming.pop(0)
        if self.end is DROP:
            raise EOFError('link dropped')
        return None

    def send(self, data):
        if self.closed:
            raise EOFError('closed')
        self.messages.append(data)

    def close(self):
        self.closed = True

    def lobby(self):
        """The lobby messages this link delivered to Play ASR."""
        return [m[1:] for m in self.messages if m[:1] == b'D']


def hello(token=bytes(16), received=0):
    return b'H' + token + u64(received)


def d(message):
    return b'D' + message


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.lobby = Lobby()
        self.relay = Relay(self.lobby)

    def start(self, *messages, end=DROP):
        link = Link(hello(), d(HELLO), *messages, end=end)
        self.relay.run(link)
        self.assertEqual(link.messages[0][:1], b'W')
        return link, link.messages[0][1:17]

    def session(self, token):
        return self.relay.sessions[token]

    def test_drop_keeps_the_guest_in_the_room_and_resends_what_it_missed(self):
        host_link, host_token = self.start(d(HOST_ROOM))
        host = self.session(host_token).player
        code = host.room.code
        guest_link, guest_token = self.start(d(b'\x05' + string(code) + string('')))
        guest = self.session(guest_token).player
        self.assertIs(guest.room, host.room)
        # Both links dropped; nobody was told anyone left.
        to_host = host_link.lobby() + [m for _, m in self.session(host_token).pending]
        self.assertNotIn(b'\x19' + number(guest.peer), to_host)
        self.assertIn(guest.peer, host.room.members)
        self.lobby.handle(host, b'\x06' + number(guest.peer) + blob(b'world while away'))
        delivered = len(guest_link.lobby())
        back = Link(hello(guest_token, delivered), b'A' + u64(delivered))
        self.relay.run(back)
        self.assertEqual(back.messages[0], b'W' + guest_token + u64(2))
        self.assertEqual(back.lobby(), [b'\x1a' + number(0) + blob(b'world while away')])
        self.assertIs(guest.room, host.room)

    def test_resume_does_not_repeat_acknowledged_messages(self):
        link, token = self.start(d(b'\x02'))
        self.assertEqual(len(link.lobby()), 1)
        back = Link(hello(token, 1))
        self.relay.run(back)
        self.assertEqual(back.lobby(), [])
        self.assertEqual(self.session(token).pending, [])

    def test_unknown_or_ended_session_is_refused(self):
        stranger = Link(hello(b'\x01' * 16))
        self.relay.run(stranger)
        self.assertEqual(stranger.messages, [b'X'])
        link, token = self.start(b'E', end=None)
        self.assertNotIn(token, self.relay.sessions)
        late = Link(hello(token))
        self.relay.run(late)
        self.assertEqual(late.messages, [b'X'])

    def test_game_closing_its_connection_ends_the_party_at_once(self):
        host_link, host_token = self.start(d(HOST_ROOM), b'E', end=None)
        self.assertEqual(self.lobby.rooms, {})
        self.assertEqual(len(self.lobby.players), 0)

    def test_grace_expiry_frees_the_place(self):
        original, native_relay.GRACE = native_relay.GRACE, 0.05
        try:
            host_link, host_token = self.start(d(HOST_ROOM))
            host = self.session(host_token).player
            guest_link, guest_token = self.start(d(b'\x05' + string(host.room.code) + string('')))
            peer = self.session(guest_token).player.peer
            time.sleep(0.3)
        finally:
            native_relay.GRACE = original
        self.assertNotIn(guest_token, self.relay.sessions)
        self.assertNotIn(host_token, self.relay.sessions)
        self.assertEqual(self.lobby.rooms, {})
        self.assertEqual(len(self.lobby.players), 0)
        self.assertNotIn(peer, host.room.members if host.room else {})

    def test_a_returning_link_replaces_a_half_open_one(self):
        link, token = self.start()
        session = self.session(token)
        stale = Link()
        session.attach(stale, 0)
        fresh = Link(hello(token, 0))
        self.relay.run(fresh)
        self.assertTrue(stale.closed)

    def test_backlog_limit_ends_a_session_that_never_returns(self):
        original, native_relay.BACKLOG = native_relay.BACKLOG, 1000
        try:
            host_link, host_token = self.start(d(HOST_ROOM))
            host = self.session(host_token).player
            guest_link, guest_token = self.start(d(b'\x05' + string(host.room.code) + string('')))
            guest = self.session(guest_token).player
            peer = guest.peer
            for _ in range(20):
                self.lobby.handle(host, b'\x06' + number(guest.peer) + blob(b'x' * 100))
        finally:
            native_relay.BACKLOG = original
        self.assertNotIn(guest_token, self.relay.sessions)
        self.assertNotIn(peer, host.room.members)
        self.assertIn(b'' + number(peer), host_link.lobby() + [m for _, m in self.session(host_token).pending])

    def test_heartbeat_is_answered_and_broken_frames_end_the_session(self):
        link, token = self.start(b'A' + u64(0), end=None)
        self.assertIn(b'A' + u64(1), link.messages)
        self.assertIn(token, self.relay.sessions)
        overreach = Link(hello(token, 1), b'A' + u64(5))
        self.relay.run(overreach)
        self.assertNotIn(token, self.relay.sessions)
        link, token = self.start()
        bad = Link(hello(token, 1), b'?')
        self.relay.run(bad)
        self.assertNotIn(token, self.relay.sessions)
        for message in (b'H' + bytes(16) + u64(5), b'D' + HELLO):
            with self.subTest(message=message):
                link = Link(message)
                self.relay.run(link)
                self.assertEqual(link.messages, [])


if __name__ == '__main__':
    unittest.main()
