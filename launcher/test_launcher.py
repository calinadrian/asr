"""Test the compiled updater on isolated files through a separate HTTPS fixture."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import ssl
import socket
import struct
import subprocess
import tempfile
import threading
import time
import zipfile

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / 'server'))
from native_lobby import Lobby
native_lobby = Lobby()
STATE = ROOT / 'server/state'
EXE = ROOT / 'downloads/launcher-candidate/WorldOfSurvive.exe'
key = serialization.load_pem_private_key((STATE / 'release-signing-key.pem').read_bytes(), password=None)
routes = {}


def signed_release(sequence, changes=None, unsafe=None, corrupt=False):
    payload = {'WorldOfSurvive.exe': EXE.read_bytes(), 'server-cert.pem': (STATE / 'server-cert.pem').read_bytes(),
               'client/bootstrap.py': (ROOT / 'launcher/client/bootstrap.py').read_bytes(),
               'client/settings.json': (ROOT / 'launcher/client/settings.json').read_bytes()}
    payload.update(changes or {})
    if unsafe:
        payload[unsafe] = b'unsafe'
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path, data in payload.items():
            archive.writestr(path, data)
    archive = stream.getvalue()
    digest = hashlib.sha256(archive).hexdigest()
    manifest = dict(version=f'0.99.{sequence}', sequence=sequence, archive=f'releases/{digest}.zip', size=len(archive),
                    sha256=digest, files=[dict(path=p, size=len(b), sha256=hashlib.sha256(b).hexdigest()) for p, b in payload.items()])
    raw = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
    signature = key.sign(raw, padding.PKCS1v15(), hashes.SHA256())
    envelope = json.dumps(dict(manifest=base64.b64encode(raw).decode(), signature=base64.b64encode(signature).decode())).encode()
    routes.clear()
    routes['/launcher/latest-envelope.json'] = envelope
    routes['/launcher/' + manifest['archive']] = (bytes([archive[0] ^ 1]) + archive[1:]) if corrupt else archive


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == '/coop/lobby/':
            native_lobby.serve(self)
            return
        data = routes.get(self.path)
        self.send_response(200 if data is not None else 404)
        data = data or b'not found'
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


HARNESS = r'''
using System;
using System.IO;
using WorldOfSurvive;
class Harness {
 static int Main(string[] args) {
  System.Net.ServicePointManager.SecurityProtocol=System.Net.SecurityProtocolType.Tls12;
  try {
   if (args[0] == "paths") {
    foreach(string p in new[]{"../escape", "client/../game/save", "client//x", "client/NUL.json", "client/x:stream", "game/characters.txt", "/client/x", "client\\x"})
      if(Update.SafePath(p)) throw new Exception("Accepted unsafe path: " + p);
    if(!Update.SafePath("client/bootstrap.py")) throw new Exception("Rejected client file");
    Update.Pinned=false; Update.BaseUrl="https://github.com/calinadrian/asr/releases/";
    string github=Update.ArchiveUrl(new Release{version="1.2.3",sha256=new string('a',64),archive="releases/"+new string('a',64)+".zip"});
    if(github!="https://github.com/calinadrian/asr/releases/download/v1.2.3/"+new string('a',64)+".zip") throw new Exception("Wrong GitHub asset URL: "+github);
    return 0;
   }
   Update.BaseUrl=args[1]; Update.Pinned=true; string root=args[2]; Directory.CreateDirectory(root);
   if(args[0]=="native-tunnel") {
    using(var tunnel=new NativeTunnel(new Uri(args[1]),"127.0.0.1")) {
     File.WriteAllText(Path.Combine(root,"native-tunnel-url.txt"),tunnel.GameUrl);
     System.Threading.Thread.Sleep(15000);
    }
    return 0;
   }
   if(args[0]=="desktop") {
    using(var form=new Launcher(root,false)) {
     var method=typeof(Launcher).GetMethod("RunGame",System.Reflection.BindingFlags.NonPublic|System.Reflection.BindingFlags.Instance);
     ((System.Threading.Tasks.Task)method.Invoke(form,null)).GetAwaiter().GetResult();
    }
    return 0;
   }
   if(args[0]=="cleanup") {
    foreach(var p in System.Diagnostics.Process.GetProcessesByName("WorldOfSurvive")) {
     try { if(String.Equals(p.MainModule.FileName,Path.Combine(root,"WorldOfSurvive.exe"),StringComparison.OrdinalIgnoreCase)) {
      p.CloseMainWindow(); if(!p.WaitForExit(5000)) p.Kill();
     } } catch(System.ComponentModel.Win32Exception) { }
    }
    return 0;
   }
   if(args[0]=="apply") { Update.Apply(root, File.ReadAllText(Path.Combine(root,"pending-update.txt"))); return 0; }
   if(args[0]=="locked") {
    using(var file=new FileStream(Path.Combine(root, "WorldOfSurvive.exe"),FileMode.Open,FileAccess.ReadWrite,FileShare.None))
     Update.Apply(root,File.ReadAllText(Path.Combine(root,"pending-update.txt")));
    return 0;
   }
   Release result=Update.Stage(root, s=>{}, null);
   if(result!=null && args[0]!="stage") Update.Apply(root,File.ReadAllText(Path.Combine(root,"pending-update.txt")));
   return 0;
  } catch(Exception e) { Console.Error.WriteLine(e.Message); return 10; }
 }
}
'''


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(STATE / 'server-cert.pem', STATE / 'server-key.pem')
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'https://127.0.0.1:{server.server_port}/launcher/'
    test_parent = ROOT / 'downloads/launcher-tests'
    test_parent.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=test_parent) as temporary:
            folder = Path(temporary)
            shutil.copyfile(EXE, folder / EXE.name)
            (folder / 'Harness.cs').write_text(HARNESS)
            compiler = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
            subprocess.run([str(compiler), '/nologo', '/out:' + str(folder / 'Harness.exe'),
                            '/reference:' + str(folder / EXE.name), '/reference:System.Windows.Forms.dll',
                            str(folder / 'Harness.cs')], check=True)
            installation = folder / 'installation'
            save = installation / 'game/coop-lab/personal-native/characters.txt'
            save.parent.mkdir(parents=True)
            save.write_bytes(b'player save must survive\x00\xff')
            save_hash = hashlib.sha256(save.read_bytes()).hexdigest()

            def run(mode, success=True):
                result = subprocess.run([str(folder / 'Harness.exe'), mode, base, str(installation)], capture_output=True, text=True, timeout=30)
                assert (result.returncode == 0) == success, (mode, result.returncode, result.stderr)

            # Exercise the compiled tunnel and the actual HTTP upgrade, rather
            # than only checking the environment passed to a fake game.
            from urllib.parse import urlsplit
            tunnel_root = folder / 'native-tunnel'
            process = subprocess.Popen([str(folder / 'Harness.exe'), 'native-tunnel', base, str(tunnel_root)])
            try:
                url_file = tunnel_root / 'native-tunnel-url.txt'
                deadline = time.monotonic() + 10
                while not url_file.exists() and time.monotonic() < deadline:
                    time.sleep(.05)
                url = urlsplit(url_file.read_text())
                with socket.create_connection((url.hostname, url.port), timeout=5) as connection:
                    key_header = base64.b64encode(os.urandom(16)).decode()
                    connection.sendall((f'GET {url.path} HTTP/1.1\r\nHost: {url.netloc}\r\nConnection: Upgrade\r\n'
                        f'Upgrade: websocket\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key_header}\r\n\r\n').encode())
                    response = b''
                    while b'\r\n\r\n' not in response:
                        response += connection.recv(1)
                    assert response.startswith(b'HTTP/1.1 101 '), response
                    def send_frame(payload):
                        mask = os.urandom(4)
                        connection.sendall(bytes([130, 128 | len(payload)]) + mask + bytes(v ^ mask[i % 4] for i, v in enumerate(payload)))
                    send_frame(bytes.fromhex('010300000007000000302e3132302e310000000001'))
                    send_frame(b'\x02')
                    response = b''
                    while len(response) < 7:
                        chunk = connection.recv(7 - len(response))
                        if not chunk:
                            raise AssertionError('Native tunnel closed before room-list response')
                        response += chunk
                    assert response == b'\x82\x05\x14\x00\x00\x00\x00', response
            finally:
                process.terminate()
                process.wait(timeout=5)
                assert hashlib.sha256(save.read_bytes()).hexdigest() == save_hash

            run('paths')
            native = folder / 'native-game'
            native.mkdir()
            (native / 'Game.cs').write_text('class Game { static void Main() { System.IO.File.WriteAllText("native-started.txt", "desktop"); System.IO.File.WriteAllText("native-server.txt", System.Environment.GetEnvironmentVariable("WOW_ROGUE_COOP_URL") ?? "missing"); System.IO.File.WriteAllText("native-presence.txt", System.Environment.GetEnvironmentVariable("WOW_ROGUE_PRESENCE") ?? "missing"); } }')
            subprocess.run([str(compiler), '/nologo', '/target:winexe', '/out:' + str(native / 'AzerothSurvivors.exe'), str(native / 'Game.cs')], check=True)
            (installation / 'desktop-game.txt').write_text(str(native / 'AzerothSurvivors.exe'))
            run('desktop')
            for _ in range(30):
                if (native / 'native-started.txt').exists():
                    break
                time.sleep(.1)
            assert (native / 'native-started.txt').read_text() == 'desktop'
            assert (native / 'native-server.txt').read_text().startswith('ws://127.0.0.1:')
            assert (native / 'native-presence.txt').read_text() == '0'
            sequence = json.loads((ROOT / 'downloads/launcher-candidate/latest.json').read_bytes())['sequence'] + 100
            signed_release(sequence)
            run('install')
            original = (installation / 'client/bootstrap.py').read_bytes()
            run('install')  # Already-current releases are idempotent.
            envelope = json.loads(routes['/launcher/latest-envelope.json'])
            raw = bytearray(base64.b64decode(envelope['manifest']))
            raw[5] ^= 1
            envelope['manifest'] = base64.b64encode(raw).decode()
            routes['/launcher/latest-envelope.json'] = json.dumps(envelope).encode()
            run('install', success=False)
            signed_release(sequence + 1, corrupt=True)
            run('install', success=False)
            signed_release(sequence + 1, unsafe='client/../../escape.txt')
            run('install', success=False)
            assert not (folder / 'escape.txt').exists()
            signed_release(sequence + 1, {'client/bootstrap.py': original + b'\n# newer verified fixture\n'})
            run('stage')
            pending = Path((installation / 'pending-update.txt').read_text())
            (pending / 'client/bootstrap.py').write_bytes(b'tampered after staging')
            run('apply', success=False)
            assert (installation / 'client/bootstrap.py').read_bytes() == original
            signed_release(sequence + 1, {'client/bootstrap.py': original + b'\n# newer verified fixture\n'})
            run('stage')
            run('locked', success=False)
            assert (installation / 'client/bootstrap.py').read_bytes() == original
            run('apply')
            assert b'newer verified fixture' in (installation / 'client/bootstrap.py').read_bytes()
            signed_release(sequence)
            run('install', success=False)
            # Exercise the actual helper process against a running executable.
            signed_release(sequence + 2, {'client/bootstrap.py': original + b'\n# helper upgrade fixture\n'})
            run('stage')
            pending = Path((installation / 'pending-update.txt').read_text())
            helper = pending / 'update-helper.exe'
            shutil.copyfile(EXE, helper)
            player = subprocess.Popen([str(installation / EXE.name), '--root', str(installation), '--no-auto-check'])
            try:
                time.sleep(.5)
                updater = subprocess.Popen([str(helper), '--apply-update', str(player.pid), str(installation), str(pending)])
                time.sleep(.3)
                assert updater.poll() is None, 'Updater did not wait for the running launcher'
                run('cleanup')
                assert updater.wait(timeout=15) == 0
                assert b'helper upgrade fixture' in (installation / 'client/bootstrap.py').read_bytes()
                assert hashlib.sha256(save.read_bytes()).hexdigest() == save_hash
            finally:
                time.sleep(.3)
                run('cleanup')
            print('PASS: safe paths, authenticated TLS download, signed install, repeat check, signature tampering, '
                  'archive corruption, traversal rejection, staging tampering, locked-file preflight, upgrade, rollback refusal, '
                  'save preservation, real launcher self-update and restart, pinned native TLS tunnel, HTTP/1.1 WebSocket room list, '
                  'default native Play without browser or installer')
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
