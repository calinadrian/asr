"""Connect the installed co-op game to the World of Survive directory."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
settings = json.loads((ROOT / 'client/settings.json').read_text())
GAME = ROOT / 'game'
os.environ['SSL_CERT_FILE'] = str(ROOT / 'server-cert.pem')
target = settings['directory']
# Only an explicit operator setting uses LAN; another player's LAN may use the same addresses.
if (ROOT / 'use-local-server').is_file():
    target = 'https://' + settings['host_lan'] + ':47770'
    os.environ['COOP_UPNP'] = '0'
raise SystemExit(subprocess.call([str(GAME / 'Start-Coop.cmd'), target], cwd=GAME))
