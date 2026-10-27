"""Run the installed co-op directory and authenticated relay on this PC."""
import argparse
import asyncio
import datetime
import ipaddress
import json
import os
from pathlib import Path
import ssl
import sys
import threading
import zipfile
import re

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / 'Azeroth Survivors Together'
STATE = ROOT / 'server/state'
CONFIG = STATE / 'config.json'
sys.path[:0] = [str(GAME), str(GAME / 'reconstruction')]


def configure(host, lan):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    if '://' in host or '/' in host or ':' in host:
        raise ValueError('Use a hostname or IPv4 address without a scheme or port')
    ipaddress.IPv4Address(lan)
    STATE.mkdir(parents=True, exist_ok=True)
    if CONFIG.exists():
        current = json.loads(CONFIG.read_text())
        if current['host'] != host or current['lan'] != lan:
            raise ValueError('Endpoint changed: stop the server and archive server/state before reconfiguring; redistribute the new player pack')
    else:
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'ASR co-op')])
        sans = []
        for address in dict.fromkeys([host, lan, '127.0.0.1', 'localhost']):
            try:
                sans.append(x509.IPAddress(ipaddress.ip_address(address)))
            except ValueError:
                sans.append(x509.DNSName(address))
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=5))
                .not_valid_after(now + datetime.timedelta(days=365))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(x509.SubjectAlternativeName(sans), critical=False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .sign(key, hashes.SHA256()))
        (STATE / 'server-key.pem').write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        (STATE / 'server-cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        CONFIG.write_text(json.dumps(dict(host=host, lan=lan, directory_port=47770, relay_port=47771), indent=2))
    pack = ROOT / 'server/player-pack'
    pack.mkdir(exist_ok=True)
    (pack / 'world-of-survive-server.pem').write_bytes((STATE / 'server-cert.pem').read_bytes())
    join = ('@echo off\nsetlocal\ncd /d "%~dp0"\n'
            'if not exist "Start-Coop.cmd" (\n'
            '  echo Extract this player pack into your Azeroth Survivors Together game folder.\n'
            '  pause\n  exit /b 1\n)\n'
            'set "SSL_CERT_FILE=%~dp0world-of-survive-server.pem"\n'
            f'call "%~dp0Start-Coop.cmd" https://{host}:47770\n')
    (pack / 'Join-World-of-Survive.cmd').write_text(join)
    (pack / 'READ-ME.txt').write_text(
        'Install Azeroth Survivors Together from:\n'
        'https://github.com/bymarvin/azeroth-survivors-together/releases/latest\n\n'
        'Extract this pack next to Start-Coop.cmd, then run Join-World-of-Survive.cmd.\n'
        'This launcher trusts the included server certificate only inside the game process; '
        'it does not change Windows certificate settings.\n'
        'All players in a room need the same game version. Maximum 4 per room.\n'
        'Each room needs a player host whose game stays running.\n'
        'Hosts can leave the connection address on auto; the server relay is the fallback.\n')
    with zipfile.ZipFile(STATE / 'World-of-Survive-Player-Pack.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in pack.iterdir():
            archive.write(path, path.name)
    print(f'Configured https://{host}:47770; relay TCP 47771', flush=True)


def serve():
    import lobby_server
    from native_lobby import Lobby
    from native_websocket import ProtocolError
    from relay.server import Relay
    config = json.loads(CONFIG.read_text())
    native = Lobby()
    class PublicHandler(lobby_server.Handler):
        def do_GET(self):
            if self.path == '/coop/lobby/':
                try:
                    native.serve(self)
                except ProtocolError:
                    self.reply(400, dict(error='Invalid desktop lobby connection'))
                return
            if not self.path.startswith('/launcher/'):
                return super().do_GET()
            relative = self.path.removeprefix('/launcher/')
            if relative in ('latest-envelope.json', 'WorldOfSurvive.exe') or re.fullmatch(r'releases/[0-9a-f]{64}\.zip', relative):
                path = STATE / 'updates' / relative
                try:
                    with path.open('rb') as source:
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json' if relative.endswith('.json') else 'application/octet-stream')
                        self.send_header('Content-Length', str(path.stat().st_size))
                        self.send_header('Cache-Control', 'no-store' if relative == 'latest-envelope.json' else 'public, max-age=3600')
                        self.send_header('X-Content-Type-Options', 'nosniff')
                        self.end_headers()
                        import shutil
                        shutil.copyfileobj(source, self.wfile)
                except FileNotFoundError:
                    self.reply(404, dict(error='Release not published'))
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
            else:
                self.reply(404, dict(error='Unknown launcher resource'))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(STATE / 'server-cert.pem', STATE / 'server-key.pem')
    # The relay authenticates through a loopback-only endpoint sharing the same rooms.
    public = lobby_server.server(('0.0.0.0', config['directory_port']),
                                 collected_logs=str(STATE / 'reports'), exclusive=True)
    public.RequestHandlerClass = PublicHandler
    backend = lobby_server.server(('127.0.0.1', 47769),
                                  collected_logs=str(STATE / 'reports'), rooms=public.rooms, exclusive=True)
    public.socket = context.wrap_socket(public.socket, server_side=True)
    threads = [threading.Thread(target=app.serve_forever, daemon=True) for app in (public, backend)]
    for thread in threads:
        thread.start()

    async def run():
        relay = Relay('http://127.0.0.1:47769')
        async with await asyncio.start_server(relay.handle, '0.0.0.0', config['relay_port'],
                ssl=context, ssl_handshake_timeout=5, limit=2048, backlog=64) as listener:
            print(f"Public directory: https://{config['host']}:47770", flush=True)
            print('Desktop in-game lobby: /coop/lobby/ (protocol 3, game 0.120.1; four players)', flush=True)
            print('Authenticated relay: TCP 47771; 4 players per room. Ctrl+C stops the server.', flush=True)
            await listener.serve_forever()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    finally:
        for app in (public, backend):
            app.shutdown()
            app.server_close()


def play_browser():
    import subprocess
    config = json.loads(CONFIG.read_text())
    os.environ['SSL_CERT_FILE'] = str(STATE / 'server-cert.pem')
    # Router forwarding is managed by the operator; use our relay by default.
    os.environ['COOP_UPNP'] = '0'
    # The local PC reaches its own directory over LAN, avoiding router hairpin NAT.
    raise SystemExit(subprocess.call([str(GAME / '.coop-runtime/python.exe'),
        str(GAME / 'coop_launcher.py'), f"https://{config['lan']}:47770"], cwd=GAME))


def play():
    import subprocess
    launcher_root = ROOT / 'downloads/desktop-launcher'
    launcher = launcher_root / 'WorldOfSurvive.exe'
    if not launcher.is_file():
        raise SystemExit('Build the ASR desktop launcher first.')
    # This project entry point is for the operator PC; remote players use the
    # normal launcher and its public hostname setting.
    (launcher_root / 'use-local-server').write_text('1')
    preference = launcher_root / 'desktop-game.txt'
    selected = Path(preference.read_text().strip()) if preference.is_file() else None
    if selected is not None and selected.is_file():
        command = [str(launcher), '--native-session', str(launcher_root), str(selected)]
    else:
        command = [str(launcher), '--root', str(launcher_root), '--no-auto-check']
    subprocess.Popen(command, cwd=launcher_root, creationflags=subprocess.CREATE_NO_WINDOW)
    print('Opened ASR. Use the desktop game\'s Co-op menu to host or join.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['configure', 'serve', 'play', 'play-browser'])
    parser.add_argument('--host')
    parser.add_argument('--lan')
    args = parser.parse_args()
    if args.command == 'configure':
        if not args.host or not args.lan:
            parser.error('configure requires --host and --lan')
        configure(args.host, args.lan)
    elif args.command == 'serve':
        serve()
    elif args.command == 'play-browser':
        play_browser()
    else:
        play()
