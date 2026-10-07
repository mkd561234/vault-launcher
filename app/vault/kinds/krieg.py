"""Krieg the Psycho for the Pre-Sequel: builds DLC\\Lilac from the player's own Borderlands 2 files,
then adds the SDK and the KriegTPS mod.

Every mod kind offers the same things:
    needs(mod)     -> tuple       game ids whose folders the kind uses (the mod's own game first)
    checks(ctx)    -> list        [{'label', 'ok', 'detail'}]: what must be true before installing
    installed(ctx) -> bool
    install(ctx)                  raises on failure
    uninstall(ctx, restore)       restore: put back what the install moved aside
    has_backup(ctx) -> bool       whether there is something to put back
"""

import shutil
import time
from pathlib import Path

from .. import sdk, winutil
from ..games import BY_ID
from . import krieg_build as build

MOD_FOLDER = 'KriegTPS'
KEEP_LOGS = {'krieg_log.txt', 'krieg_log_prev.txt', 'freeze_log.txt', 'freeze_log_prev.txt'}


def needs(mod) -> tuple:
    return ('tps', 'bl2')


def checks(ctx) -> list:
    bl2, tps = ctx.paths.get('bl2'), ctx.paths.get('tps')
    out = []
    out.append({'label': 'Borderlands 2 installed', 'ok': bool(bl2) and (bl2 / build.BL2_EXE).is_file(),
                'detail': 'Krieg is built from your own Borderlands 2 files.'})
    if out[-1]['ok']:
        problems = build.check_bl2(bl2)
        out.append({'label': 'Psycho Pack DLC for Borderlands 2', 'ok': not problems,
                    'detail': problems[0] if problems else 'Found.'})
    else:
        out.append({'label': 'Psycho Pack DLC for Borderlands 2', 'ok': False,
                    'detail': 'Set the Borderlands 2 folder first.'})
    out.append({'label': 'The Pre-Sequel installed', 'ok': bool(tps) and (tps / build.TPS_EXE).is_file(),
                'detail': ''})
    if out[-1]['ok']:
        name, _ = build.find_tps_licence(tps)
        out.append({'label': 'Any Pre-Sequel DLC', 'ok': name is not None,
                    'detail': f'Using the {name} DLC licence.' if name else build.check_tps(tps)[0]})
    else:
        out.append({'label': 'Any Pre-Sequel DLC', 'ok': False, 'detail': 'Set the Pre-Sequel folder first.'})
    return out


def installed(ctx) -> bool:
    tps = ctx.paths.get('tps')
    return bool(ctx.state.get('installed')) and tps is not None and \
        (tps / 'DLC' / 'Lilac').is_dir() and (tps / 'sdk_mods' / MOD_FOLDER).is_dir()


def _install_mod_files(src: Path, tps: Path) -> None:
    dst = tps / 'sdk_mods' / MOD_FOLDER
    dst.mkdir(parents=True, exist_ok=True)
    for old in dst.iterdir():
        if old.name in KEEP_LOGS:
            continue
        shutil.rmtree(old, ignore_errors=True) if old.is_dir() else old.unlink()
    for f in src.iterdir():
        if f.is_file():
            shutil.copyfile(f, dst / f.name)


def install(ctx) -> None:
    bl2, tps = ctx.paths.get('bl2'), ctx.paths.get('tps')
    failed = [c for c in checks(ctx) if not c['ok']]
    if failed:
        raise RuntimeError('; '.join(f"{c['label']}: {c['detail']}" for c in failed))
    say = ctx.say
    say('Building Krieg from your Borderlands 2 files')
    dlc = tps / 'DLC'
    staging = dlc / 'Lilac.vault_new'
    if staging.exists():
        shutil.rmtree(staging)
    try:
        report = build.build(bl2, tps, ctx.mod.payload, staging, say)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    lilac = dlc / 'Lilac'
    if lilac.exists():
        # Ours if our state says so, or if our mod is next to it (an install the launcher's state
        # doesn't know about, e.g. from the Krieg Launcher or a reset state file).
        if ctx.state.get('installed') or (tps / 'sdk_mods' / MOD_FOLDER).is_dir():
            shutil.rmtree(lilac)
        else:   # a Lilac folder we did not make: keep it
            backup = winutil.data_dir() / 'backup' / f"Lilac_{time.strftime('%Y%m%d_%H%M%S')}"
            backup.parent.mkdir(parents=True, exist_ok=True)
            say(f'  moving your existing DLC\\Lilac folder to {backup}')
            shutil.move(str(lilac), str(backup))
            ctx.state['backup'] = str(backup)
    staging.rename(lilac)
    ctx.state['installed'] = True     # from here on, the Lilac folder is ours
    ctx.save()
    say(f"  DLC folder ready: {report['built']} packages, licence from the {report['licence_from']} DLC")
    if report['skipped_optional']:
        say(f"  skipped {len(report['skipped_optional'])} optional extras (they come from Borderlands 2 DLCs "
            'you do not have: extra heads, skins and class mods)')
    say('Setting up the mod SDK')
    sdk.ensure(BY_ID['tps'], tps, ctx.paths, ctx.user_agent, say)
    say('Copying the KriegTPS mod')
    _install_mod_files(ctx.mod.payload / 'mod' / MOD_FOLDER, tps)


def uninstall(ctx, restore: bool) -> None:
    tps = ctx.paths.get('tps')
    if tps is None:
        raise RuntimeError('The Pre-Sequel folder is not set.')
    lilac = tps / 'DLC' / 'Lilac'
    if lilac.exists() and ctx.state.get('installed'):
        shutil.rmtree(lilac)
        ctx.say('  removed DLC\\Lilac')
    mod = tps / 'sdk_mods' / MOD_FOLDER
    if mod.exists():
        shutil.rmtree(mod)
        ctx.say(f'  removed sdk_mods\\{MOD_FOLDER}')
    backup = ctx.state.get('backup')
    if restore and backup and Path(backup).exists() and not lilac.exists():
        shutil.move(backup, str(lilac))
        ctx.say('  put back your earlier DLC\\Lilac folder')
        ctx.state.pop('backup', None)
    ctx.state['installed'] = False


def has_backup(ctx) -> bool:
    b = ctx.state.get('backup')
    return bool(b) and Path(b).exists()
