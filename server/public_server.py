"""Run the ASR co-op lobby and update channel on this PC."""
import argparse
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import re
import shutil
import socket
import ssl
import threading

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'server/state'
CONFIG = STATE / 'config.json'


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
            raise ValueError('Endpoint changed: stop the server and archive server/state before reconfiguring')
        return
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
    CONFIG.write_text(json.dumps(dict(host=host, lan=lan, directory_port=47770), indent=2))
    print(f'Configured https://{host}:47770', flush=True)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 1024
    # On Windows SO_REUSEADDR would let a second server share the port and take part of the connections.
    allow_reuse_address = not hasattr(socket, 'SO_EXCLUSIVEADDRUSE')

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def handler(native):
    from native_websocket import ProtocolError

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)  # the lobby's WebSocket upgrade sets its own timeout

        def log_message(self, *_):
            pass  # never log room codes or passwords

        def reply(self, status, value):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/coop/lobby/':
                try:
                    native.serve(self)
                except ProtocolError:
                    self.reply(400, dict(error='Invalid desktop lobby connection'))
                return
            relative = self.path.removeprefix('/launcher/') if self.path.startswith('/launcher/') else None
            # Launchers up to 0.1.4 still update from here; newer ones use GitHub Releases.
            if relative in ('latest-envelope.json', 'ASR.exe') or re.fullmatch(r'releases/[0-9a-f]{64}\.zip', relative or ''):
                path = STATE / 'updates' / relative
                try:
                    with path.open('rb') as source:
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json' if relative.endswith('.json') else 'application/octet-stream')
                        self.send_header('Content-Length', str(path.stat().st_size))
                        self.send_header('Cache-Control', 'no-store' if relative == 'latest-envelope.json' else 'public, max-age=3600')
                        self.send_header('X-Content-Type-Options', 'nosniff')
                        self.end_headers()
                        shutil.copyfileobj(source, self.wfile)
                except FileNotFoundError:
                    self.reply(404, dict(error='Release not published'))
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
                return
            self.reply(404, dict(error='Not found'))
    return Handler


def serve():
    from native_lobby import Lobby, SUPPORTED_VERSIONS
    import mirror
    config = json.loads(CONFIG.read_text())
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(STATE / 'server-cert.pem', STATE / 'server-key.pem')
    public = Server(('0.0.0.0', config['directory_port']), handler(Lobby()))
    # Handshakes run in each connection's thread, so a slow client cannot stall new connections.
    public.socket = context.wrap_socket(public.socket, server_side=True, do_handshake_on_connect=False)
    threading.Thread(target=mirror.run, args=(STATE,), daemon=True).start()
    print(f"ASR server: https://{config['host']}:{config['directory_port']}", flush=True)
    print(f"In-game co-op lobby: /coop/lobby/ (games {', '.join(SUPPORTED_VERSIONS)}; four players)", flush=True)
    print('Launcher updates: mirrored from GitHub Releases every 10 minutes. Ctrl+C stops the server.', flush=True)
    try:
        public.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        public.server_close()


def play():
    import subprocess
    launcher_root = ROOT / 'downloads/desktop-launcher'
    launcher = launcher_root / 'ASR.exe'
    if not launcher.is_file():
        raise SystemExit('Put ASR.exe in downloads/desktop-launcher first.')
    # This PC reaches its own server over the LAN; other players use the public hostname.
    (launcher_root / 'use-local-server').write_text('1')
    preference = launcher_root / 'desktop-game.txt'
    selected = Path(preference.read_text().strip()) if preference.is_file() else None
    if selected is not None and selected.is_file():
        command = [str(launcher), '--native-session', str(launcher_root), str(selected)]
    else:
        command = [str(launcher), '--root', str(launcher_root), '--no-auto-check']
    subprocess.Popen(command, cwd=launcher_root, creationflags=subprocess.CREATE_NO_WINDOW)
    print('Opened ASR. Use the game\'s Co-op menu to host or join.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['configure', 'serve', 'play'])
    parser.add_argument('--host')
    parser.add_argument('--lan')
    args = parser.parse_args()
    if args.command == 'configure':
        if not args.host or not args.lan:
            parser.error('configure requires --host and --lan')
        configure(args.host, args.lan)
    elif args.command == 'serve':
        serve()
    else:
        play()
