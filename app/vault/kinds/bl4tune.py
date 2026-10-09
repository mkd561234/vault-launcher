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


def config_dir() -> Path:
    return winutil.documents_dir() / 'My Games' / 'Borderlands 4' / 'Saved' / 'Config' / 'Windows'


def _engine_ini() -> Path:
    return config_dir() / 'Engine.ini'


def checks(ctx) -> list:
    folder = ctx.paths.get(ctx.mod.game)
    return [{'label': 'Borderlands 4 installed', 'ok': folder is not None,
             'detail': '' if folder is not None else 'The settings are written anyway; they apply once the game is installed.'}]


def installed(ctx) -> bool:
    try:
        return ctx.state.get('installed') and BEGIN in _engine_ini().read_text(encoding='utf-8', errors='replace')
    except OSError:
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


INTEGRATED = re.compile(r'(intel\(r\) (uhd|hd|iris)|intel.*graphics$|radeon\(tm\) graphics|radeon graphics|vega \d+ graphics|'
                        r'microsoft basic|remote display|virtual)', re.I)


def scan() -> dict:
    gpus = _gpus()
    real = [g for g in gpus if not INTEGRATED.search(g[0])]
    name, vram = max(real or gpus or [('Unknown graphics card', 0)], key=lambda g: g[1])
    cpu_name, threads = _cpu()
    w, h, hz = _screen()
    return {'gpu': name, 'vram_gb': round(vram / 2 ** 30, 1), 'integrated': not real,
            'ram_gb': round(_ram_bytes() / 2 ** 30), 'cpu': cpu_name or 'Unknown processor', 'threads': threads,
            'width': w, 'height': h, 'hz': hz}


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
    if hw['integrated'] or vram < 5.5 or ram < 12:
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
    share = {'low': 0.40, 'medium': 0.45, 'high': 0.50, 'ultra': 0.50}[t]
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
    if t == 'low':
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
        out.append(('r.ViewDistanceScale', 0.85 if t != 'low' else 0.8, 'less for the processor to draw far away'))
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
    if t == 'low':
        quality = 'Performance' if h > 1080 else 'Balanced'
    preset = {'low': 'Low', 'medium': 'Medium', 'high': 'High', 'ultra': 'High'}[t]
    rec = [
        f'Graphics preset: {preset}, then change the lines below',
        f'Upscaling: {upscaler}, {quality}',
        f'Frame rate limit: {hw["hz"]} (your screen\'s refresh rate), VSync off',
        'Display mode: Fullscreen',
        'Motion blur: off (the launcher also turns it off)',
        f'Volumetric fog: {"Low" if t in ("low", "medium") else "Medium"}',
        f'Volumetric clouds: {"Low" if t in ("low", "medium") else "Medium"}',
        'Volumetric cloud shadows: off',
        f'Shadow quality: {"Low" if t == "low" else "Medium"}',
        f'Foliage density: {"Low" if t != "ultra" else "Medium"}',
        f'Texture quality: {"Low" if hw["vram_gb"] < 6 else "Medium" if hw["vram_gb"] < 10 else "High"} (set by your {hw["vram_gb"]} GB of video memory)',
        'HLOD loading range: Medium',
    ]
    fg = _frame_gen(hw['gpu'])
    if fg and t != 'low':
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
    hw = scan()
    t = tier(hw)
    ctx.say(f"  graphics card: {hw['gpu']} ({hw['vram_gb']} GB)")
    ctx.say(f"  processor: {hw['cpu']} ({hw['threads']} threads), memory {hw['ram_gb']} GB")
    ctx.say(f"  screen: {hw['width']}x{hw['height']} at {hw['hz']} Hz")
    ctx.say(f'  tuning for: {t}')
    rows, rec = settings(hw)
    ini = _engine_ini()
    ini.parent.mkdir(parents=True, exist_ok=True)
    existed = ini.is_file()
    text = ini.read_text(encoding='utf-8', errors='replace') if existed else ''
    if 'created_ini' not in ctx.state:
        ctx.state['created_ini'] = not existed
    text = _strip_block(text).rstrip()
    if text:
        text += '\n\n'
    # A second [SystemSettings] section is merged by the engine, so the block can sit at the end.
    ini.write_text(text + _block(rows), encoding='utf-8')
    ctx.say(f'Wrote {len(rows)} settings to {ini}')
    notes = [
        'Vault Launcher - Borderlands 4 settings',
        f'Made {time.strftime("%Y-%m-%d %H:%M")}',
        '',
        'Your PC',
        f"  Graphics card: {hw['gpu']} ({hw['vram_gb']} GB video memory)",
        f"  Processor: {hw['cpu']} ({hw['threads']} threads)",
        f"  Memory: {hw['ram_gb']} GB",
        f"  Screen: {hw['width']}x{hw['height']} at {hw['hz']} Hz",
        f'  Tuned as: {t}',
        '',
        'Set by the launcher (in Engine.ini, between the Vault Launcher lines)',
    ] + [f'  {n}={v}  ({w})' for n, v, w in rows] + [
        '',
        'Pick these in the game (Options > Graphics)',
    ] + [f'  {r}' for r in rec] + [
        '',
        'To undo: remove "Borderlands 4 Tuning" in Vault Launcher. Only the launcher\'s lines are taken out.',
    ]
    (ini.parent / NOTES_NAME).write_text('\n'.join(notes) + '\n', encoding='utf-8')
    ctx.say('In-game settings to pick for this PC:')
    for r in rec:
        ctx.say(f'  {r}')
    ctx.state.update({'installed': True, 'tier': t, 'hardware': hw})


def uninstall(ctx, restore: bool) -> None:
    ini = _engine_ini()
    if ini.is_file():
        rest = _strip_block(ini.read_text(encoding='utf-8', errors='replace')).strip()
        if not rest and ctx.state.get('created_ini'):
            ini.unlink()
            ctx.say('  removed Engine.ini (the launcher had made it)')
        else:
            ini.write_text(rest + '\n' if rest else '', encoding='utf-8')
            ctx.say("  took the launcher's settings out of Engine.ini")
    notes = ini.parent / NOTES_NAME
    if notes.is_file():
        notes.unlink()
    for key in ('installed', 'tier', 'hardware', 'created_ini'):
        ctx.state.pop(key, None)
