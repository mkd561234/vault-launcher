"""The mods this launcher ships (app\\catalog\\<mod-id>\\mod.json) and the kinds that install them."""

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path

CATALOG_DIR = Path(__file__).resolve().parents[1] / 'catalog'


@dataclass
class Mod:
    id: str
    name: str
    game: str
    version: str
    kind: str
    summary: str
    details: str
    dir: Path
    icon: str | None = None
    nexus: dict = field(default_factory=dict)

    @property
    def payload(self) -> Path:
        return self.dir / 'payload'

    @property
    def kind_module(self):
        return importlib.import_module(f'vault.kinds.{self.kind}')

    def icon_svg(self) -> str | None:
        if self.icon and (self.dir / self.icon).is_file():
            return (self.dir / self.icon).read_text(encoding='utf-8')
        return None

    @property
    def nexus_page(self) -> str | None:
        if self.nexus.get('mod_id'):
            return f"https://www.nexusmods.com/{self.nexus['game_domain']}/mods/{self.nexus['mod_id']}"
        return None


def load(catalog_dir: Path = CATALOG_DIR) -> list:
    mods = []
    if not catalog_dir.is_dir():
        return mods
    for d in sorted(catalog_dir.iterdir()):
        f = d / 'mod.json'
        if not f.is_file():
            continue
        m = json.loads(f.read_text(encoding='utf-8'))
        mods.append(Mod(id=m['id'], name=m['name'], game=m['game'], version=m['version'], kind=m['kind'],
                        summary=m.get('summary', ''), details=m.get('details', ''), dir=d,
                        icon=m.get('icon'), nexus=m.get('nexus') or {}))
    return mods


def by_id(mod_id: str, catalog_dir: Path = CATALOG_DIR):
    for m in load(catalog_dir):
        if m.id == mod_id:
            return m
    return None


@dataclass
class Context:
    """What a mod kind gets to work with."""
    mod: Mod
    paths: dict          # game id -> Path | None
    state: dict          # this mod's saved state (kinds may add keys)
    say: callable
    save: callable = lambda: None      # writes state.json now (for steps that must survive a crash)
    user_agent: str = 'VaultLauncher'
