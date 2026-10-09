"""Every Borderlands game the launcher knows: where it lives and which mod SDK it uses.

Games are found through Steam's own records (appmanifest files in every Steam library), then the
Epic Games launcher's install records, then a folder the player picks.
"""

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Game:
    id: str
    name: str
    short: str
    steam_appid: int
    steam_dir: str                  # fallback folder name under steamapps\common
    exes: tuple                     # relative paths, any one marks the folder as this game
    sdk: str | None                 # bl-sdk mod manager repo that supports it
    sdk_hint: tuple = field(default=())   # words that pick the right release zip
    epic_names: tuple = field(default=())

    @property
    def exe_names(self) -> tuple:
        return tuple(Path(e).name for e in self.exes)


GAMES = (
    Game('bl1e', 'Borderlands Game of the Year Enhanced', 'GOTY Enhanced', 729040, 'BorderlandsGOTYEnhanced',
         ('Binaries/Win64/BorderlandsGOTY.exe',), 'willow1-mod-manager', ('bl1-enhanced-sdk.zip', 'enhanced')),
    Game('bl2', 'Borderlands 2', 'Borderlands 2', 49520, 'Borderlands 2',
         ('Binaries/Win32/Borderlands2.exe',), 'willow2-mod-manager', ('bl2', 'willow2')),
    Game('tps', 'Borderlands: The Pre-Sequel', 'The Pre-Sequel', 261640, 'BorderlandsPreSequel',
         ('Binaries/Win32/BorderlandsPreSequel.exe',), 'willow2-mod-manager', ('tps', 'willow2')),
    Game('bl3', 'Borderlands 3', 'Borderlands 3', 397540, 'Borderlands 3',
         ('OakGame/Binaries/Win64/Borderlands3.exe',), 'oak-mod-manager', ('bl3',),
         ('Borderlands 3',)),
    Game('wl', "Tiny Tina's Wonderlands", 'Wonderlands', 1286680, "Tiny Tina's Wonderlands",
         ('OakGame/Binaries/Win64/Wonderlands.exe',), 'oak-mod-manager', ('wl', 'wonderlands'),
         ("Tiny Tina's Wonderlands",)),
)
BY_ID = {g.id: g for g in GAMES}


# --------------------------------------------------------------------------------------------
def _steam_roots() -> list:
    roots = []
    try:
        import winreg
        for hive, key, value in (
            (winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'),
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Valve\Steam', 'InstallPath'),
        ):
            try:
                with winreg.OpenKey(hive, key) as k:
                    roots.append(Path(winreg.QueryValueEx(k, value)[0]))
            except OSError:
                pass
    except ImportError:
        pass
    roots += [Path(r'C:\Program Files (x86)\Steam'), Path(r'C:\Program Files\Steam')]
    return [r for r in _unique(roots) if r.is_dir()]


def _unique(paths) -> list:
    seen, out = set(), []
    for p in paths:
        key = str(p).lower().replace('/', '\\').rstrip('\\')
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _vdf_values(text: str, key: str) -> list:
    return [m.group(1).replace('\\\\', '\\') for m in re.finditer(r'"%s"\s+"([^"]*)"' % re.escape(key), text, re.I)]


def steam_libraries() -> list:
    libs = []
    for root in _steam_roots():
        libs.append(root)
        try:
            text = (root / 'steamapps' / 'libraryfolders.vdf').read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        libs += [Path(p) for p in _vdf_values(text, 'path')]
    return _unique(libs)


def _epic_installs() -> dict:
    out = {}
    base = Path(os.environ.get('PROGRAMDATA', r'C:\ProgramData')) / 'Epic' / 'EpicGamesLauncher' / 'Data' / 'Manifests'
    try:
        items = list(base.glob('*.item'))
    except OSError:
        return out
    for item in items:
        try:
            d = json.loads(item.read_text(encoding='utf-8', errors='replace'))
            out[d.get('DisplayName', '')] = Path(d.get('InstallLocation', ''))
        except (OSError, ValueError):
            continue
    return out


def looks_like(game: Game, folder: Path | None) -> bool:
    return folder is not None and any((folder / e).is_file() for e in game.exes)


def detect(game: Game, libraries=None, epic=None) -> Path | None:
    for lib in libraries if libraries is not None else steam_libraries():
        manifest = lib / 'steamapps' / f'appmanifest_{game.steam_appid}.acf'
        names = []
        if manifest.is_file():
            try:
                names = _vdf_values(manifest.read_text(encoding='utf-8', errors='replace'), 'installdir')
            except OSError:
                pass
        for name in names + [game.steam_dir]:
            folder = lib / 'steamapps' / 'common' / name
            if folder.is_dir() and (manifest.is_file() or looks_like(game, folder)):
                return folder
    epic = epic if epic is not None else _epic_installs()
    for name in game.epic_names:
        folder = epic.get(name)
        if folder and folder.is_dir():
            return folder
    return None


def detect_all() -> dict:
    libs = steam_libraries()
    epic = _epic_installs()
    return {g.id: detect(g, libs, epic) for g in GAMES}


def running(game: Game) -> bool:
    if os.name != 'nt':
        return False
    try:
        out = subprocess.run(['tasklist', '/NH', '/FO', 'CSV'], capture_output=True, text=True,
                             creationflags=0x08000000).stdout.lower()
    except OSError:
        return False
    return any(f'"{n.lower()}"' in out for n in game.exe_names)


def close(game: Game, wait: float = 8.0) -> bool:
    """Closes the game: first politely (like clicking its X), then forcefully if it hasn't exited
    after `wait` seconds (a game stuck on a loading screen ignores the polite request).
    Returns True once it is no longer running."""
    import time
    if os.name != 'nt':
        return True
    flags = 0x08000000      # no console window
    for n in game.exe_names:
        subprocess.run(['taskkill', '/IM', n], capture_output=True, creationflags=flags)
    deadline = time.time() + wait
    while time.time() < deadline:
        if not running(game):
            return True
        time.sleep(0.5)
    for n in game.exe_names:
        subprocess.run(['taskkill', '/F', '/T', '/IM', n], capture_output=True, creationflags=flags)
    for _ in range(20):
        if not running(game):
            return True
        time.sleep(0.5)
    return not running(game)
