"""Vault Launcher's window: Edge in app mode on a private localhost page. The page talks to this
process over a small HTTP API protected by a random token; the process exits shortly after the
window is closed."""

import base64
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import catalog, games, main, sdk, winutil
from .nexus import version_tuple

APP_DIR = main.APP_DIR
ASSETS = APP_DIR / 'assets'
IDLE_EXIT = 25          # seconds without the window before the launcher quits
NO_WINDOW = 0x08000000
SHORTCUT = 'Vault Launcher'
OLD_SHORTCUTS = ('Krieg Launcher',)


# --------------------------------------------------------------------------------------------
# Job runner: one long task at a time, streamed to the window
# --------------------------------------------------------------------------------------------
class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.name = None
        self.target = None          # mod id the job is about
        self.running = False
        self.progress = 0.0
        self.log = []
        self.result = None          # 'ok' | 'failed' | None
        self.question = None        # {'id', 'text', 'yes', 'no'}
        self.notice = None          # {'text', 'warning'}
        self._answer = None
        self._answered = threading.Event()

    def snapshot(self):
        with self.lock:
            return {'name': self.name, 'target': self.target, 'running': self.running,
                    'progress': round(self.progress, 3), 'log': self.log[-400:], 'result': self.result,
                    'question': self.question, 'notice': self.notice}

    def add(self, msg: str):
        with self.lock:
            self.log.append(msg)
            m = re.search(r'packages (\d+)/(\d+)', msg)
            if m:
                self.progress = 0.05 + 0.70 * int(m.group(1)) / int(m.group(2))
            elif 'sound/text/texture' in msg:
                self.progress = max(self.progress, 0.80)
            elif 'texture caches' in msg:
                self.progress = max(self.progress, 0.88)
            elif msg.startswith('Setting up the mod SDK'):
                self.progress = max(self.progress, 0.92)
            elif msg.startswith('Copying'):
                self.progress = max(self.progress, 0.97)

    def ask(self, text: str, yes='Yes', no='No') -> bool:
        with self.lock:
            self._answered.clear()
            self.question = {'id': secrets.token_hex(4), 'text': text, 'yes': yes, 'no': no}
        self._answered.wait()
        with self.lock:
            self.question = None
            return bool(self._answer)

    def answer(self, qid: str, yes: bool):
        with self.lock:
            if self.question and self.question['id'] == qid:
                self._answer = yes
                self._answered.set()

    def tell(self, text: str, warning=False):
        with self.lock:
            self.notice = {'text': text, 'warning': warning}

    def start(self, name: str, fn, target=None) -> bool:
        with self.lock:
            if self.running:
                return False
            self.name, self.target, self.running, self.progress, self.result = name, target, True, 0.02, None
            self.log, self.notice = [], None

        def runner():
            ok = False
            try:
                ok = fn() == 0
            except Exception as ex:  # noqa: BLE001
                self.add(f'{ex}' if isinstance(ex, RuntimeError) else f'Unexpected error: {type(ex).__name__}: {ex}')
                main.say(f'job {name} failed: {type(ex).__name__}: {ex}')
            with self.lock:
                self.running = False
                self.progress = 1.0 if ok else self.progress
                self.result = 'ok' if ok else 'failed'
            _refresh_status(force=True)

        threading.Thread(target=runner, daemon=True).start()
        return True


JOB = Job()
main.SAY_HOOKS.append(JOB.add)
# Inside the launcher, questions and notices appear in the window instead of message boxes.
winutil.ask = lambda text: JOB.ask(text)
winutil.message = lambda text, warning=False: JOB.tell(text, warning)


# --------------------------------------------------------------------------------------------
# What the window shows
# --------------------------------------------------------------------------------------------
_status = {'data': None, 'at': 0.0}
_nexus = {'data': None, 'at': 0.0, 'busy': False}
_icons = {}


def _mod_icon(mod) -> str | None:
    if mod.id not in _icons:
        _icons[mod.id] = mod.icon_svg()
    return _icons[mod.id]


def _store(p: Path | None) -> str | None:
    if p is None:
        return None
    if 'steamapps' in str(p).lower():
        return 'steam'
    if any(str(e).lower().rstrip('\\/') == str(p).lower().rstrip('\\/') for e in games._epic_installs().values()):
        return 'epic'
    return 'folder'


def _compute_status() -> dict:
    st = main.load_state()
    rel = main.release()
    paths = main.game_paths(st)
    mods = catalog.load()
    out_games = []
    for g in games.GAMES:
        p = paths[g.id]
        out_games.append({
            'id': g.id, 'name': g.name, 'short': g.short, 'path': str(p) if p else None,
            'running': bool(p) and games.running(g),
            'store': _store(p),
            'sdk': {'repo': g.sdk, 'installed': bool(p) and sdk.installed(p), 'page': sdk.PAGE.format(repo=g.sdk)},
            'mods': [m.id for m in mods if m.game == g.id],
        })
    out_mods = []
    for m in mods:
        try:
            s = main.mod_status(m, st)
        except Exception as ex:  # noqa: BLE001
            s = {'installed': False, 'version': None, 'update': False, 'needs': [m.game], 'has_backup': False,
                 'checks': [{'label': 'Could not read this mod', 'ok': False, 'detail': f'{type(ex).__name__}: {ex}'}]}
        s['version_installed'] = s.pop('version', None)
        out_mods.append({'id': m.id, 'name': m.name, 'game': m.game, 'version': m.version, 'summary': m.summary,
                         'details': m.details, 'icon': _mod_icon(m), 'page': m.nexus_page, **s})
    repo = main.github_repo()
    return {'launcher': {'version': rel['version'], 'data_dir': str(winutil.data_dir()),
                         'pending': st.get('pending'),
                         'github': {'repo': repo, 'page': f'https://github.com/{repo}/releases',
                                    'latest': st.get('gh_latest')} if repo else None},
            'games': out_games, 'mods': out_mods}


def _refresh_status(force=False) -> dict:
    if force or _status['data'] is None or time.time() - _status['at'] > 4:
        try:
            _status['data'] = _compute_status()
        except Exception as ex:  # noqa: BLE001
            _status['data'] = {'error': f'{type(ex).__name__}: {ex}', 'games': [], 'mods': [],
                               'launcher': {'version': '?'}}
        _status['at'] = time.time()
    return _status['data']


def _refresh_nexus(force=False):
    if _nexus['busy'] or (not force and _nexus['data'] is not None and time.time() - _nexus['at'] < 600):
        return

    def work():
        _nexus['busy'] = True
        try:
            _nexus['data'] = main.latest_release()
        except Exception as ex:  # noqa: BLE001
            _nexus['data'] = {'error': str(ex)}
        _nexus['at'] = time.time()
        _nexus['busy'] = False

    threading.Thread(target=work, daemon=True).start()


# --------------------------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------------------------
class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def act_install(mod_id: str) -> int:
    mod = catalog.by_id(mod_id)
    st = main.load_state()
    failed = [c for c in main.mod_status(mod, st)['checks'] if not c['ok']]
    if failed:
        main.say(f'{mod.name} cannot be downloaded yet: ' + '; '.join(c['label'] for c in failed) + '.')
        return 1
    main.install_mod(mod_id)
    try:
        main.install_self()
    except OSError as ex:
        main.say(f'(could not keep a copy for automatic updates: {ex})')
    ensure_shortcuts()
    return 0


def act_uninstall(mod_id: str, restore: bool) -> int:
    main.uninstall_mod(mod_id, restore)
    return 0


def act_update_mods(mod_ids: list) -> int:
    for mod_id in mod_ids:
        main.install_mod(mod_id)
    return 0


def _auto_update_mods() -> None:
    """Mods this launcher carries a newer version of are updated as soon as it opens
    (unless their game is running; then the Update button waits on the mod)."""
    ready = [m.id for m in main.outdated_mods() if not main._running_games(m)]
    if ready:
        JOB.start('modupdate', lambda: act_update_mods(ready), ready[0])


_restart = {'zip': None, 'version': None, 'at': 0.0, 'url': None, 'handover': False, 'quit': False}
RUN_VERSION = main.release()['version']        # the version of the code running in this process


def _disk_version() -> str:
    try:
        return json.loads((APP_DIR / 'release.json').read_text(encoding='utf-8'))['version']
    except (OSError, ValueError, KeyError):
        return RUN_VERSION


def _github_check() -> None:
    """On open: fetch a newer release from GitHub, then switch to it once nothing is running."""
    try:
        z = main.github_fetch(auto=False)
    except Exception as ex:  # noqa: BLE001
        main.say(f'GitHub update failed: {ex}')
        return
    _refresh_status(force=True)
    if z is None:
        return
    while JOB.running:
        time.sleep(1)
    rel = main._zip_release(z) or {}
    _restart.update({'zip': z, 'version': rel.get('version', ''), 'at': time.time()})


def act_update() -> int:
    if main.github_repo():
        z = main.github_fetch(auto=False)
        _refresh_status(force=True)
        if z is None:
            main.say(f"Vault Launcher {main.release()['version']} is the newest version.")
            return 0
        rel = main._zip_release(z) or {}
        main.say(f"Vault Launcher {rel.get('version', '')} downloaded; switching to it")
        _restart.update({'zip': z, 'version': rel.get('version', ''), 'at': time.time() + 1})
        return 0
    rc = main.cmd_update(_Args(auto=False, game_pid=None))
    _refresh_nexus(force=True)
    return rc


def act_signin() -> int:
    rc = main.cmd_signin(_Args())
    _refresh_nexus(force=True)
    return rc


def play(game_id: str) -> None:
    g = games.BY_ID[game_id]
    p = main.game_paths(main.load_state()).get(game_id)
    if p is None:
        return
    if 'steamapps' in str(p).lower():
        winutil.open_url(f'steam://rungameid/{g.steam_appid}')
        return
    for exe in g.exes:
        if (p / exe).is_file():
            subprocess.Popen([str(p / exe)], cwd=str((p / exe).parent))  # noqa: S603
            return


def open_folder(which: str, game_id: str | None) -> None:
    p = main.game_paths(main.load_state()).get(game_id) if game_id else None
    target = {'logs': winutil.data_dir(), 'game': p, 'mods': p / 'sdk_mods' if p else None}.get(which)
    if target and Path(target).exists():
        winutil.open_url(str(target))


def _powershell(script: str, timeout=600) -> str:
    enc = base64.b64encode(script.encode('utf-16-le')).decode()
    # stdin must be closed: the launcher runs without a console, and PowerShell otherwise waits
    # forever for input on the missing one.
    res = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-STA', '-ExecutionPolicy', 'Bypass',
                          '-EncodedCommand', enc], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                         encoding='utf-8', errors='replace', timeout=timeout, creationflags=NO_WINDOW)
    return res.stdout.strip()


def _ps_quote(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def ensure_shortcuts() -> None:
    """Desktop + Start menu shortcuts to the launcher copy in %LOCALAPPDATA%\\VaultLauncher
    (and the Krieg Launcher ones from 1.x removed)."""
    if not winutil.IS_WINDOWS:
        return
    base = winutil.data_dir()
    pyw = base / 'python' / 'pythonw.exe'
    run = base / 'app' / 'run.py'
    icon = base / 'app' / 'assets' / 'vault.ico'
    if not (pyw.is_file() and run.is_file()):
        return
    exe = base / main.EXE_NAME
    if exe.is_file():          # the launcher's own window
        target, arguments, icon = exe, '', exe
    else:
        target, arguments = pyw, chr(34) + str(run) + chr(34) + ' launcher'
    lines = []
    for folder in ("[Environment]::GetFolderPath('Desktop')", "[Environment]::GetFolderPath('Programs')"):
        for old in OLD_SHORTCUTS:
            lines.append(f"Remove-Item -LiteralPath (Join-Path ({folder}) {_ps_quote(old + '.lnk')}) "
                         "-ErrorAction SilentlyContinue;")
        lines.append(f"$p = Join-Path ({folder}) {_ps_quote(SHORTCUT + '.lnk')};"
                     "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($p);"
                     f"$s.TargetPath = {_ps_quote(target)};"
                     f"$s.Arguments = {_ps_quote(arguments)};"
                     f"$s.WorkingDirectory = {_ps_quote(base)};"
                     f"$s.IconLocation = {_ps_quote(str(icon) + ',0')};"
                     "$s.Description = 'Install, update or remove Borderlands mods';"
                     "$s.Save();")
    try:
        _powershell(''.join(lines), timeout=60)
    except (OSError, subprocess.SubprocessError):
        pass


# --------------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------------
TOKEN = secrets.token_urlsafe(24)
_last_seen = {'t': time.time()}


def _page() -> bytes:
    html = (ASSETS / 'launcher.html').read_text(encoding='utf-8')
    svg = (ASSETS / 'emblem.svg').read_text(encoding='utf-8')
    return html.replace('{{EMBLEM}}', svg).replace('{{TOKEN}}', TOKEN).encode('utf-8')


_picker_lock = threading.Lock()


def _browse_powershell(title: str, start: str | None) -> str | None:
    script = ("Add-Type -AssemblyName System.Windows.Forms;"
              "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
              f"$d.Description = {_ps_quote(title)};"
              "$d.ShowNewFolderButton = $false;"
              + (f"$d.SelectedPath = {_ps_quote(start)};" if start else "") +
              "$w = New-Object System.Windows.Forms.Form -Property @{TopMost=$true; ShowInTaskbar=$false; "
              "Opacity=0; StartPosition='CenterScreen'};"
              "$w.Show(); $w.Activate();"
              "if ($d.ShowDialog($w) -eq 'OK') { Write-Output $d.SelectedPath }; $w.Close()")
    return _powershell(script) or None


def _browse(game_id: str) -> str | None:
    """Lets the player pick a game folder. Returns an error message, or None."""
    g = games.BY_ID[game_id]
    current = main.game_paths(main.load_state()).get(game_id)
    if current is None:
        current = next((lib / 'steamapps' / 'common' for lib in games.steam_libraries()
                        if (lib / 'steamapps' / 'common').is_dir()), None)
    title = f"Choose your {g.name} folder: the one with the {g.exes[0].split('/')[0]} folder inside it."
    try:
        picked = winutil.browse_folder(title, str(current) if current else None)
    except Exception:  # noqa: BLE001
        import traceback
        main.say('folder picker failed, trying the other one:\n' + traceback.format_exc())
        picked = _browse_powershell(title, str(current) if current else None)
    main.say(f'folder picker: {picked or "cancelled"}')
    error = main.set_game_path(game_id, picked) if picked else None
    _refresh_status(force=True)
    return error


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body: bytes, ctype='application/json'):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode())

    def _authed(self) -> bool:
        return secrets.compare_digest(self.headers.get('X-Vault-Token', ''), TOKEN)

    def do_GET(self):  # noqa: N802
        if self.path.split('?')[0] == '/':
            if self.path != f'/?t={TOKEN}':
                return self._send(403, b'forbidden', 'text/plain')
            _window['served'] = time.time()
            return self._send(200, _page(), 'text/html; charset=utf-8')
        if self.path == '/icon.png':
            return self._send(200, (ASSETS / 'vault.png').read_bytes(), 'image/png')
        if not self._authed():
            return self._send(403, b'{}')
        _last_seen['t'] = time.time()
        if self.path == '/api/state':
            _refresh_nexus()
            return self._json({'status': _refresh_status(), 'job': JOB.snapshot(),
                               'restarting': _restart['version'], 'restart_url': _restart['url'],
                               'nexus': _nexus['data'], 'nexus_busy': _nexus['busy']})
        if self.path == '/api/changelog':
            try:
                notes = json.loads((APP_DIR / 'changelog.json').read_text(encoding='utf-8'))
            except (OSError, ValueError):
                notes = []
            return self._json(notes)
        if self.path == '/api/ping':
            return self._json({'ok': True})
        self._send(404, b'{}')

    def do_POST(self):  # noqa: N802
        try:
            self._post()
        except Exception:  # noqa: BLE001 - write it down instead of failing silently
            import traceback
            main.say(f'request {self.path} failed:\n' + traceback.format_exc())
            try:
                self._json({'ok': False, 'error': 'Something went wrong. The details are in the launcher log.'})
            except OSError:
                pass

    def _post(self):
        if not self._authed():
            return self._send(403, b'{}')
        _last_seen['t'] = time.time()
        n = int(self.headers.get('Content-Length') or 0)
        try:
            body = json.loads(self.rfile.read(n) or b'{}')
        except ValueError:
            body = {}
        path = self.path
        mod_id = body.get('mod')
        game_id = body.get('game') if body.get('game') in games.BY_ID else None
        error = None
        if path in ('/api/mod/install', '/api/mod/uninstall'):
            if catalog.by_id(mod_id or '') is None:
                return self._send(400, b'{}')
            if path.endswith('install') and not path.endswith('uninstall'):
                ok = JOB.start('install', lambda: act_install(mod_id), mod_id)
            else:
                ok = JOB.start('uninstall', lambda: act_uninstall(mod_id, bool(body.get('restore'))), mod_id)
        elif path == '/api/update':
            ok = JOB.start('update', act_update)
        elif path == '/api/signin':
            ok = JOB.start('signin', act_signin)
        elif path == '/api/check':
            _refresh_nexus(force=True)
            ok = True
        elif path == '/api/answer':
            JOB.answer(body.get('id', ''), bool(body.get('yes')))
            ok = True
        elif path == '/api/dismiss':
            with JOB.lock:
                JOB.notice = None
                if not JOB.running:
                    JOB.result, JOB.log, JOB.name, JOB.target = None, [], None, None
            ok = True
        elif path == '/api/game/browse' and game_id:
            if not _picker_lock.acquire(blocking=False):      # one picker at a time
                winutil.bring_picker_to_front()
                return self._json({'ok': False, 'error': None, 'busy': True})
            try:
                error = _browse(game_id)
            finally:
                _picker_lock.release()
            ok = error is None
        elif path == '/api/quit':
            _restart['quit'] = True          # a newer launcher has taken over
            ok = True
        elif path == '/api/openurl':
            u = str(body.get('url', ''))
            ok = u.startswith(('https://', 'http://')) and winutil.open_url(u)   # the player's own browser
            if not ok:
                main.say(f'could not open {u!r} in the browser')
        elif path == '/api/picker/front':
            ok = winutil.bring_picker_to_front()
        elif path == '/api/game/play' and game_id:
            play(game_id)
            ok = True
        elif path == '/api/open':
            open_folder(body.get('which', ''), game_id)
            ok = True
        elif path == '/api/rescan':
            main.detected(refresh=True)
            _refresh_status(force=True)
            ok = True
        else:
            return self._send(404, b'{}')
        self._json({'ok': ok, 'error': error})


# --------------------------------------------------------------------------------------------
# Browsers that can show the launcher as its own app window (no tabs or address bar), best first.
# (name, exe, folders under Program Files / Program Files (x86) / LocalAppData)
APP_BROWSERS = (
    ('Edge', 'msedge.exe', (r'Microsoft\Edge\Application',)),
    ('Chrome', 'chrome.exe', (r'Google\Chrome\Application',)),
    ('Brave', 'brave.exe', (r'BraveSoftware\Brave-Browser\Application',)),
    ('Vivaldi', 'vivaldi.exe', (r'Vivaldi\Application',)),
    ('Chromium', 'chrome.exe', (r'Chromium\Application',)),
)
WINDOW_WAIT = 12        # seconds a browser gets to show the page before the next one is tried
_window = {'served': 0.0}


def _program_dirs() -> list:
    """Every Program Files folder. The launcher's Python is 32-bit, and Windows only tells a 32-bit
    program about "Program Files (x86)" unless it asks for the 64-bit one by name."""
    dirs = [os.environ.get(v) for v in ('ProgramW6432', 'ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA')]
    drive = os.environ.get('SystemDrive', 'C:')
    dirs += [drive + '\\Program Files', drive + '\\Program Files (x86)']
    out, seen = [], set()
    for d in dirs:
        if d and d.lower() not in seen:
            seen.add(d.lower())
            out.append(Path(d))
    return out


def _registry_app_path(exe: str) -> str | None:
    try:
        import winreg
    except ImportError:
        return None
    views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)   # both halves of the registry
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in views:
            try:
                with winreg.OpenKey(hive, rf'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}', 0,
                                    winreg.KEY_READ | view) as k:
                    p = winreg.QueryValueEx(k, '')[0].strip('"')
                    if p and Path(p).is_file():
                        return p
            except OSError:
                continue
    return None


def _webview2_runtime() -> str | None:
    """The Edge WebView2 Runtime (part of Windows 11 and most Windows 10 PCs, even when the Edge
    browser itself was removed). Its msedgewebview2.exe can show an app window too."""
    for base in _program_dirs():
        root = base / 'Microsoft' / 'EdgeWebView' / 'Application'
        try:
            versions = sorted((d for d in root.iterdir() if d.is_dir() and d.name[:1].isdigit()),
                              key=lambda d: [int(x) for x in d.name.split('.') if x.isdigit()], reverse=True)
        except OSError:
            continue
        for v in versions:
            exe = v / 'msedgewebview2.exe'
            if exe.is_file():
                return str(exe)
    return None


def _app_browsers() -> list:
    """[(name, exe path)] of installed browsers that support app windows."""
    out, seen = [], set()
    for name, exe, folders in APP_BROWSERS:
        found = _registry_app_path(exe) if name != 'Chromium' else None
        if found and name == 'Chrome' and 'google' not in found.lower():
            found = None
        if not found:
            for base in _program_dirs():
                for folder in folders:
                    candidate = base.joinpath(*folder.split('\\'), exe)
                    if candidate.is_file():
                        found = str(candidate)
                        break
                if found:
                    break
        if found and found.lower() not in seen:
            seen.add(found.lower())
            out.append((name, found))
    wv = _webview2_runtime()
    if wv:
        out.append(('WebView2', wv))
    return out


def _browser_args(name: str, exe: str, url: str, guest: bool) -> list:
    # Each browser gets a private profile folder, so the window never touches the player's own
    # browser profile (bookmarks, sign-in, extensions) and keeps nothing worth keeping.
    profile = winutil.data_dir() / ('launcher-window-guest' if guest else f'launcher-window-{name.lower()}')
    args = [exe, f'--app={url}', '--window-size=1180,760', f'--user-data-dir={profile}', '--no-first-run',
            '--no-default-browser-check', '--disable-sync', '--disable-features=Translate']
    if name in ('Edge', 'WebView2'):
        args.append('--no-service-autorun')
    if guest:
        # Edge never signs Guest windows in to the Microsoft account or shows its sync screens.
        args.append('--guest')
    return args


def _attempts() -> list:
    out = []
    for name, exe in _app_browsers():
        if name == 'Edge':
            out.append((name, exe, True))
        out.append((name, exe, False))
    return out


def open_window(url: str, confirm: bool = True) -> None:
    """Opens the launcher in an app window. confirm: watch that the page actually loads, and try
    the next browser if it doesn't (the plain default browser is the last resort)."""
    for name, exe, guest in _attempts():
        started = time.time()
        try:
            subprocess.Popen(_browser_args(name, exe, url, guest), creationflags=NO_WINDOW)
        except OSError as ex:
            main.say(f'window: {name} would not start ({ex})')
            continue
        if not confirm:
            return
        while time.time() - started < WINDOW_WAIT:
            time.sleep(0.25)
            _last_seen['t'] = max(_last_seen['t'], time.time() + 20)
            if _window['served'] >= started:
                main.say(f"window: {name}{' (guest)' if guest else ''}")
                return
        main.say(f"window: {name}{' (guest)' if guest else ''} did not show the page, trying the next way")
    main.say('window: no app-window browser found, using the default browser')
    winutil.open_url(url)


def _watch_exe_window(url: str) -> None:
    """Vault Launcher.exe should show the page within seconds. If it never does (for example the
    WebView2 engine failed without saying so), open the page the other way so there is a window."""
    started = time.time()
    while time.time() - started < 30:
        time.sleep(1)
        _last_seen['t'] = max(_last_seen['t'], time.time() + 20)
        if _window['served']:
            main.say('window: Vault Launcher.exe')
            return
    main.say('window: Vault Launcher.exe did not show the page, opening it another way')
    open_window(url)


def _tell_window(url_file: str | None, url: str) -> None:
    """Vault Launcher.exe waits for this file to know which page to show in its window."""
    if url_file:
        try:
            tmp = Path(url_file + '.tmp')
            tmp.write_text(url, encoding='ascii')
            tmp.replace(url_file)
        except OSError as ex:
            main.say(f'could not tell the window where the page is: {ex}')


def _already_running(url_file: str | None = None) -> bool:
    info = winutil.data_dir() / 'launcher.json'
    try:
        d = json.loads(info.read_text(encoding='utf-8'))
        if version_tuple(str(d.get('version', '0'))) < version_tuple(RUN_VERSION):
            # An older launcher is still running: ask it to stop (2.1.3 and later) and start fresh,
            # so this window gets the new code.
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{d['port']}/api/quit", data=b'{}', method='POST',
                                             headers={'X-Vault-Token': d['token'], 'Content-Type': 'application/json'})
                urllib.request.urlopen(req, timeout=2).close()
            except (OSError, ValueError):
                pass
            return False
        req = urllib.request.Request(f"http://127.0.0.1:{d['port']}/api/ping", headers={'X-Vault-Token': d['token']})
        with urllib.request.urlopen(req, timeout=2) as r:
            if r.status == 200:
                url = f"http://127.0.0.1:{d['port']}/?t={d['token']}"
                if url_file:
                    _tell_window(url_file, url)      # Vault Launcher.exe shows it in its own window
                else:
                    open_window(url, confirm=False)
                return True
    except (OSError, ValueError, KeyError):
        pass
    return False


def _relaunch_from_data_dir() -> bool:
    """Started from the downloaded zip: keep a copy in %LOCALAPPDATA% and run that one, so the
    shortcuts and automatic updates keep working after the zip is deleted."""
    target = winutil.data_dir() / 'app'
    if not winutil.IS_WINDOWS or target.resolve() == APP_DIR:
        return False
    try:
        mine = main.release()['version']
        theirs = json.loads((target / 'release.json').read_text(encoding='utf-8'))['version'] \
            if (target / 'release.json').is_file() else '0'
        from .nexus import version_tuple
        if version_tuple(mine) >= version_tuple(theirs):
            main.install_self()
        subprocess.Popen([sys.executable, str(target / 'run.py'), 'launcher', *main.LAUNCH_ARGS],
                         cwd=str(winutil.data_dir()), creationflags=0x00000008)
        return True
    except (OSError, ValueError, KeyError):
        return False


def run(open_ui: bool = True, port: int = 0, url_file: str | None = None) -> int:
    if _relaunch_from_data_dir() or _already_running(url_file):
        return 0
    ensure_shortcuts()
    srv = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    port = srv.server_address[1]
    (winutil.data_dir() / 'launcher.json').write_text(
        json.dumps({'port': port, 'token': TOKEN, 'version': RUN_VERSION, 'pid': os.getpid()}), encoding='utf-8')
    url = f'http://127.0.0.1:{port}/?t={TOKEN}'
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _tell_window(url_file, url)
    _last_seen['t'] = time.time() + 20
    if url_file and not open_ui:
        threading.Thread(target=_watch_exe_window, args=(url,), daemon=True).start()
    _refresh_status(force=True)
    _refresh_nexus()
    try:
        _auto_update_mods()
    except Exception as ex:  # noqa: BLE001
        main.say(f'automatic mod update not started: {ex}')
    threading.Thread(target=_github_check, daemon=True).start()
    if open_ui:
        threading.Thread(target=open_window, args=(url,), daemon=True).start()
    else:
        print(url, flush=True)
    _last_seen['t'] = time.time() + 20   # give the window time to open
    while True:
        time.sleep(2)
        if not JOB.running and time.time() - _last_seen['t'] > IDLE_EXIT:
            break
        if _restart['zip'] and not JOB.running and time.time() - _restart['at'] > 3:   # the window has shown the notice
            break
        if _restart['quit']:
            break
        # A newer version was installed while this one kept running (for example from a zip in
        # Downloads): hand the window over, so the page never talks to older code.
        if not JOB.running and not _restart['zip'] and \
                version_tuple(_disk_version()) > version_tuple(RUN_VERSION):
            main.say(f'Vault Launcher {_disk_version()} is installed; switching this window to it')
            _restart.update({'handover': True, 'version': _disk_version(), 'at': time.time()})
            break
    info = winutil.data_dir() / 'launcher.json'
    try:
        info.unlink()
    except OSError:
        pass
    if _restart['zip'] or _restart['handover']:
        _switch_to_new_version(info)
    srv.shutdown()
    return 0


def _switch_to_new_version(info: Path) -> None:
    """Starts the newer launcher without a window of its own and points this window at it (a
    window can't close itself). Either a downloaded release is installed first, or a newer
    version was already put in place (an update from a zip while this one kept running)."""
    try:
        run = main.apply_launcher_zip(_restart['zip']) if _restart['zip'] else APP_DIR / 'run.py'
    except Exception as ex:  # noqa: BLE001
        main.say(f'could not switch to the new version: {ex}')
        return
    subprocess.Popen([sys.executable, str(run), 'launcher', '--no-window'], cwd=str(winutil.data_dir()),
                     creationflags=0x00000008 if winutil.IS_WINDOWS else 0)
    deadline = time.time() + 40
    while time.time() < deadline:
        time.sleep(0.5)
        try:
            d = json.loads(info.read_text(encoding='utf-8'))
            req = urllib.request.Request(f"http://127.0.0.1:{d['port']}/api/ping", headers={'X-Vault-Token': d['token']})
            with urllib.request.urlopen(req, timeout=2):
                pass
        except (OSError, ValueError, KeyError):
            continue
        _restart['url'] = f"http://127.0.0.1:{d['port']}/?t={d['token']}"
        time.sleep(4)          # the window polls once a second and follows the new address
        return
    main.say('the new version did not start in time')
