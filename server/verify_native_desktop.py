"""Verify two unmodified games against a private copy of the lobby, the way installed games connect.

Each game gets WOW_ROGUE_COOP_URL=wss://game.hassian.duckdns.org:<test port>/coop/lobby/, as ASR-Setup
sets it, and the test lobby presents the real Let's Encrypt certificate for that name. On the server PC
that name must resolve to this machine (the hosts entry in server/README.md). Uses disposable saves and
the game's own scripted menu click; never enters a zone, never touches the public lobby.
"""
from pathlib import Path
import os,sys,ssl,threading,subprocess,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'server'))
from native_lobby import Lobby,string
import acme

class Fixture(Lobby):
 def __init__(self):super().__init__();self.events=[];self.errors=[];self.host=None
 def handle(self,p,m):
  try:
   super().handle(p,m)
   self.events.append((p.peer,m[0],len(m)))
   if m==b'\x02' and p.room is None:
    if self.host is None:
     self.host=p
     super().handle(p,bytes.fromhex('030000000001000000000000000005000000566f7279610106000000656c77796e6e01010000000104'))
    elif p is not self.host and self.host.room is not None:
     super().handle(p,b'\x05'+string(self.host.room.code)+string(''))
  except Exception as e:self.errors.append(str(e));raise
import argparse
import tempfile
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--game',type=Path,required=True)
args=parser.parse_args()
args.game=args.game.resolve(strict=True)
output=Path(tempfile.mkdtemp(prefix='asr-native-party-'))
print('Verification artifacts:',output,flush=True)
lobby=Fixture()
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):lobby.serve(self)
 def log_message(self,*a):pass
server=ThreadingHTTPServer(('0.0.0.0',0),Handler)
context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(acme.CERT,acme.KEY);server.socket=context.wrap_socket(server.socket,server_side=True)
threading.Thread(target=server.serve_forever,daemon=True).start()
url=f'wss://{acme.GAME_HOST}:{server.server_port}/coop/lobby/'
processes=[];logs=[];homes=[]
try:
 for role in ['host','guest']:
  folder=output/role;folder.mkdir(parents=True);(folder/'shots').mkdir()
  env={k:v for k,v in os.environ.items() if not k.startswith('WOW_ROGUE_')};env.update(WOW_ROGUE_COOP_URL=url,WOW_ROGUE_SAVE=str(folder/'characters.txt'),BENILLA_HOME=str(folder/'config'),WOW_NOSOUND='1',WOW_UNATTENDED='1',WOW_ROGUE_PRESENCE='0',WOW_ROGUE_UPDATE='0',WOW_ROGUE_TAPS='444,326',WOW_ROGUE_SHOTS=str(folder/'shots'),WOW_ROGUE_SHOTS_EVERY='10',RUST_LOG='error')
  log=(folder/'game.log').open('w');logs.append(log);homes.append(folder)
  p=subprocess.Popen([str(args.game)],cwd=args.game.parent,env=env,stdout=log,stderr=log);processes.append(p)
  if role=='host':
   end=time.monotonic()+40
   while lobby.host is None and time.monotonic()<end:time.sleep(.2)
 end=time.monotonic()+50
 while time.monotonic()<end:
  text=[(f/'game.log').read_text(errors='replace') for f in homes]
  if len(text)==2 and all('"size":2' in x and ('"state":"hosting"' in x or '"state":"joined"' in x) for x in text):break
  time.sleep(.25)
 print('Lobby events:',lobby.events,flush=True);print('Protocol errors:',lobby.errors,flush=True)
 for f in homes:print(f.name, 'party state recorded in', f/'game.log',flush=True)
 assert all('"size":2' in (f/'game.log').read_text(errors='replace') for f in homes),'Both games must report a two-player party'
 print(f'PASS: two real games joined each other directly over {url}',flush=True)
finally:
 for p in processes:
  if p.poll() is None:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True)
  try:p.wait(timeout=5)
  except subprocess.TimeoutExpired:pass
 for log in logs:log.close()
 server.shutdown();server.server_close()
