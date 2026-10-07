"""A plain Python SDK mod: payload\\<folder or .sdkmod> is copied into the game's sdk_mods folder.

mod.json may add "folder": the name it gets in sdk_mods (default: the single item in payload).
"""

import shutil
from pathlib import Path

from .. import sdk
from ..games import BY_ID

KEEP = ('.txt', '.log')     # a mod's own logs survive updates


def needs(mod) -> tuple:
    return (mod.game,)


def _items(ctx) -> list:
    return [p for p in ctx.mod.payload.iterdir() if not p.name.startswith('.')]


def checks(ctx) -> list:
    game = BY_ID[ctx.mod.game]
    folder = ctx.paths.get(game.id)
    return [{'label': f'{game.short} installed', 'ok': folder is not None, 'detail': ''}]


def installed(ctx) -> bool:
    folder = ctx.paths.get(ctx.mod.game)
    if not ctx.state.get('installed') or folder is None:
        return False
    return all((folder / 'sdk_mods' / p.name).exists() for p in _items(ctx))


def install(ctx) -> None:
    game = BY_ID[ctx.mod.game]
    folder = ctx.paths.get(game.id)
    if folder is None:
        raise RuntimeError(f'The {game.short} folder is not set.')
    ctx.say('Setting up the mod SDK')
    sdk.ensure(game, folder, ctx.paths, ctx.user_agent, ctx.say)
    ctx.say(f'Copying {ctx.mod.name}')
    for item in _items(ctx):
        dst = folder / 'sdk_mods' / item.name
        if item.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            for old in dst.iterdir():
                if old.suffix.lower() in KEEP:
                    continue
                shutil.rmtree(old, ignore_errors=True) if old.is_dir() else old.unlink()
            shutil.copytree(item, dst, dirs_exist_ok=True)
        else:
            shutil.copyfile(item, dst)
    ctx.state['installed'] = True
    ctx.state['files'] = [p.name for p in _items(ctx)]


def uninstall(ctx, restore: bool) -> None:
    folder = ctx.paths.get(ctx.mod.game)
    if folder is None:
        raise RuntimeError('The game folder is not set.')
    for name in ctx.state.get('files') or [p.name for p in _items(ctx)]:
        p = folder / 'sdk_mods' / name
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
        ctx.say(f'  removed sdk_mods\\{name}')
    ctx.state['installed'] = False


def has_backup(ctx) -> bool:
    return False
