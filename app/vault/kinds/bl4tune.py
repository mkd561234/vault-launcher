"""Borderlands 4 settings tuned to this PC.

Reads the PC's graphics card (name and video memory), memory, processor and screen, picks a tier,
and writes a block of engine settings into Borderlands 4's Engine.ini:
    Documents\\My Games\\Borderlands 4\\Saved\\Config\\Windows\\Engine.ini
Everything the launcher writes sits between two marker lines, so the player's own lines are never
touched, an update rewrites only that block, and removing the mod takes only that block out (and
deletes the file if the launcher created it and nothing else is in it).

It also writes "Vault Launcher - BL4 settings.txt" next to it: what it found, what it changed, and
which in-game settings to pick for this PC (the game's own menu settings are kept by the game, so
they're recommended rather than forced).
"""

import ctypes
import os
import re
import time
from pathlib import Path

from .. import winutil

BEGIN = '; >>> Vault Launcher: Borderlands 4 tuning (this block is rewritten by the launcher) >>>'
END = '; <<< Vault Launcher: Borderlands 4 tuning <<<'
NOTES_NAME = 'Vault Launcher - BL4 settings.txt'


def needs(mod) -> tuple:
    return (mod.game,)


def _saved_roots() -> list:
    roots = []
    for docs in (winutil.documents_dir(), Path.home() / 'Documents', Path.home() / 'OneDrive' / 'Documents'):
        roots.append(docs / 'My Games' / 'Borderlands 4' / 'Saved')
    local = os.environ.get('LOCALAPPDATA')
    if local:
        roots.append(Path(local) / 'Borderlands 4' / 'Saved')
    out, seen = [], set()
    for root in roots:
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            out.append(root)
    return out


def config_dirs() -> list:
    """Every settings folder the game uses on this PC: Steam/Epic ("Windows") and the Xbox app
    ("WinGDK"). If the game hasn't run yet, the usual Steam/Epic folder."""
    found = []
    for root in _saved_roots():
        for platform in ('Windows', 'WinGDK'):
            d = root / 'Config' / platform
            if d.is_dir():
                found.append(d)
    return found or [config_dir()]


def config_dir() -> Path:
    return winutil.documents_dir() / 'My Games' / 'Borderlands 4' / 'Saved' / 'Config' / 'Windows'


def _engine_ini() -> Path:
    return config_dirs()[0] / 'Engine.ini'


def _read(path: Path) -> tuple:
    """(text, encoding): Unreal writes some ini files as UTF-16."""
    raw = path.read_bytes()
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return raw.decode('utf-16', errors='replace'), 'utf-16'
    if raw[:3] == b'\xef\xbb\xbf':
        return raw[3:].decode('utf-8', errors='replace'), 'utf-8-sig'
    return raw.decode('utf-8', errors='replace'), 'utf-8'


def _write(path: Path, text: str, encoding: str) -> None:
    try:
        import stat
        mode = path.stat().st_mode
        if not mode & stat.S_IWRITE:
            path.chmod(mode | stat.S_IWRITE)      # a read-only Engine.ini (an old tweak guide's advice)
    except OSError:
        pass
    path.write_text(text, encoding=encoding)


def checks(ctx) -> list:
    folder = ctx.paths.get(ctx.mod.game)
    return [{'label': 'Borderlands 4 installed', 'ok': folder is not None,
             'detail': '' if folder is not None else 'The settings are written anyway; they apply once the game is installed.'}]


def installed(ctx) -> bool:
    if not ctx.state.get('installed'):
        return False
    for d in config_dirs():
        try:
            if BEGIN in _read(d / 'Engine.ini')[0]:
                return True
        except OSError:
            continue
    return False


def has_backup(ctx) -> bool:
    return False


# --------------------------------------------------------------------------------------------
# what this PC has
# --------------------------------------------------------------------------------------------
def _reg_values(root, path: str) -> dict:
    import winreg
    out = {}
    try:
        with winreg.OpenKey(root, path) as k:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                out[name] = value
                i += 1
    except OSError:
        pass
    return out


def _gpus() -> list:
    """[(name, vram_bytes)] from the display adapters' driver records."""
    gpus = []
    try:
        import winreg
    except ImportError:
        return gpus
    base = r'SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}'
    for i in range(32):
        vals = _reg_values(winreg.HKEY_LOCAL_MACHINE, f'{base}\\{i:04d}')
        name = vals.get('DriverDesc')
        if not name:
            continue
        vram = 0
        q = vals.get('HardwareInformation.qwMemorySize')
        d = vals.get('HardwareInformation.MemorySize')
        for v in (q, d):
            if isinstance(v, int) and v > vram:
                vram = v
            elif isinstance(v, (bytes, bytearray)) and len(v) in (4, 8):
                vram = max(vram, int.from_bytes(v, 'little'))
        gpus.append((str(name), vram))
    return gpus


def _ram_bytes() -> int:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
    try:
        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(m)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return int(m.ullTotalPhys)
    except Exception:  # noqa: BLE001
        pass
    return 0


def _cpu() -> tuple:
    name = ''
    try:
        import winreg
        name = str(_reg_values(winreg.HKEY_LOCAL_MACHINE,
                               r'HARDWARE\DESCRIPTION\System\CentralProcessor\0').get('ProcessorNameString', '')).strip()
    except ImportError:
        pass
    return name, os.cpu_count() or 4


def _screen() -> tuple:
    """(width, height, refresh rate) of the main screen."""
    try:
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        hdc = user32.GetDC(0)
        try:
            w, h, hz = gdi32.GetDeviceCaps(hdc, 118), gdi32.GetDeviceCaps(hdc, 117), gdi32.GetDeviceCaps(hdc, 116)
        finally:
            user32.ReleaseDC(0, hdc)
        return int(w), int(h), int(hz) if hz > 1 else 60
    except Exception:  # noqa: BLE001
        return 1920, 1080, 60


# Video memory by model, for drivers that don't report it (or report the old 4 GB maximum).
VRAM_BY_NAME = (
    (r'rtx\s*5090', 32), (r'rtx\s*5080', 16), (r'rtx\s*5070\s*ti', 16), (r'rtx\s*5070', 12),
    (r'rtx\s*5060\s*ti', 16), (r'rtx\s*5060', 8), (r'rtx\s*5050', 8),
    (r'rtx\s*4090', 24), (r'rtx\s*4080', 16), (r'rtx\s*4070\s*ti\s*super', 16), (r'rtx\s*4070', 12),
    (r'rtx\s*4060\s*ti', 8), (r'rtx\s*4060', 8), (r'rtx\s*4050', 6),
    (r'rtx\s*3090', 24), (r'rtx\s*3080\s*ti', 12), (r'rtx\s*3080', 10), (r'rtx\s*3070', 8),
    (r'rtx\s*3060\s*ti', 8), (r'rtx\s*3060', 12), (r'rtx\s*3050', 8),
    (r'rtx\s*20[78]0', 8), (r'rtx\s*2060', 6), (r'gtx\s*1650', 4), (r'gtx\s*1660', 6),
    (r'gtx\s*1080', 8), (r'gtx\s*1070', 8), (r'gtx\s*1060', 6), (r'gtx\s*1050', 4),
    (r'rx\s*9070', 16), (r'rx\s*9060', 8), (r'rx\s*79\d\d', 20), (r'rx\s*78\d\d', 16),
    (r'rx\s*77\d\d', 12), (r'rx\s*76\d\d', 8), (r'rx\s*69\d\d', 16), (r'rx\s*68\d\d', 16),
    (r'rx\s*67\d\d', 12), (r'rx\s*66\d\d', 8), (r'rx\s*65\d\d', 4), (r'rx\s*5[67]\d\d', 8),
    (r'rx\s*5[45]\d\d', 4), (r'rx\s*5[89]0', 8), (r'arc\s*b580', 12), (r'arc\s*b570', 10),
    (r'arc\s*a7\d\d', 16), (r'arc\s*a5\d\d', 8), (r'arc\s*a3\d\d', 6),
)


def _vram_from_name(name: str) -> float:
    for pattern, gb in VRAM_BY_NAME:
        if re.search(pattern, name, re.I):
            return float(gb)
    return 0.0


INTEGRATED = re.compile(r'(intel\(r\) (uhd|hd|iris)|intel.*graphics$|radeon\(tm\) graphics|radeon graphics|vega \d+ graphics|'
                        r'microsoft basic|remote display|virtual)', re.I)


def _safe(fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return default


def scan() -> dict:
    """What this PC has. Anything that can't be read gets a middle-of-the-road guess (and is
    marked as a guess), so the mod always has something sensible to write."""
    guessed = []
    gpus = _safe(_gpus, [])
    real = [g for g in gpus if not INTEGRATED.search(g[0])]
    name, vram = max(real or gpus or [('Unknown graphics card', 0)], key=lambda g: g[1])
    vram_gb = round(vram / 2 ** 30, 1)
    by_name = _vram_from_name(name)
    if by_name and (vram_gb < 1 or (abs(vram_gb - 4) < 0.2 and by_name > 4)):
        vram_gb = by_name                      # driver didn't say, or said the old 4 GB maximum
    if vram_gb < 1:
        if real or not gpus:
            vram_gb = 6.0
            guessed.append('video memory')
        else:
            vram_gb = 2.0                       # integrated graphics share system memory
    if not gpus:
        guessed.append('graphics card')
    cpu_name, threads = _safe(_cpu, ('', os.cpu_count() or 8))
    ram_gb = round(_safe(_ram_bytes, 0) / 2 ** 30)
    if ram_gb < 2:
        ram_gb = 16
        guessed.append('memory')
    w, h, hz = _safe(_screen, (1920, 1080, 60))
    if w < 640 or h < 480:
        w, h = 1920, 1080
        guessed.append('screen size')
    if not 24 <= hz <= 500:
        hz = 60
    return {'gpu': name, 'vram_gb': vram_gb, 'integrated': bool(gpus) and not real,
            'ram_gb': ram_gb, 'cpu': cpu_name or 'Unknown processor', 'threads': max(2, int(threads or 8)),
            'width': w, 'height': h, 'hz': hz, 'guessed': guessed}


def _vendor(gpu: str) -> str:
    g = gpu.lower()
    if 'nvidia' in g or 'geforce' in g or 'rtx' in g or 'gtx' in g:
        return 'nvidia'
    if 'radeon' in g or 'amd' in g:
        return 'amd'
    if 'intel' in g or 'arc' in g:
        return 'intel'
    return 'other'


def _frame_gen(gpu: str) -> str:
    g = gpu.lower()
    if re.search(r'rtx\s*(40|50)\d\d', g):
        return 'DLSS Frame Generation'
    if re.search(r'rx\s*(7|9)\d\d\d', g) or re.search(r'rtx\s*(20|30)\d\d', g) or re.search(r'rx\s*6\d\d\d', g):
        return 'FSR Frame Generation'
    return ''


def tier(hw: dict) -> str:
    vram, ram, threads = hw['vram_gb'], hw['ram_gb'], hw['threads']
    if hw['integrated'] or vram < 3.5 or ram < 8 or threads < 4:
        return 'minimum'
    if vram < 5.5 or ram < 12:
        return 'low'
    if vram < 9.5 or ram < 16 or threads < 8:
        return 'medium'
    if vram < 14:
        return 'high'
    return 'ultra'


# --------------------------------------------------------------------------------------------
# what gets written
# --------------------------------------------------------------------------------------------
def settings(hw: dict) -> tuple:
    """([(cvar, value, why)], in-game recommendations)"""
    t = tier(hw)
    vram_mb = int(hw['vram_gb'] * 1024) or 4096
    share = {'minimum': 0.35, 'low': 0.40, 'medium': 0.45, 'high': 0.50, 'ultra': 0.50}[t]
    pool = max(1000, min(8000, int(vram_mb * share) // 100 * 100))
    if hw['ram_gb'] and hw['ram_gb'] < 16:
        pool = min(pool, 2500)
    out = [
        # smoother: fewer shader-compile and texture-streaming hitches
        ('r.PSOPrecaching', 1, 'compile shaders ahead of time (fewer stutters)'),
        ('r.ShaderPipelineCache.Enabled', 1, 'reuse shaders compiled in earlier sessions'),
        ('r.Streaming.LimitPoolSizeToVRAM', 1, 'never stream more textures than the card holds'),
        ('r.Streaming.PoolSize', pool, f'texture memory sized to your {hw["vram_gb"]} GB card'),
        # cleaner picture, and a little faster
        ('r.MotionBlurQuality', 0, 'motion blur off'),
        ('r.DefaultFeature.MotionBlur', 0, 'motion blur off'),
        ('r.SceneColorFringeQuality', 0, 'chromatic aberration off'),
        ('r.FilmGrain', 0, 'film grain off'),
        ('r.LensFlareQuality', 0, 'lens flares off'),
    ]
    if t == 'minimum':
        out += [
            ('r.VolumetricFog.GridPixelSize', 16, 'cheaper volumetric fog (same look, coarser)'),
            ('r.VolumetricFog.GridSizeZ', 48, 'cheaper volumetric fog'),
            ('r.Shadow.Virtual.ResolutionLodBiasDirectional', 2.0, 'much cheaper sun shadows'),
            ('r.Shadow.Virtual.ResolutionLodBiasLocal', 2.0, 'much cheaper lamp shadows'),
            ('foliage.DensityScale', 0.35, 'about a third of the small foliage'),
            ('grass.DensityScale', 0.35, 'about a third of the grass'),
            ('r.ViewDistanceScale', 0.7, 'small objects fade sooner'),
            ('r.SSR.Quality', 1, 'cheaper reflections'),
            ('r.Streaming.MipBias', 1, 'textures one step softer (saves video memory)'),
        ]
    elif t == 'low':
        out += [
            ('r.VolumetricFog.GridPixelSize', 16, 'cheaper volumetric fog (same look, coarser)'),
            ('r.VolumetricFog.GridSizeZ', 64, 'cheaper volumetric fog'),
            ('r.Shadow.Virtual.ResolutionLodBiasDirectional', 1.5, 'cheaper sun shadows'),
            ('r.Shadow.Virtual.ResolutionLodBiasLocal', 1.5, 'cheaper lamp shadows'),
            ('foliage.DensityScale', 0.5, 'half the small foliage'),
            ('grass.DensityScale', 0.5, 'half the grass'),
            ('r.ViewDistanceScale', 0.8, 'small objects fade a bit sooner'),
        ]
    elif t == 'medium':
        out += [
            ('r.VolumetricFog.GridPixelSize', 12, 'cheaper volumetric fog'),
            ('r.Shadow.Virtual.ResolutionLodBiasDirectional', 0.5, 'slightly cheaper sun shadows'),
            ('foliage.DensityScale', 0.75, 'a quarter less small foliage'),
            ('grass.DensityScale', 0.75, 'a quarter less grass'),
        ]
    if hw['threads'] <= 8:
        out.append(('r.ViewDistanceScale', {'minimum': 0.7, 'low': 0.8}.get(t, 0.85),
                    'less for the processor to draw far away'))
    # one value per cvar (the last one wins)
    seen = {}
    for name, value, why in out:
        seen[name] = (value, why)
    rows = [(n, v, w) for n, (v, w) in seen.items()]
    return rows, recommendations(hw, t)


def recommendations(hw: dict, t: str) -> list:
    vendor = _vendor(hw['gpu'])
    upscaler = {'nvidia': 'DLSS', 'amd': 'FSR', 'intel': 'XeSS'}.get(vendor, 'FSR')
    if hw['gpu'].lower().find('gtx') >= 0:
        upscaler = 'FSR'                      # GTX cards have no DLSS
    h = hw['height']
    quality = 'Quality' if h <= 1080 else ('Balanced' if h <= 1600 else 'Performance')
    if t in ('low', 'minimum'):
        quality = 'Performance' if h > 1080 or t == 'minimum' else 'Balanced'
    preset = {'minimum': 'Low', 'low': 'Low', 'medium': 'Medium', 'high': 'High', 'ultra': 'High'}[t]
    rec = [
        f'Graphics preset: {preset}, then change the lines below',
        f'Upscaling: {upscaler}, {quality}',
        f'Frame rate limit: {hw["hz"]} (your screen\'s refresh rate), VSync off',
        'Display mode: Fullscreen',
        'Motion blur: off (the launcher also turns it off)',
        f'Volumetric fog: {"Low" if t in ("minimum", "low", "medium") else "Medium"}',
        f'Volumetric clouds: {"Low" if t in ("minimum", "low", "medium") else "Medium"}',
        'Volumetric cloud shadows: off',
        f'Shadow quality: {"Low" if t in ("minimum", "low") else "Medium"}',
        f'Foliage density: {"Low" if t != "ultra" else "Medium"}',
        f'Texture quality: {"Low" if hw["vram_gb"] < 6 else "Medium" if hw["vram_gb"] < 10 else "High"} (set by your {hw["vram_gb"]} GB of video memory)',
        'HLOD loading range: Medium',
    ]
    fg = _frame_gen(hw['gpu'])
    if t == 'minimum':
        rec.append('Your PC is below what Borderlands 4 asks for: expect 30-45 fps; a 30 fps cap feels steadier than an uneven 40')
    if fg and t not in ('low', 'minimum'):
        rec.append(f'Frame generation: {fg} on (with NVIDIA Reflex/AMD Anti-Lag on); turn it off if aiming feels floaty')
    rec.append('After changing settings, play 10-15 minutes: the game finishes compiling shaders and the stutter calms down')
    return rec


def _block(rows) -> str:
    lines = [BEGIN, '[SystemSettings]']
    for name, value, why in rows:
        lines.append(f'; {why}')
        lines.append(f'{name}={value}')
    lines.append(END)
    return '\n'.join(lines) + '\n'


def _strip_block(text: str) -> str:
    return re.sub(re.escape(BEGIN) + r'.*?' + re.escape(END) + r'\n?', '', text, flags=re.S)


def install(ctx) -> None:
    ctx.say('Checking this PC')
    try:
        hw = scan()
    except Exception as ex:  # noqa: BLE001  - never let an odd PC stop the install
        ctx.say(f'  could not read this PC ({type(ex).__name__}); using middle-of-the-road settings')
        hw = {'gpu': 'Unknown graphics card', 'vram_gb': 6.0, 'integrated': False, 'ram_gb': 16,
              'cpu': 'Unknown processor', 'threads': 8, 'width': 1920, 'height': 1080, 'hz': 60,
              'guessed': ['everything']}
    t = tier(hw)
    ctx.say(f"  graphics card: {hw['gpu']} ({hw['vram_gb']} GB)")
    ctx.say(f"  processor: {hw['cpu']} ({hw['threads']} threads), memory {hw['ram_gb']} GB")
    ctx.say(f"  screen: {hw['width']}x{hw['height']} at {hw['hz']} Hz")
    if hw.get('guessed'):
        ctx.say(f"  couldn't read: {', '.join(hw['guessed'])} (a safe middle value is used)")
    ctx.say(f'  tuning for: {t}')
    rows, rec = settings(hw)
    created = set(ctx.state.get('created_inis') or [])
    written = []
    for d in config_dirs():
        ini = d / 'Engine.ini'
        try:
            d.mkdir(parents=True, exist_ok=True)
            if ini.is_file():
                text, enc = _read(ini)
            else:
                text, enc = '', 'utf-8'
                created.add(str(ini))
            text = _strip_block(text).rstrip()
            if text:
                text += '\n\n'
            # A second [SystemSettings] section is merged by the engine, so the block can sit at the end.
            _write(ini, text + _block(rows), enc)
            written.append(ini)
            ctx.say(f'Wrote {len(rows)} settings to {ini}')
        except OSError as ex:
            ctx.say(f'Could not write {ini}: {ex}')
    if not written:
        raise RuntimeError("Couldn't write Borderlands 4's settings file. Close the game and try again.")
    ctx.state['created_inis'] = sorted(created)
    notes = [
        'Vault Launcher - Borderlands 4 settings',
        f'Made {time.strftime("%Y-%m-%d %H:%M")}',
        '',
        'Your PC',
        f"  Graphics card: {hw['gpu']} ({hw['vram_gb']} GB video memory)",
        f"  Processor: {hw['cpu']} ({hw['threads']} threads)",
        f"  Memory: {hw['ram_gb']} GB",
        f"  Screen: {hw['width']}x{hw['height']} at {hw['hz']} Hz",
        f'  Tuned as: {t}' + (f" (couldn't read {', '.join(hw['guessed'])}; used safe values)" if hw.get('guessed') else ''),
        '',
        'Set by the launcher (in Engine.ini, between the Vault Launcher lines)',
    ] + [f'  {n}={v}  ({w})' for n, v, w in rows] + [
        '',
        'Pick these in the game (Options > Graphics)',
    ] + [f'  {r}' for r in rec] + [
        '',
        'To undo: remove "Borderlands 4 Tuning" in Vault Launcher. Only the launcher\'s lines are taken out.',
    ]
    for ini in written:
        try:
            (ini.parent / NOTES_NAME).write_text('\n'.join(notes) + '\n', encoding='utf-8')
        except OSError:
            pass
    ctx.say('In-game settings to pick for this PC:')
    for r in rec:
        ctx.say(f'  {r}')
    ctx.state.update({'installed': True, 'tier': t, 'hardware': hw})


def uninstall(ctx, restore: bool) -> None:
    created = set(ctx.state.get('created_inis') or [])
    if ctx.state.get('created_ini'):                 # 1.0.0 kept a single flag
        created.add(str(config_dir() / 'Engine.ini'))
    for d in config_dirs():
        ini = d / 'Engine.ini'
        try:
            if ini.is_file():
                text, enc = _read(ini)
                rest = _strip_block(text).strip()
                if not rest and str(ini) in created:
                    ini.unlink()
                    ctx.say(f'  removed {ini} (the launcher had made it)')
                elif rest != text.strip():
                    _write(ini, rest + '\n' if rest else '', enc)
                    ctx.say(f"  took the launcher's settings out of {ini}")
            notes = d / NOTES_NAME
            if notes.is_file():
                notes.unlink()
        except OSError as ex:
            ctx.say(f'  could not clean {ini}: {ex}')
    for key in ('installed', 'tier', 'hardware', 'created_ini', 'created_inis'):
        ctx.state.pop(key, None)
