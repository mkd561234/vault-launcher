"""Vault Launcher: installs, updates and removes mods for every Borderlands game.

    run.py [launcher]                      the window (default)
    run.py install <mod-id> [--unattended]
    run.py uninstall <mod-id> [--yes] [--restore-backup]
    run.py update [--auto] [--game-pid PID]    launcher self-update from Nexus (mods start this)
    run.py selfinstall [--unattended]      copy this launcher into %LOCALAPPDATA%\\VaultLauncher and
                                           bring installed mods up to the versions it carries
    run.py signin                          connect Nexus Mods for automatic updates
    run.py list
"""

import argparse
import json
import shutil
import sys
import tempfile
import time
import traceback
import urllib.request
import zipfile
from pathlib import Path

from . import catalog, games, nexus, winutil

APP_DIR = Path(__file__).resolve().parents[1]          # ...\app
CHECK_EVERY = 6 * 3600          # automatic update checks at most every 6 hours
WATCH_DOWNLOADS_FOR = 3 * 3600  # free accounts: wait this long for the browser download


# --------------------------------------------------------------------------------------------
def release() -> dict:
    return json.loads((APP_DIR / 'release.json').read_text(encoding='utf-8'))


def user_agent() -> str:
    return f"VaultLauncher/{release()['version']}"


def state_path() -> Path:
    return winutil.data_dir() / 'state.json'


def load_state() -> dict:
    try:
        st = json.loads(state_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        st = {}
    st.setdefault('games', {})
    st.setdefault('mods', {})
    return st


def save_state(st: dict) -> None:
    tmp = state_path().with_suffix('.tmp')
    tmp.write_text(json.dumps(st, indent=1), encoding='utf-8')
    tmp.replace(state_path())


_LOG = None
SAY_HOOKS = []      # the launcher window listens here


def say(msg: str) -> None:
    global _LOG
    for hook in SAY_HOOKS:
        try:
            hook(msg)
        except Exception:  # noqa: BLE001
            pass
    try:
        print(msg, flush=True)
    except (OSError, ValueError, AttributeError):
        pass  # pythonw has no console
    try:
        if _LOG is None:
            _LOG = open(winutil.data_dir() / 'launcher.log', 'a', encoding='utf-8')  # noqa: SIM115
        _LOG.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
        _LOG.flush()
    except OSError:
        pass


def prompt(question: str, default: bool = True) -> bool:
    hint = '[Y/n]' if default else '[y/N]'
    try:
        ans = input(f'{question} {hint} ').strip().lower()
    except EOFError:
        return default
    return default if not ans else ans.startswith('y')


# --------------------------------------------------------------------------------------------
# Games
# --------------------------------------------------------------------------------------------
_DETECTED = None


def detected(refresh: bool = False) -> dict:
    global _DETECTED
    if _DETECTED is None or refresh:
        _DETECTED = games.detect_all()
    return _DETECTED


def game_paths(st: dict) -> dict:
    """game id -> folder (the one the player picked, else what Steam/Epic report), or None."""
    out = {}
    found = detected()
    for g in games.GAMES:
        saved = st['games'].get(g.id, {}).get('path')
        if saved and games.looks_like(g, Path(saved)):
            out[g.id] = Path(saved)
        else:
            out[g.id] = found.get(g.id)
    return out


def set_game_path(game_id: str, folder: str) -> str | None:
    """Returns an error message, or None when the folder was saved."""
    g = games.BY_ID[game_id]
    p = Path(folder)
    if not games.looks_like(g, p):
        # people often pick the Binaries folder or the exe's folder
        for up in (p.parent, p.parent.parent, p.parent.parent.parent):
            if games.looks_like(g, up):
                p = up
                break
        else:
            return f'{folder} does not look like the {g.name} folder (no {g.exe_names[0]} found).'
    st = load_state()
    st['games'].setdefault(game_id, {})['path'] = str(p)
    save_state(st)
    return None


# --------------------------------------------------------------------------------------------
# Mods
# --------------------------------------------------------------------------------------------
def context(mod, st: dict, log=None) -> catalog.Context:
    mst = st['mods'].setdefault(mod.id, {})
    return catalog.Context(mod=mod, paths=game_paths(st), state=mst, say=log or say,
                           save=lambda: save_state(st), user_agent=user_agent())


def mod_status(mod, st: dict) -> dict:
    ctx = context(mod, st)
    k = mod.kind_module
    inst = k.installed(ctx)
    have = ctx.state.get('version') if inst else None
    return {'installed': inst, 'version': have,
            'update': bool(inst and have and nexus.version_tuple(mod.version) > nexus.version_tuple(have)),
            'checks': k.checks(ctx), 'needs': list(k.needs(mod)), 'has_backup': k.has_backup(ctx),
            'was_installed': bool(ctx.state.get('installed_at'))}


def _running_games(mod) -> list:
    return [games.BY_ID[g].short for g in mod.kind_module.needs(mod) if games.running(games.BY_ID[g])]


def install_mod(mod_id: str, log=None, wait_for_games: bool = False) -> None:
    log = log or say
    mod = catalog.by_id(mod_id)
    if mod is None:
        raise RuntimeError(f'There is no mod called {mod_id} in this launcher.')
    while True:
        busy = _running_games(mod)
        if not busy:
            break
        if not wait_for_games:
            raise RuntimeError(f"Close {' and '.join(busy)} first.")
        time.sleep(10)
    st = load_state()
    ctx = context(mod, st, log)
    log(f'Installing {mod.name} {mod.version}')
    try:
        mod.kind_module.install(ctx)
    except PermissionError as ex:
        save_state(st)
        raise RuntimeError(f'Windows blocked writing to the game folder ({ex.filename}). Close the game and any '
                           'program using that folder, then try again.') from ex
    except Exception:
        save_state(st)
        raise
    ctx.state.update({'installed': True, 'version': mod.version, 'installed_at': int(time.time())})
    ctx.state.pop('removed_by_user', None)
    save_state(st)
    log(f'{mod.name} {mod.version} is downloaded and ready to play.')


def uninstall_mod(mod_id: str, restore: bool, log=None) -> None:
    log = log or say
    mod = catalog.by_id(mod_id)
    if mod is None:
        raise RuntimeError(f'There is no mod called {mod_id} in this launcher.')
    busy = _running_games(mod)
    if busy:
        raise RuntimeError(f"Close {' and '.join(busy)} first.")
    st = load_state()
    ctx = context(mod, st, log)
    log(f'Removing {mod.name}')
    try:
        mod.kind_module.uninstall(ctx, restore)
    finally:
        save_state(st)
    ctx.state.pop('version', None)
    ctx.state['removed_by_user'] = True      # never put back automatically
    save_state(st)
    log(f'{mod.name} was removed.' + (' The mod SDK stays in place for other mods.' if mod.kind == 'sdkmod' else ''))


def missing_mods(st: dict | None = None) -> list:
    """Mods that install themselves: every mod in the launcher whose game is on this PC, unless the
    player removed it (removing it is remembered; installing it again by hand undoes that)."""
    st = st or load_state()
    out = []
    for mod in catalog.load():
        try:
            mst = st.get('mods', {}).get(mod.id, {})
            if mst.get('removed_by_user'):
                continue
            s = mod_status(mod, st)
            if s['installed']:
                continue
            if mst.get('installed_at') and not mst.get('installed'):
                continue                      # removed with an older launcher that didn't remember it
            if all(c['ok'] for c in s['checks']):
                out.append(mod)
        except Exception:  # noqa: BLE001
            continue
    return out


def pending_mods(st: dict | None = None) -> list:
    """Mods to install now: newer versions of installed ones, and ones not installed yet."""
    st = st or load_state()
    seen, out = set(), []
    for mod in outdated_mods(st) + missing_mods(st):
        if mod.id not in seen:
            seen.add(mod.id)
            out.append(mod)
    return out


def outdated_mods(st: dict | None = None) -> list:
    st = st or load_state()
    out = []
    for mod in catalog.load():
        try:
            s = mod_status(mod, st)
        except Exception:  # noqa: BLE001
            continue
        if s['update']:
            out.append(mod)
    return out


# --------------------------------------------------------------------------------------------
# Moving over from the Krieg Launcher (1.x), which lived in %LOCALAPPDATA%\KriegTPS
# --------------------------------------------------------------------------------------------
def _old_dir() -> Path:
    return winutil.data_dir().parent / 'KriegTPS'


def migrate() -> bool:
    old = _old_dir()
    old_state = old / 'state.json'
    if not old_state.is_file():
        return False
    try:
        o = json.loads(old_state.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        o = {}
    st = load_state()
    for gid in ('bl2', 'tps'):
        if o.get(gid) and gid not in st['games']:
            st['games'][gid] = {'path': o[gid]}
    if o.get('installed') and 'krieg-tps' not in st['mods']:
        st['mods']['krieg-tps'] = {k: o[k] for k in ('installed', 'version', 'backup', 'installed_at') if k in o}
    # A DLC\Lilac folder the old installer set aside lives in the old folder, which goes away below.
    for mst in st['mods'].values():
        b = Path(mst['backup']) if mst.get('backup') else None
        if b is not None and b.exists() and old.resolve() in b.resolve().parents:
            dst = winutil.data_dir() / 'backup' / b.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(b), str(dst))
                mst['backup'] = str(dst)
            except OSError as ex:
                say(f'could not move the backup {b}: {ex}')
                return False      # keep the old folder so nothing is lost
    for k in ('nexus_key', 'nexus_premium'):
        if o.get(k) and not st.get(k):
            st[k] = o[k]
    save_state(st)
    say('moved settings over from the Krieg Launcher')

    # The installed KriegTPS mod starts its update check from the old folder: point it here.
    mod = catalog.by_id('krieg-tps')
    have = st['mods'].get('krieg-tps', {}).get('version', '0')
    if mod is not None and st['mods'].get('krieg-tps', {}).get('installed') and \
            nexus.version_tuple(mod.version) >= nexus.version_tuple(have):
        tps = game_paths(st).get('tps')
        src = mod.payload / 'mod' / 'KriegTPS'
        if tps is not None and (tps / 'sdk_mods' / 'KriegTPS').is_dir() and not games.running(games.BY_ID['tps']):
            try:
                mod.kind_module._install_mod_files(src, tps)
                st['mods']['krieg-tps']['version'] = mod.version
                save_state(st)
            except OSError as ex:
                say(f'could not refresh the KriegTPS mod files: {ex}')

    # (the old "Krieg Launcher" shortcuts are replaced when the launcher makes its own)
    try:
        old_state.rename(old / 'state.migrated.json')
    except OSError:
        pass
    shutil.rmtree(old, ignore_errors=True)    # python, app and the old window profile
    return True


# --------------------------------------------------------------------------------------------
# Keeping a copy of the launcher, and Nexus updates
# --------------------------------------------------------------------------------------------
EXE_NAME = 'Vault Launcher - THE Borderlands Launcher.exe'
OLD_EXE_NAMES = ('Vault Launcher.exe',)          # what the window exe was called before 2.1.20
BUNDLED_EXE = Path('bin') / 'launcher.exe'      # a copy inside app\ so an update always carries it
LAUNCH_ARGS = []      # --no-window / --url-file, passed on whenever the launcher hands over to another copy


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def install_exe(src: Path) -> None:
    """Keeps the launcher's window exe in %LOCALAPPDATA%\\VaultLauncher, for the shortcuts.
    A running exe can't be overwritten but can be renamed, so the old one is moved aside."""
    if not src.is_file():
        return
    dst = winutil.data_dir() / EXE_NAME
    try:
        if dst.resolve() == src.resolve() or _same_file(src, dst):
            return
    except OSError:
        pass
    old = dst.with_name(EXE_NAME + '.old')
    try:
        old.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        if dst.exists():
            dst.replace(old)
        shutil.copyfile(src, dst)
    except OSError as ex:
        say(f'could not copy {EXE_NAME}: {ex}')
    _remove_old_exes()


def _remove_old_exes() -> None:
    """The exe from before the rename: deleted, or (while it is still running) renamed so the next
    start deletes it."""
    for name in OLD_EXE_NAMES:
        for p in (winutil.data_dir() / name, winutil.data_dir() / (name + '.old')):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                try:
                    p.replace(p.with_name(p.name + '.old'))
                except OSError:
                    pass


def refresh_exe() -> None:
    """After an update made by an older launcher (which only knew the old exe name), put the
    window exe this version carries in place."""
    bundled = APP_DIR / BUNDLED_EXE
    dst = winutil.data_dir() / EXE_NAME
    if bundled.is_file() and not _same_file(bundled, dst):
        install_exe(bundled)
    else:
        _remove_old_exes()


def install_self() -> None:
    """Keeps this launcher in %LOCALAPPDATA%\\VaultLauncher\\app so shortcuts and the updater work
    after the downloaded zip is gone."""
    target = winutil.data_dir() / 'app'
    install_exe(APP_DIR.parent / EXE_NAME if (APP_DIR.parent / EXE_NAME).is_file() else APP_DIR / BUNDLED_EXE)
    if target.resolve() == APP_DIR:
        return
    if target.exists():
        for item in target.iterdir():
            try:
                shutil.rmtree(item) if item.is_dir() else item.unlink()
            except OSError:
                pass
    shutil.copytree(APP_DIR, target, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__'))


def cmd_selfinstall(args) -> int:
    install_self()
    pending = pending_mods()
    done, failed = [], 0
    for mod in pending:
        try:
            install_mod(mod.id, wait_for_games=args.unattended)
            done.append(mod)
        except Exception as ex:  # noqa: BLE001  - one mod failing doesn't stop the others
            failed += 1
            say(f'{mod.name} could not be installed: {ex}')
            if args.unattended:
                winutil.message(f'{mod.name} {mod.version} could not be installed: {ex}', warning=True)
    if args.unattended and done:
        winutil.message('Installed ' + ', '.join(f'{m.name} {m.version}' for m in done) + '.')
    return 1 if failed else 0


def nexus_client(st: dict | None = None):
    rel = release()
    nx = nexus.Nexus(rel['nexus'], rel['version'])
    if st and st.get('nexus_key'):
        try:
            nx.key = winutil.unprotect(st['nexus_key'])
        except OSError:
            pass
    return nx


def cmd_signin(args=None) -> int:
    nx = nexus_client()
    if not nx.configured:
        say('Automatic updates are not set up in this release yet.')
        return 1
    try:
        key = nx.sign_in(winutil.open_url, say)
        user = nx.user()
    except nexus.NexusError as ex:
        say(f'Nexus sign-in failed: {ex}')
        return 1
    st = load_state()
    st['nexus_key'] = winutil.protect(key)
    st['nexus_premium'] = bool(user.get('is_premium'))
    st['nexus_user'] = user.get('name', '')
    save_state(st)
    kind = 'Premium: updates download and install by themselves' if user.get('is_premium') else \
        'free account: when an update is out, Nexus opens and you click download, then it installs itself'
    say(f"Signed in to Nexus Mods as {user.get('name', '?')} ({kind}).")
    return 0


def _download(url: str, dst: Path) -> None:
    tmp = dst.with_suffix(dst.suffix + '.part')
    req = urllib.request.Request(url, headers={'User-Agent': user_agent()})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, 'wb') as f:
        shutil.copyfileobj(r, f)
    tmp.replace(dst)


def _wait_for_browser_download(file_name: str) -> Path | None:
    folder = winutil.downloads_dir()
    stem = Path(file_name).stem.lower()
    deadline = time.time() + WATCH_DOWNLOADS_FOR
    last_size = {}
    while time.time() < deadline:
        try:
            candidates = [p for p in folder.iterdir() if p.suffix.lower() == '.zip' and
                          (p.stem.lower().startswith(stem) or p.name == file_name)]
        except OSError:
            candidates = []
        for p in candidates:
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size and last_size.get(p) == size and zipfile.is_zipfile(p):
                return p
            last_size[p] = size
        time.sleep(5)
    return None


def _install_archive(archive: Path) -> bool:
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(archive) as z:
            z.extractall(tmp)
        runs = list(Path(tmp).rglob('app/run.py'))
        if not runs:
            say(f'{archive.name} does not contain Vault Launcher')
            return False
        cmd = [sys.executable, str(runs[0]), 'selfinstall', '--unattended']
        say('running ' + ' '.join(cmd))
        res = subprocess.run(cmd, creationflags=0x08000000 if winutil.IS_WINDOWS else 0)
        return res.returncode == 0


def _lock():
    lock = winutil.data_dir() / 'update.lock'
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime < WATCH_DOWNLOADS_FOR + 600:
            return None
        lock.write_text(str(time.time()))
        return lock
    except OSError:
        return None


def latest_release(st: dict | None = None) -> dict:
    """What GitHub (or Nexus) has, for display: {'source', 'configured', 'signed_in', 'latest', 'error', 'page'}."""
    st = st if st is not None else load_state()
    if github_repo():
        out = {'source': 'github', 'configured': True, 'signed_in': True, 'latest': None, 'error': None,
               'page': f'https://github.com/{github_repo()}/releases'}
        try:
            g = github_latest()
            out['latest'] = g['version'] if g else None
        except (OSError, ValueError, KeyError) as ex:
            out['error'] = str(ex)
        return out
    nx = nexus_client(st)
    out = {'configured': nx.configured, 'signed_in': bool(st.get('nexus_key')), 'latest': None, 'error': None,
           'page': nx.mod_page if nx.mod_id else None, 'user': st.get('nexus_user')}
    if not (nx.configured and nx.key):
        return out
    try:
        f = nx.latest_main_file()
        out['latest'] = f.get('version') if f else None
    except (nexus.NexusError, OSError) as ex:
        out['error'] = str(ex)
    return out


# --------------------------------------------------------------------------------------------
# Updates dropped into the Downloads folder (no upload anywhere needed)
# --------------------------------------------------------------------------------------------
def _zip_release(path: Path) -> dict | None:
    """release.json of a Vault Launcher zip, or None if the file is something else."""
    try:
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.replace('\\', '/').endswith('app/release.json')]
            if not names or not any(n.endswith('app/run.py') for n in z.namelist()):
                return None
            rel = json.loads(z.read(min(names, key=len)).decode('utf-8'))
            return rel if rel.get('name') == 'Vault Launcher' and rel.get('version') else None
    except (OSError, ValueError, zipfile.BadZipFile, KeyError):
        return None


def _update_folders() -> list:
    """Where new launcher zips are looked for: the player's Downloads, and the folder GitHub
    downloads go to."""
    return [winutil.downloads_dir(), winutil.data_dir() / 'downloads']


def find_local_update():
    """The newest Vault Launcher zip that is newer than this launcher: (path, version)."""
    current = nexus.version_tuple(release()['version'])
    best = None
    files = []
    for folder in _update_folders():
        try:
            files += [p for p in folder.iterdir()
                      if p.is_file() and p.suffix.lower() == '.zip' and p.name.lower().startswith('vaultlauncher')]
        except OSError:
            pass
    for p in files:
        rel = _zip_release(p)
        if rel is None:
            continue
        v = nexus.version_tuple(rel['version'])
        if v > current and (best is None or v > nexus.version_tuple(best[1])):
            best = (p, rel['version'])
    return best


def apply_launcher_zip(archive: Path) -> Path:
    """Puts the launcher from the zip into %LOCALAPPDATA%\\VaultLauncher\\app. Returns its run.py."""
    target = winutil.data_dir() / 'app'
    with tempfile.TemporaryDirectory(dir=winutil.data_dir()) as tmp:
        with zipfile.ZipFile(archive) as z:
            z.extractall(tmp)
        runs = sorted(Path(tmp).rglob('app/run.py'), key=lambda p: len(p.parts))
        if not runs:
            raise RuntimeError(f'{archive.name} does not contain Vault Launcher')
        src = runs[0].parent
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src, target, ignore=shutil.ignore_patterns('__pycache__'))
        install_exe(src.parent / EXE_NAME if (src.parent / EXE_NAME).is_file() else src / BUNDLED_EXE)
    say(f'Vault Launcher updated from {archive.name}')
    own = winutil.data_dir() / 'downloads'
    for old in own.glob('VaultLauncher*.zip') if own.is_dir() else []:
        try:
            old.unlink()      # only our own download folder is tidied, never the player's Downloads
        except OSError:
            pass
    return target / 'run.py'


def install_launcher_zip(archive: Path, auto: bool) -> int:
    """Switches to the launcher in the zip, then lets the NEW launcher bring the installed mods up
    to date. auto: wait for games to close (background); otherwise mods whose game is running
    keep their Update button."""
    import subprocess
    run = apply_launcher_zip(archive)
    cmd = [sys.executable, str(run), 'selfinstall'] + (['--unattended'] if auto else [])
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                         errors='replace', creationflags=0x08000000 if winutil.IS_WINDOWS else 0)
    for line in p.stdout:
        line = line.rstrip()
        if line and not auto:
            for hook in SAY_HOOKS:      # show the new launcher's progress in this window
                try:
                    hook(line)
                except Exception:  # noqa: BLE001
                    pass
    return p.wait()


def local_update(auto: bool) -> int | None:
    """Installs a newer launcher zip from Downloads, then updates installed mods with it.
    Returns None when there is nothing newer."""
    found = find_local_update()
    if found is None:
        return None
    archive, version = found
    lock = _lock()
    if lock is None:
        return 0
    try:
        say(f'found Vault Launcher {version} ({archive.name})')
        return install_launcher_zip(archive, auto)
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------------------------
# GitHub releases: the launcher checks <owner>/<repo>'s latest release for a VaultLauncher zip
# --------------------------------------------------------------------------------------------
GITHUB_EVERY = 120          # automatic GitHub checks at most every 2 minutes (latest.json has no limit)


def github_repo() -> str:
    return (release().get('github') or {}).get('repo', '').strip()


def _github_release(repo: str) -> dict | None:
    """The newest GitHub release that has a VaultLauncher zip attached."""
    import urllib.error
    req = urllib.request.Request(f'https://api.github.com/repos/{repo}/releases/latest',
                                 headers={'User-Agent': user_agent(), 'Accept': 'application/vnd.github+json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            rel = json.load(r)
    except urllib.error.HTTPError as ex:
        if ex.code == 404:          # no releases yet
            return None
        raise
    assets = [a for a in rel.get('assets', [])
              if a.get('name', '').lower().startswith('vaultlauncher') and a['name'].lower().endswith('.zip')]
    if not assets:
        return None
    version = str(rel.get('tag_name') or '').lstrip('vV') or assets[0]['name'][len('VaultLauncher-'):-4]
    return {'version': version, 'url': assets[0]['browser_download_url'], 'name': assets[0]['name'],
            'page': rel.get('html_url')}


def _github_file(repo: str) -> dict | None:
    """latest.json on the main branch: {"version": "x.y.z", "zip": "dist/VaultLauncher-x.y.z.zip"}."""
    import urllib.error
    raw = f'https://raw.githubusercontent.com/{repo}/main/'
    # the ?t= part makes GitHub's file cache hand out the current copy (it can be ~5 minutes old)
    req = urllib.request.Request(raw + f'latest.json?t={int(time.time())}',
                                 headers={'User-Agent': user_agent(), 'Cache-Control': 'no-cache'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
    except urllib.error.HTTPError as ex:
        if ex.code == 404:
            return None
        raise
    if not d.get('version') or not d.get('zip'):
        return None
    return {'version': str(d['version']).lstrip('vV'), 'url': raw + d['zip'].lstrip('/'),
            'name': Path(d['zip']).name, 'page': f'https://github.com/{repo}'}


def github_latest() -> dict | None:
    """{'version', 'url', 'name', 'page'} for the newest version on GitHub (a release, or the
    repository's latest.json, whichever is newer), or None."""
    repo = github_repo()
    if not repo:
        return None
    # latest.json (raw.githubusercontent.com) first: it has no request limit. GitHub's API allows
    # only 60 requests an hour per connection, which friends checking a lot could use up
    # ("HTTP Error 403: rate limit exceeded"). The API is only the fallback.
    errors, found = [], []
    for source in (_github_file, _github_release):
        try:
            x = source(repo)
            if x:
                found.append(x)
        except (OSError, ValueError) as ex:   # e.g. the API's hourly limit: the file is enough
            errors.append(ex)
    if not found:
        if errors:
            raise errors[0]
        return None
    return max(found, key=lambda x: nexus.version_tuple(x['version']))


def github_fetch(auto: bool, raise_errors: bool = False) -> Path | None:
    """Downloads a newer release from GitHub into %LOCALAPPDATA%\\VaultLauncher\\downloads.
    Returns the zip, or None when there is nothing newer (or GitHub can't be reached)."""
    if not github_repo():
        return None
    st = load_state()
    if auto and time.time() - st.get('gh_last_check', 0) < GITHUB_EVERY:
        return None
    try:
        latest = github_latest()
    except (OSError, ValueError) as ex:
        say(f'GitHub update check failed: {ex}')
        if raise_errors:
            raise
        return None
    st = load_state()
    st['gh_last_check'] = int(time.time())
    st['gh_latest'] = latest['version'] if latest else None
    save_state(st)
    if not latest or nexus.version_tuple(latest['version']) <= nexus.version_tuple(release()['version']):
        return None
    folder = winutil.data_dir() / 'downloads'
    folder.mkdir(exist_ok=True)
    dst = folder / latest['name']
    if not (dst.is_file() and _zip_release(dst)):
        say(f"downloading Vault Launcher {latest['version']} from GitHub")
        try:
            _download(latest['url'], dst)
        except (OSError, ValueError) as ex:
            dst.unlink(missing_ok=True)
            say(f'GitHub download failed: {ex}')
            if raise_errors:
                raise
            return None
    if _zip_release(dst) is None:
        dst.unlink(missing_ok=True)
        say('the GitHub download was not a Vault Launcher zip')
        if raise_errors:
            raise ValueError('the download from GitHub was not a Vault Launcher zip')
        return None
    return dst


def cmd_update(args) -> int:
    github_fetch(args.auto)          # a newer release lands where local_update looks
    local = local_update(args.auto)
    if local is not None:
        return local
    if github_repo():
        if not args.auto:
            winutil.message(f"Vault Launcher is up to date (version {release()['version']}).")
        return 0
    rel = release()
    st = load_state()
    auto = args.auto
    nx = nexus_client(st)
    if not nx.configured:
        if not auto:
            winutil.message('Automatic updates are not set up in this release yet.')
        return 0
    if auto and time.time() - st.get('last_check', 0) < CHECK_EVERY and not st.get('pending'):
        return 0
    if not nx.key:
        if auto:
            return 0
        if cmd_signin(args) != 0:
            return 1
        st = load_state()
        nx = nexus_client(st)
    lock = _lock()
    if lock is None:
        return 0  # another updater is already running
    try:
        try:
            latest = nx.latest_main_file()
        except (nexus.NexusError, OSError) as ex:
            say(f'update check failed: {ex}')
            if 'expired' in str(ex):
                st.pop('nexus_key', None)
                save_state(st)
            if not auto:
                winutil.message(f'Could not check for updates: {ex}', warning=True)
            return 1
        st['last_check'] = int(time.time())
        save_state(st)
        current = rel['version']
        if not latest or nexus.version_tuple(latest.get('version', '0')) <= nexus.version_tuple(current):
            say(f'up to date ({current})')
            if not auto:
                winutil.message(f'Vault Launcher is up to date (version {current}).')
            return 0
        new_ver = latest.get('version')
        say(f'update available: {current} -> {new_ver} ({latest.get("file_name")})')
        downloads = winutil.data_dir() / 'downloads'
        downloads.mkdir(exist_ok=True)
        archive = downloads / latest['file_name']
        if not archive.is_file():
            premium = False
            try:
                premium = bool(nx.user().get('is_premium'))
            except nexus.NexusError:
                pass
            if premium:
                say('downloading (Nexus Premium)')
                _download(nx.download_url(latest['file_id']), archive)
            else:
                if st.get('declined') == new_ver and auto:
                    return 0
                if not winutil.ask(f'Vault Launcher {new_ver} is out (you have {current}).\n\nNexus Mods only '
                                   'lets Premium members download automatically, so the download page will open: '
                                   'click "Manual download" / "Slow download" there.\n\nAs soon as the file is '
                                   'in your Downloads folder, the update installs itself (after you close the '
                                   'game). Open the download page now?'):
                    st['declined'] = new_ver
                    save_state(st)
                    return 0
                winutil.open_url(nx.files_page(latest['file_id']))
                found = _wait_for_browser_download(latest['file_name'])
                if found is None:
                    say('gave up waiting for the browser download')
                    return 1
                shutil.copyfile(found, archive)
            st['pending'] = {'version': new_ver, 'archive': str(archive)}
            save_state(st)
        ok = _install_archive(archive)
        st = load_state()
        if ok:
            st.pop('pending', None)
            st.pop('declined', None)
            save_state(st)
            try:
                archive.unlink()
            except OSError:
                pass
            return 0
        winutil.message(f'The Vault Launcher {new_ver} update could not be installed. See '
                        f'{winutil.data_dir()}\\launcher.log, or open Vault Launcher from the new download.',
                        warning=True)
        return 1
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------------------------
def cmd_install(args) -> int:
    try:
        install_mod(args.mod, wait_for_games=args.unattended)
    except Exception as ex:  # noqa: BLE001
        say(f'FAILED: {ex}')
        return 1
    try:
        install_self()
    except OSError as ex:
        say(f'(could not keep a copy for automatic updates: {ex})')
    return 0


def cmd_uninstall(args) -> int:
    mod = catalog.by_id(args.mod)
    if mod is None:
        say(f'There is no mod called {args.mod}.')
        return 1
    if not args.yes and not prompt(f'Remove {mod.name}?', default=False):
        return 0
    try:
        uninstall_mod(args.mod, args.restore_backup)
    except Exception as ex:  # noqa: BLE001
        say(f'FAILED: {ex}')
        return 1
    return 0


def cmd_list(args) -> int:
    st = load_state()
    paths = game_paths(st)
    for g in games.GAMES:
        say(f'{g.short:18} {paths[g.id] or "not found"}')
    for mod in catalog.load():
        s = mod_status(mod, st)
        say(f"{mod.id:18} {mod.version:8} {'installed ' + s['version'] if s['installed'] else 'not installed'}")
    return 0


def main(argv) -> int:
    ap = argparse.ArgumentParser(prog='Vault Launcher')
    sub = ap.add_subparsers(dest='cmd')
    p = sub.add_parser('install')
    p.add_argument('mod')
    p.add_argument('--unattended', action='store_true')
    p = sub.add_parser('uninstall')
    p.add_argument('mod')
    p.add_argument('--yes', action='store_true')
    p.add_argument('--restore-backup', action='store_true')
    p = sub.add_parser('update')
    p.add_argument('--auto', action='store_true')
    p.add_argument('--game-pid', type=int)
    p = sub.add_parser('selfinstall')
    p.add_argument('--unattended', action='store_true')
    sub.add_parser('signin')
    sub.add_parser('list')
    p = sub.add_parser('launcher')
    p.add_argument('--no-window', action='store_true')
    p.add_argument('--url-file')
    args = ap.parse_args(argv or ['launcher'])
    if args.cmd == 'launcher':
        LAUNCH_ARGS[:] = (['--no-window'] if args.no_window else []) + \
            (['--url-file', args.url_file] if args.url_file else [])
    try:
        migrate()
    except Exception:  # noqa: BLE001
        say('moving settings from the Krieg Launcher failed:\n' + traceback.format_exc())
    try:
        if args.cmd in (None, 'launcher'):
            found = find_local_update()
            if found is not None and winutil.IS_WINDOWS:
                # a newer launcher is in Downloads: switch to it before the window opens
                import subprocess
                run = apply_launcher_zip(found[0])
                subprocess.Popen([sys.executable, str(run), 'launcher', *LAUNCH_ARGS], cwd=str(winutil.data_dir()),
                                 creationflags=0x00000008)
                return 0
            from . import launcher
            return launcher.run(open_ui=not getattr(args, 'no_window', False),
                                url_file=getattr(args, 'url_file', None))
        return {'install': cmd_install, 'uninstall': cmd_uninstall, 'update': cmd_update,
                'selfinstall': cmd_selfinstall, 'signin': cmd_signin, 'list': cmd_list}[args.cmd](args)
    except KeyboardInterrupt:
        return 1
    except Exception:  # noqa: BLE001
        say('Unexpected error:\n' + traceback.format_exc())
        return 1
