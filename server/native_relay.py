"""Resumable lobby connections for games started by Play ASR.exe.

The game talks to Play ASR on loopback, which never drops; Play ASR talks to this endpoint and
reconnects when the internet does. A dropped link keeps the player's place in the lobby for
GRACE seconds: messages for them wait here, theirs wait in Play ASR, and both sides resend
what the other has not received.

Every message is binary; the first byte says what it is:
  H token(16) received(u64)  Play ASR, first on each link: all-zero token for a new session
  W token(16) received(u64)  server reply: the session's token and how many D it has received
  X                          server reply: that session has ended; Play ASR closes the game's connection
  D lobby-message            a native lobby message in either direction, numbered from 0 by its sender
  A received(u64)            acknowledgement; Play ASR sends one every few seconds as a heartbeat
  E                          the game closed its connection, or the server ended the session
"""
import secrets
import struct
import threading
import time

from native_websocket import ProtocolError, WebSocket

GRACE = 120          # seconds a dropped player keeps their place
LINK_TIMEOUT = 20    # Play ASR sends a heartbeat every 5 seconds
BACKLOG = 32 << 20   # unacknowledged bytes kept for a dropped player before the session ends
ACK_EVERY = 32


def u64(value):
    return struct.pack('<Q', value)


class Session:
    """Stands in for a player's WebSocket in the lobby, across any number of links."""

    def __init__(self, relay):
        self.relay, self.token = relay, secrets.token_bytes(16)
        self.lock = threading.Lock()
        self.link = None
        self.pending = []    # (number, message) sent but not yet acknowledged
        self.sent = 0        # D messages produced for Play ASR
        self.received = 0    # D messages from Play ASR handed to the lobby
        self.backlog = 0
        self.ended = False
        self.player = None
        self.generation = 0

    # The lobby calls these, always holding its own lock.
    def send(self, message):
        with self.lock:
            if self.ended:
                raise EOFError('Session ended')
            self.pending.append((self.sent, message))
            self.sent += 1
            self.backlog += len(message)
            if self.backlog > BACKLOG:
                raise EOFError('Dropped player fell too far behind')
            link = self.link
        if link is not None:
            try:
                link.send(b'D' + message)
            except (OSError, EOFError, ValueError):
                self.detach(link)

    def close(self):
        # The lobby gave up on this player (a send failed): end the session and free their place.
        self.relay.end(self)

    def shutdown(self):
        with self.lock:
            if self.ended:
                return
            self.ended = True
            link, self.link = self.link, None
        if link is not None:
            try:
                link.send(b'E')
            except (OSError, EOFError, ValueError):
                pass
            link.close()

    def acknowledge(self, count):
        with self.lock:
            if count > self.sent:
                raise ProtocolError('Acknowledged messages that were never sent')
            while self.pending and self.pending[0][0] < count:
                self.backlog -= len(self.pending.pop(0)[1])

    def attach(self, link, received):
        """Make link current and resend what Play ASR has not received yet."""
        self.acknowledge(received)
        with self.lock:
            if self.ended:
                raise EOFError('Session ended')
            old, self.link = self.link, link
            self.generation += 1
            missed = [message for number, message in self.pending if number >= received]
            # Under the session lock so a concurrent send cannot overtake the resent backlog.
            link.send(b'W' + self.token + u64(self.received))
            for message in missed:
                link.send(b'D' + message)
        if old is not None and old is not link:
            old.close()

    def detach(self, link):
        """The link dropped: keep the place for GRACE seconds unless another link took over."""
        with self.lock:
            if self.link is not link or self.ended:
                return
            self.link = None
            generation = self.generation
        link.close()
        timer = threading.Timer(GRACE, self.expire, args=(generation,))
        timer.daemon = True
        timer.start()

    def expire(self, generation):
        with self.lock:
            if self.ended or self.link is not None or self.generation != generation:
                return
        self.relay.end(self)


class Relay:
    def __init__(self, lobby):
        self.lobby = lobby
        self.lock = threading.Lock()
        self.sessions = {}

    def end(self, session):
        with self.lock:
            if self.sessions.pop(session.token, None) is None and session.ended:
                return
        session.shutdown()
        if session.player is not None:
            self.lobby.disconnect(session.player)

    def serve(self, handler):
        wire = WebSocket.upgrade(handler)
        handler.connection.settimeout(LINK_TIMEOUT)
        self.run(wire)

    def run(self, wire):
        session = None
        try:
            hello = wire.receive()
            if hello is None or len(hello) != 25 or hello[:1] != b'H':
                raise ProtocolError('Relay hello is required')
            token, received = hello[1:17], struct.unpack('<Q', hello[17:])[0]
            if token == bytes(16):
                if received:
                    raise ProtocolError('A new session has received nothing')
                # Never hold the relay lock while taking the lobby's: the lobby ends sessions under its own.
                player = self.lobby.connect(Session(self))
                session = player.wire
                session.player = player
                with self.lock:
                    self.sessions[session.token] = session
            else:
                with self.lock:
                    session = self.sessions.get(token)
            if session is None:
                wire.send(b'X')
                return
            try:
                session.attach(wire, received)
            except EOFError:
                session = None
                wire.send(b'X')
                return
            since_ack = 0
            while True:
                message = wire.receive()
                if message is None:
                    break
                kind = message[:1]
                if session.link is not wire:
                    break  # a newer link took over this session
                if kind == b'D':
                    session.received += 1
                    self.lobby.handle(session.player, message[1:])
                    since_ack += 1
                    if since_ack >= ACK_EVERY:
                        wire.send(b'A' + u64(session.received))
                        since_ack = 0
                elif kind == b'A' and len(message) == 9:
                    session.acknowledge(struct.unpack('<Q', message[1:])[0])
                    wire.send(b'A' + u64(session.received))
                    since_ack = 0
                elif kind == b'E' and len(message) == 1:
                    self.end(session)
                    session = None
                    return
                else:
                    raise ProtocolError('Unknown relay message')
        except ProtocolError:
            # A broken lobby message or relay frame ends the session, as it ends a plain connection.
            if session is not None:
                self.end(session)
                session = None
        except (EOFError, OSError):
            pass
        finally:
            if session is not None:
                session.detach(wire)
            wire.close()
