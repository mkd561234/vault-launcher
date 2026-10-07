"""Nexus Mods: sign-in (SSO) and update lookups for this mod.

Nexus rules for public tools: the tool is registered with Nexus (application slug), players sign in
through Nexus's own SSO page, and every request names the application. Download links come from the
API only for Premium members; everyone else downloads from the mod page (the updater then picks the
file up from their Downloads folder).
"""

import base64
import json
import os
import socket
import ssl
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

API = 'https://api.nexusmods.com/v1'
SSO_HOST = 'sso.nexusmods.com'
SSO_PAGE = 'https://www.nexusmods.com/sso?id={id}&application={slug}'


class NexusError(Exception):
    pass


def version_tuple(v: str) -> tuple:
    parts = []
    for p in str(v).strip().lstrip('vV').replace('-', '.').split('.'):
        num = ''.join(ch for ch in p if ch.isdigit())
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


class Nexus:
    def __init__(self, cfg: dict, app_version: str, api_key: str | None = None):
        self.game = cfg['game_domain']
        self.mod_id = int(cfg.get('mod_id') or 0)
        self.slug = cfg.get('app_slug') or ''
        self.app_name = cfg.get('application_name') or 'VaultLauncher'
        self.app_version = app_version
        self.key = api_key
        self.sso_endpoint = (SSO_HOST, 443, True)

    @property
    def configured(self) -> bool:
        return self.mod_id > 0 and bool(self.slug)

    @property
    def mod_page(self) -> str:
        return f'https://www.nexusmods.com/{self.game}/mods/{self.mod_id}'

    def files_page(self, file_id=None) -> str:
        url = f'{self.mod_page}?tab=files'
        return url + (f'&file_id={file_id}' if file_id else '')

    # ---- REST -------------------------------------------------------------------------------
    def _get(self, path: str):
        if not self.key:
            raise NexusError('not signed in to Nexus Mods')
        req = urllib.request.Request(API + path, headers={
            'apikey': self.key,
            'Application-Name': self.app_name,
            'Application-Version': self.app_version,
            'Accept': 'application/json',
            'User-Agent': f'{self.app_name}/{self.app_version}',
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as ex:
            if ex.code == 401:
                raise NexusError('Nexus sign-in expired') from ex
            if ex.code == 403:
                raise NexusError('forbidden') from ex
            if ex.code == 429:
                raise NexusError('Nexus rate limit reached, try again later') from ex
            raise NexusError(f'Nexus returned HTTP {ex.code}') from ex
        except (urllib.error.URLError, OSError, ValueError) as ex:
            raise NexusError(f'could not reach Nexus Mods ({ex})') from ex

    def user(self) -> dict:
        return self._get('/users/validate.json')

    def latest_main_file(self) -> dict | None:
        data = self._get(f'/games/{self.game}/mods/{self.mod_id}/files.json?category=main')
        files = [f for f in data.get('files', []) if str(f.get('category_name', '')).upper() == 'MAIN']
        if not files:
            return None
        return max(files, key=lambda f: (version_tuple(f.get('version') or f.get('mod_version') or '0'),
                                          f.get('uploaded_timestamp') or 0))

    def download_url(self, file_id: int) -> str:
        links = self._get(f'/games/{self.game}/mods/{self.mod_id}/files/{file_id}/download_link.json')
        if not links:
            raise NexusError('Nexus returned no download link')
        return links[0]['URI']

    # ---- SSO --------------------------------------------------------------------------------
    def sign_in(self, open_url, say, timeout: float = 300.0) -> str:
        """Nexus SSO: connect to the SSO websocket, open the approval page, wait for the key."""
        if not self.slug:
            raise NexusError('this release has no Nexus application slug configured')
        sid = str(uuid.uuid4())
        ws = _WebSocket(*self.sso_endpoint)
        try:
            ws.send_text(json.dumps({'id': sid, 'token': None, 'protocol': 2}))
            opened = False
            deadline = time.time() + timeout
            while time.time() < deadline:
                msg = ws.recv_text(timeout=max(1.0, deadline - time.time()))
                if msg is None:
                    continue
                data = json.loads(msg)
                if not data.get('success'):
                    raise NexusError(f"Nexus sign-in failed: {data.get('error')}")
                payload = data.get('data') or {}
                if payload.get('connection_token') and not opened:
                    opened = True
                    say('  approve "Vault Launcher" in the browser window that opened...')
                    open_url(SSO_PAGE.format(id=sid, slug=urllib.parse.quote(self.slug)))
                if payload.get('api_key'):
                    self.key = payload['api_key']
                    return self.key
            raise NexusError('timed out waiting for Nexus sign-in')
        finally:
            ws.close()


class _WebSocket:
    """Just enough RFC 6455 client for Nexus SSO (text frames, ping/pong, close)."""

    def __init__(self, host: str, port: int = 443, tls: bool = True):
        raw = socket.create_connection((host, port), timeout=30)
        self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host) if tls else raw
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f'GET / HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                           f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n'
                           'User-Agent: VaultLauncher\r\n\r\n').encode())
        resp = b''
        while b'\r\n\r\n' not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise NexusError('Nexus SSO closed the connection')
            resp += chunk
        head, _, self.buf = resp.partition(b'\r\n\r\n')
        if b' 101 ' not in head.split(b'\r\n', 1)[0]:
            raise NexusError('Nexus SSO refused the connection')

    def _send(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        n = len(payload)
        header = bytes([0x80 | opcode])
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack('>H', n)
        else:
            header += bytes([0x80 | 127]) + struct.pack('>Q', n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def send_text(self, text: str) -> None:
        self._send(0x1, text.encode('utf-8'))

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise NexusError('Nexus SSO connection lost')
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv_text(self, timeout: float):
        self.sock.settimeout(timeout)
        try:
            b1, b2 = self._read(2)
        except (socket.timeout, TimeoutError):
            return None
        opcode = b1 & 0x0F
        n = b2 & 0x7F
        if n == 126:
            n, = struct.unpack('>H', self._read(2))
        elif n == 127:
            n, = struct.unpack('>Q', self._read(8))
        mask = self._read(4) if b2 & 0x80 else None
        data = self._read(n)
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        if opcode == 0x9:  # ping
            self._send(0xA, data)
            return None
        if opcode == 0x8:
            raise NexusError('Nexus SSO closed the connection')
        if opcode in (0x1, 0x0):
            return data.decode('utf-8', errors='replace')
        return None

    def close(self) -> None:
        try:
            self._send(0x8, b'')
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
