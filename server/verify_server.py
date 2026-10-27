"""Exercise TLS, four-player room limits and an authenticated relay round trip."""
import asyncio
import json
import os
from pathlib import Path
import ssl
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / 'Azeroth Survivors Together'
STATE = ROOT / 'server/state'
os.environ['SSL_CERT_FILE'] = str(STATE / 'server-cert.pem')
sys.path[:0] = [str(GAME), str(GAME / 'reconstruction')]
CONTEXT = ssl.create_default_context(cafile=str(STATE / 'server-cert.pem'))


def request(path, data=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request('https://127.0.0.1:47770' + path,
        data=json.dumps(data).encode() if data is not None else None, headers=headers)
    with urllib.request.urlopen(req, context=CONTEXT, timeout=10) as response:
        return json.load(response)


async def relay_check(room, host, guest):
    from relay.client import connect
    a, b = await asyncio.gather(
        connect('127.0.0.1', 47771, dict(room=room, token=host), 2),
        connect('127.0.0.1', 47771, dict(room=room, token=guest), 1))
    try:
        a[1].write(b'host-to-guest')
        await a[1].drain()
        assert await asyncio.wait_for(b[0].readexactly(13), 5) == b'host-to-guest'
        b[1].write(b'guest-to-host')
        await b[1].drain()
        assert await asyncio.wait_for(a[0].readexactly(13), 5) == b'guest-to-host'
    finally:
        for _, writer in (a, b):
            writer.close()
        await asyncio.gather(a[1].wait_closed(), b[1].wait_closed(), return_exceptions=True)
    reader, writer = await asyncio.open_connection('127.0.0.1', 47771, ssl=CONTEXT)
    try:
        writer.write(b'{"version":1,"room":"bad","token":"bad","peer":1}\n')
        await writer.drain()
        assert await asyncio.wait_for(reader.read(100), 5) != b'{"paired":true}\n'
    finally:
        writer.close()
        await writer.wait_closed()


def main():
    assert isinstance(request('/rooms')['rooms'], list)
    host = request('/create', dict(name='Server verification', player='Test host', private=True,
        build='0' * 64, region='eu', version='verification'))
    room = host['room']['id']
    try:
        guests = [request('/join', dict(room=room, player=f'Test guest {i}', build='0' * 64,
            invite=host['room']['invite'])) for i in range(1, 4)]
        assert len(guests[-1]['room']['players']) == 4
        try:
            request('/join', dict(room=room, player='Fifth player', build='0' * 64,
                invite=host['room']['invite']))
            raise AssertionError('A fifth player was accepted')
        except urllib.error.HTTPError as error:
            assert error.code == 400 and json.load(error)['code'] == 'started_or_full'
        try:
            request('/poll', dict(room=room))
            raise AssertionError('Anonymous room polling was accepted')
        except urllib.error.HTTPError as error:
            assert error.code == 400
        asyncio.run(relay_check(room, host['token'], guests[0]['token']))
        print('PASS: verified HTTPS, four-player capacity, fifth-player rejection, membership authentication, '
              'two-way relay traffic, invalid relay credential rejection')
    finally:
        request('/action', dict(room=room, action='leave', revision=0), host['token'])


if __name__ == '__main__':
    main()
