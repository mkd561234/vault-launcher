"""Installs the Python SDK mod manager a game needs (all from github.com/bl-sdk):
willow1 (Borderlands GOTY: bl1-sdk.zip, and GOTY Enhanced: bl1-enhanced-sdk.zip), willow2 (BL2, Pre-Sequel), oak (BL3, Wonderlands), oak2 (BL4).

Each release is laid out like the game folder: an sdk_mods folder plus the game's Binaries (or
OakGame\\Binaries) files. If a download is not possible, a willow2 copy from another game the
player already set up is reused (the same release serves both of those games).
"""

import json
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from .games import Game

API = 'https://api.github.com/repos/bl-sdk/{repo}/releases/latest'
PAGE = 'https://github.com/bl-sdk/{repo}/releases'


def installed(game_dir: Path) -> bool:
    if not (game_dir / 'sdk_mods' / 'mods_base.sdkmod').is_file() and not (game_dir / 'sdk_mods' / 'mods_base').is_dir():
        return False
    for plugins in ('Binaries/Plugins', 'Binaries/Win32/Plugins', 'Binaries/Win64/Plugins',
                    'OakGame/Binaries/Win64/Plugins'):
        if (game_dir / plugins / 'pyunrealsdk.dll').is_file():
            return True
    return False


def _copy_tree(src: Path, dst: Path) -> None:
    for item in src.rglob('*'):
        rel = item.relative_to(src)
        # never overwrite the player's SDK settings
        if rel.parts[:2] == ('sdk_mods', 'settings') and (dst / rel).exists():
            continue
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, target)


def _pick_asset(assets: list, game: Game):
    zips = [a for a in assets if a.get('name', '').lower().endswith('.zip')]
    for hint in game.sdk_hint:
        for a in zips:
            name = a['name'].lower()
            # a hint ending in .zip is a whole file name and must match exactly
            if (name == hint) if hint.endswith('.zip') else (hint in name):
                return a
    return zips[0] if len(zips) == 1 else None


MARKER = Path('sdk_mods') / '.vault_sdk.json'     # which release the launcher put in this game folder
_latest_cache: dict = {}                          # repo -> (time, release)
CACHE_SECONDS = 20 * 60


def installed_version(game_dir: Path) -> str | None:
    try:
        return json.loads((game_dir / MARKER).read_text(encoding='utf-8')).get('tag')
    except (OSError, ValueError):
        return None


def latest_release(game: Game, ua: str) -> dict:
    import time
    hit = _latest_cache.get(game.sdk)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    req = urllib.request.Request(API.format(repo=game.sdk), headers={'User-Agent': ua,
                                                                     'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        release = json.load(r)
    _latest_cache[game.sdk] = (time.time(), release)
    return release


def _install_release(game: Game, game_dir: Path, release: dict, ua: str, say) -> bool:
    asset = _pick_asset(release.get('assets', []), game)
    if asset is None:
        return False
    say(f"  downloading {game.sdk} {release.get('tag_name', '')} ({asset['name']})")
    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / asset['name']
        req = urllib.request.Request(asset['browser_download_url'], headers={'User-Agent': ua})
        with urllib.request.urlopen(req, timeout=180) as r, open(zpath, 'wb') as f:
            shutil.copyfileobj(r, f)
        out = Path(tmp) / 'x'
        with zipfile.ZipFile(zpath) as z:
            z.extractall(out)
        roots = [out] + sorted((p for p in out.rglob('*') if p.is_dir()), key=lambda p: len(p.parts))
        for root in roots:
            if (root / 'sdk_mods').is_dir():
                _copy_tree(root, game_dir)
                if not installed(game_dir):
                    return False
                (game_dir / MARKER).write_text(json.dumps({'repo': game.sdk, 'tag': release.get('tag_name'),
                                                           'asset': asset['name']}), encoding='utf-8')
                return True
    return False


def _from_github(game: Game, game_dir: Path, ua: str, say) -> bool:
    return _install_release(game, game_dir, latest_release(game, ua), ua, say)


def update(game: Game, game_dir: Path, ua: str, say) -> str | None:
    """Brings an installed SDK up to bl-sdk's latest release. Returns the new version, or None
    when it was already current. Mods and the SDK's settings are left alone."""
    if not game.sdk or not installed(game_dir):
        return None
    release = latest_release(game, ua)
    tag = release.get('tag_name')
    if not tag or tag == installed_version(game_dir):
        return None
    say(f'Updating the mod SDK for {game.short} to {tag}')
    if not _install_release(game, game_dir, release, ua, say):
        raise RuntimeError(f'the {tag} release has no download for {game.short}')
    return tag


def _from_sibling(game: Game, game_dir: Path, others: dict, say) -> bool:
    if game.sdk != 'willow2-mod-manager':
        return False
    for other_id, other_dir in others.items():
        if other_id == game.id or other_dir is None or not installed(other_dir):
            continue
        if not (other_dir / 'Binaries/Win32/ddraw.dll').is_file():
            continue
        say(f'  copying the mod SDK from {other_dir.name}')
        (game_dir / 'Binaries/Win32').mkdir(parents=True, exist_ok=True)
        shutil.copyfile(other_dir / 'Binaries/Win32/ddraw.dll', game_dir / 'Binaries/Win32/ddraw.dll')
        _copy_tree(other_dir / 'Binaries/Win32/Plugins', game_dir / 'Binaries/Win32/Plugins')
        log = game_dir / 'Binaries/Win32/Plugins/unrealsdk.log'
        if log.exists():
            log.unlink()
        (game_dir / 'sdk_mods').mkdir(exist_ok=True)
        for item in (other_dir / 'sdk_mods').iterdir():
            if item.is_file() and (item.suffix == '.sdkmod' or item.name == '__main__.py'):
                shutil.copyfile(item, game_dir / 'sdk_mods' / item.name)
        if (other_dir / 'sdk_mods' / '.stubs').is_dir():
            _copy_tree(other_dir / 'sdk_mods' / '.stubs', game_dir / 'sdk_mods' / '.stubs')
        return installed(game_dir)
    return False


def ensure(game: Game, game_dir: Path, others: dict, ua: str, say) -> None:
    if installed(game_dir):
        try:
            tag = update(game, game_dir, ua, say)
            say(f'  the mod SDK was updated to {tag}' if tag else '  the mod SDK is installed and up to date')
        except Exception as ex:  # noqa: BLE001 - an installed SDK still works
            say(f'  the mod SDK is installed (could not check for a newer one: {ex})')
        return
    if not game.sdk:
        raise RuntimeError(f'There is no Python SDK for {game.name} yet.')
    try:
        if _from_github(game, game_dir, ua, say):
            return
    except Exception as ex:  # noqa: BLE001
        say(f'  could not download the SDK from GitHub ({type(ex).__name__}: {ex})')
    if _from_sibling(game, game_dir, others, say):
        return
    raise RuntimeError(f'The Python SDK could not be installed automatically. Download it from '
                       f'{PAGE.format(repo=game.sdk)}, extract it into the {game.name} folder, then try again.')
