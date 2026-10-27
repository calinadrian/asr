"""Get or renew a Let's Encrypt certificate for the game's co-op name through DuckDNS.

The game trusts only public certificate authorities, so it connects to GAME_HOST, which
has a Let's Encrypt certificate; launchers keep the pinned certificate on the same port.
DuckDNS answers every name under hassian.duckdns.org with the same address and TXT
record, which is how the DNS-01 challenge is answered. Needs server/state/duckdns-token.txt.
"""
import base64
import datetime
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.x509.oid import NameOID

GAME_HOST = 'game.hassian.duckdns.org'
DUCKDNS_DOMAIN = 'hassian'
DIRECTORY = 'https://acme-v02.api.letsencrypt.org/directory'
STATE = Path(__file__).resolve().parents[1] / 'server/state'
CERT, KEY = STATE / 'game-cert.pem', STATE / 'game-key.pem'


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def key_file(path):
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    key = ec.generate_private_key(ec.SECP256R1())
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return key


class Acme:
    def __init__(self):
        self.key = key_file(STATE / 'acme-account-key.pem')
        numbers = self.key.public_key().public_numbers()
        self.jwk = dict(crv='P-256', kty='EC', x=b64(numbers.x.to_bytes(32, 'big')), y=b64(numbers.y.to_bytes(32, 'big')))
        self.thumbprint = b64(hashlib.sha256(json.dumps(self.jwk, sort_keys=True, separators=(',', ':')).encode()).digest())
        self.directory = json.loads(urllib.request.urlopen(DIRECTORY, timeout=30).read())
        self.kid = None

    def nonce(self):
        request = urllib.request.Request(self.directory['newNonce'], method='HEAD')
        return urllib.request.urlopen(request, timeout=30).headers['Replay-Nonce']

    def post(self, url, payload):
        protected = dict(alg='ES256', nonce=self.nonce(), url=url, **({'kid': self.kid} if self.kid else {'jwk': self.jwk}))
        body = b64(json.dumps(protected).encode()) + '.' + ('' if payload is None else b64(json.dumps(payload).encode()))
        r, s = decode_dss_signature(self.key.sign(body.encode(), ec.ECDSA(hashes.SHA256())))
        data = json.dumps(dict(protected=body.split('.')[0], payload=body.split('.')[1],
                               signature=b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big')))).encode()
        request = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/jose+json'})
        try:
            response = urllib.request.urlopen(request, timeout=60)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f'ACME {url}: {error.code} {error.read().decode(errors="replace")}') from None
        text = response.read()
        return response.headers, (json.loads(text) if response.headers.get('Content-Type', '').startswith('application/') and text[:1] == b'{' else text)

    def poll(self, url, done=('valid',)):
        for _ in range(60):
            _, status = self.post(url, None)
            if status['status'] in done:
                return status
            if status['status'] == 'invalid':
                raise RuntimeError('Certificate request refused: ' + json.dumps(status))
            time.sleep(3)
        raise RuntimeError('Certificate request timed out')


def duckdns_txt(token, value=None):
    query = dict(domains=DUCKDNS_DOMAIN, token=token, txt=value or 'removed', verbose='true')
    if value is None:
        query['clear'] = 'true'
    answer = urllib.request.urlopen('https://www.duckdns.org/update?' + urllib.parse.urlencode(query), timeout=30).read().decode()
    if not answer.startswith('OK'):
        raise RuntimeError('DuckDNS refused the TXT update; check server/state/duckdns-token.txt')


def visible(value):
    """Ask public DNS whether the challenge TXT record is visible yet."""
    url = 'https://dns.google/resolve?' + urllib.parse.urlencode(dict(name='_acme-challenge.' + GAME_HOST, type='TXT'))
    answers = json.loads(urllib.request.urlopen(url, timeout=30).read()).get('Answer', [])
    return any(value in a.get('data', '') for a in answers)


def issue():
    token = (STATE / 'duckdns-token.txt').read_text().strip()
    acme = Acme()
    headers, _ = acme.post(acme.directory['newAccount'], dict(termsOfServiceAgreed=True))
    acme.kid = headers['Location']
    headers, order = acme.post(acme.directory['newOrder'], dict(identifiers=[dict(type='dns', value=GAME_HOST)]))
    order_url = headers['Location']
    for authorization in order['authorizations']:
        _, auth = acme.post(authorization, None)
        if auth['status'] == 'valid':
            continue
        challenge = next(c for c in auth['challenges'] if c['type'] == 'dns-01')
        value = b64(hashlib.sha256(f"{challenge['token']}.{acme.thumbprint}".encode()).digest())
        duckdns_txt(token, value)
        try:
            for _ in range(40):
                if visible(value):
                    break
                time.sleep(15)
            time.sleep(30)  # let DuckDNS's other name servers catch up
            acme.post(challenge['url'], {})
            acme.poll(authorization)
        finally:
            duckdns_txt(token)
    key = key_file(KEY)
    csr = (x509.CertificateSigningRequestBuilder()
           .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, GAME_HOST)]))
           .add_extension(x509.SubjectAlternativeName([x509.DNSName(GAME_HOST)]), critical=False)
           .sign(key, hashes.SHA256()))
    acme.post(order['finalize'], dict(csr=b64(csr.public_bytes(serialization.Encoding.DER))))
    order = acme.poll(order_url)
    _, chain = acme.post(order['certificate'], None)
    temporary = CERT.with_suffix('.new')
    temporary.write_bytes(chain)
    temporary.replace(CERT)
    return expiry()


def expiry():
    if not CERT.exists():
        return None
    return x509.load_pem_x509_certificate(CERT.read_bytes()).not_valid_after_utc


def needs_renewal():
    ends = expiry()
    return ends is None or ends - datetime.datetime.now(datetime.timezone.utc) < datetime.timedelta(days=30)


if __name__ == '__main__':
    if needs_renewal() or '--force' in sys.argv:
        print(f'Certificate for {GAME_HOST} valid until {issue()}')
    else:
        print(f'Certificate for {GAME_HOST} still valid until {expiry()}')
