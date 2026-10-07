"""Rebuilds Krieg's Pre-Sequel DLC folder from the player's own game files.

Nothing from either game ships with the installer. Every output file is either
  * copied from the player's Borderlands 2 install,
  * rebuilt from a Borderlands 2 package with a small patch (patches/*.kdl: "copy these byte
    ranges from your file" plus the mod's own changes - new icons, re-pointed textures, etc.),
  * a texture cache cut out of the player's Borderlands 2 texture caches (tfc_manifest.json), or
  * a tiny generated file (DLC version stamp, licence pointer to a Pre-Sequel DLC the player owns).
Every rebuilt file is checked against the exact SHA-1 of the working release.
"""

import hashlib
import json
import shutil
import struct
import zlib
from pathlib import Path

from ..lzo import lzo1x_decompress

PKG_TAG = 0x9E2A83C1


class BuildError(Exception):
    pass


# --------------------------------------------------------------------------------------------
# Unreal package "canonical" form (must match the encoder used to make the patches)
# --------------------------------------------------------------------------------------------
def _chunk(raw: bytes, p: int) -> bytes:
    tag, bsize, ctot, utot = struct.unpack_from('<Iiii', raw, p)
    p += 16
    blocks = []
    rem = utot
    while rem > 0:
        cs, us = struct.unpack_from('<ii', raw, p)
        p += 8
        blocks.append((cs, us))
        rem -= us
    out = bytearray()
    for cs, us in blocks:
        out += lzo1x_decompress(raw[p:p + cs], us)
        p += cs
    return bytes(out)


def canon(path: Path) -> bytes:
    raw = path.read_bytes()
    if len(raw) < 8 or struct.unpack_from('<I', raw, 0)[0] != PKG_TAG:
        return raw
    if struct.unpack_from('<I', raw, 4)[0] == 0x20000:
        raw = _chunk(raw, 0)
    o = 8
    header_size, = struct.unpack_from('<i', raw, o)
    o += 4
    n, = struct.unpack_from('<i', raw, o)
    o += 4
    o += n if n >= 0 else -2 * n
    o += 4 + 28 + 16 + 16
    gc, = struct.unpack_from('<i', raw, o)
    o += 4 + gc * 12
    o += 8
    cflags, nchunks = struct.unpack_from('<Ii', raw, o)
    o += 8
    if not nchunks:
        return raw
    chunks = [struct.unpack_from('<4i', raw, o + 16 * i) for i in range(nchunks)]
    data = bytearray(raw[:header_size])
    for (uoff, usize, coff, csize) in chunks:
        out = _chunk(raw, coff)
        if len(data) < uoff:
            data += b'\0' * (uoff - len(data))
        data[uoff:uoff + len(out)] = out
    return bytes(data)


def apply_patch(packed: bytes, sources: list) -> bytes:
    d = zlib.decompressobj(-15)
    b = d.decompress(packed) + d.flush()
    if b[:4] != b'KDL1':
        raise BuildError('not a Krieg patch file')
    n, = struct.unpack_from('<I', b, 4)
    sha = b[8:28]
    o = 28
    ns, = struct.unpack_from('<H', b, o)
    o += 2
    for _ in range(ns):
        ln, = struct.unpack_from('<H', b, o)
        o += 2 + ln
    out = bytearray()
    while True:
        op = b[o]
        o += 1
        if op == 0:
            break
        if op == 1:
            si, off, ln = struct.unpack_from('<HII', b, o)
            o += 10
            chunk = sources[si][off:off + ln]
            if len(chunk) != ln:
                raise BuildError('source file is shorter than expected')
            out += chunk
        elif op == 2:
            ln, = struct.unpack_from('<I', b, o)
            o += 4
            out += b[o:o + ln]
            o += ln
        else:
            raise BuildError('corrupt patch')
    if len(out) != n or hashlib.sha1(out).digest() != sha:
        raise BuildError('result does not match (your Borderlands 2 files differ from the expected version)')
    return bytes(out)


# --------------------------------------------------------------------------------------------
# Ownership / install checks
# --------------------------------------------------------------------------------------------
BL2_EXE = 'Binaries/Win32/Borderlands2.exe'
TPS_EXE = 'Binaries/Win32/BorderlandsPreSequel.exe'
PSYCHO_PACK = 'DLC/Lilac'
TPS_DLC_PREFERENCE = ('Crocus', 'Quince', 'Freesia', 'Marigold', 'Petunia', 'Ailanthus')


def read_licence(dlc_dir: Path):
    f = dlc_dir / 'Lic' / 'Licenses' / 'steam_0.bin'
    try:
        data = f.read_bytes()
        appid, = struct.unpack_from('<I', data, 0)
        return appid
    except (OSError, struct.error):
        return None


def check_bl2(bl2: Path) -> list:
    problems = []
    if not (bl2 / BL2_EXE).is_file():
        problems.append(f'Borderlands 2 was not found in {bl2}.')
        return problems
    lilac = bl2 / PSYCHO_PACK
    if read_licence(lilac) is None or not (lilac / 'Compat' / 'Content' / 'GD_Lilac_Psycho_Streaming_SF.upk').is_file():
        problems.append('The Borderlands 2 "Psycho Pack" (Krieg) DLC is not installed. Krieg comes from your own '
                        'copy of it, so it must be owned and installed in Steam (Borderlands 2 > Properties > DLC).')
    return problems


def find_tps_licence(tps: Path):
    """A Pre-Sequel DLC the player has installed; Krieg's folder reuses its licence (TPS only loads
    DLC folders licensed to a Pre-Sequel app the player owns)."""
    dlc = tps / 'DLC'
    found = {}
    if dlc.is_dir():
        for d in dlc.iterdir():
            if d.name.lower() == 'lilac' or not d.is_dir():
                continue
            appid = read_licence(d)
            has_stamp = (d / 'Compat' / 'contver.bin').is_file() or (d / 'Lic' / 'contver.bin').is_file()
            if appid and has_stamp:
                found[d.name] = appid
    for name in TPS_DLC_PREFERENCE:
        if name in found:
            return name, found[name]
    if found:
        name = sorted(found)[0]
        return name, found[name]
    return None, None


def check_tps(tps: Path) -> list:
    problems = []
    if not (tps / TPS_EXE).is_file():
        problems.append(f'Borderlands: The Pre-Sequel was not found in {tps}.')
        return problems
    name, _ = find_tps_licence(tps)
    if name is None:
        problems.append('No Pre-Sequel DLC is installed. Krieg loads as a DLC character, and the Pre-Sequel only '
                        'loads DLC folders licensed to a Pre-Sequel DLC you own - any one of them works '
                        '(Lady Hammerlock, Handsome Jack, Claptastic Voyage, Holodome, Shock Drop, Ultimate Vault '
                        'Hunter pack).')
    return problems


# --------------------------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------------------------
def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def build(bl2: Path, tps: Path, payload: Path, out_root: Path, say) -> dict:
    """Builds the DLC folder into out_root (which becomes TPS\\DLC\\Lilac). Returns a report."""
    recipe = json.loads((payload / 'recipe.json').read_text(encoding='utf-8'))
    report = {'built': 0, 'skipped_optional': [], 'failed_optional': []}

    # 1. packages rebuilt with patches
    cache = {}

    def source(rel):
        if rel not in cache:
            cache[rel] = canon(bl2 / rel)
        return cache[rel]

    total = len(recipe['patches'])
    for i, e in enumerate(recipe['patches'], 1):
        dlc = e['needs_dlc']
        required = dlc == 'Lilac'
        if not all((bl2 / s).is_file() for s in e['sources']):
            if required:
                raise BuildError(f"missing Borderlands 2 file {e['sources'][0]} - verify Borderlands 2 in Steam")
            report['skipped_optional'].append(Path(e['out']).name)
            continue
        try:
            data = apply_patch((payload / e['patch']).read_bytes(), [source(s) for s in e['sources']])
        except (BuildError, OSError, struct.error, zlib.error) as ex:
            if required:
                raise BuildError(f"{Path(e['out']).name}: {ex}") from ex
            report['failed_optional'].append(Path(e['out']).name)
            continue
        _write(out_root / e['out'][len('DLC/Lilac/'):], data)
        report['built'] += 1
        if i % 20 == 0 or i == total:
            say(f'  packages {i}/{total}')
    cache.clear()

    # 2. straight copies (audio, text, Krieg's own texture caches)
    for c in recipe['copies']:
        src = bl2 / c['src']
        if not src.is_file():
            raise BuildError(f"missing Borderlands 2 file {c['src']} - verify Borderlands 2 in Steam")
        dst = out_root / c['out'][len('DLC/Lilac/'):]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    say(f"  copied {len(recipe['copies'])} sound/text/texture files")

    # 3. WillowDlc.ini: Aurelia uses DLC package id 6, so Krieg moves to 20
    ini = recipe['ini']
    text = (bl2 / ini['src']).read_bytes()
    for old, new in ini['replace']:
        text = text.replace(old.encode(), new.encode())
    _write(out_root / ini['out'][len('DLC/Lilac/'):], text)

    # 4. version stamps: BL2's name/version + the Pre-Sequel's content id
    name_dlc, appid = find_tps_licence(tps)
    tps_cv = (tps / 'DLC' / name_dlc / 'Compat' / 'contver.bin')
    if not tps_cv.is_file():
        tps_cv = (tps / 'DLC' / name_dlc / 'Lic' / 'contver.bin')
    guid = tps_cv.read_bytes()[-16:]
    bl2_cv = (bl2 / 'DLC/Lilac/Compat/contver.bin').read_bytes()
    stamp = bl2_cv[:-16] + guid
    for rel in recipe['contver']:
        _write(out_root / rel[len('DLC/Lilac/'):], stamp)

    # 5. licence: a Pre-Sequel DLC the player owns
    _write(out_root / recipe['licence'][len('DLC/Lilac/'):], struct.pack('<II', appid, 1))
    report['licence_from'] = name_dlc

    # 6. texture caches cut out of the player's Borderlands 2 caches
    manifest = json.loads((payload / recipe['tfc_manifest']).read_text(encoding='utf-8'))
    tex = out_root / 'Compat' / 'Textures'
    tex.mkdir(parents=True, exist_ok=True)
    made = 0
    for name, info in manifest.items():
        src = bl2 / info['src']
        if not src.is_file():
            if not info['src'].startswith('DLC/'):
                raise BuildError(f"missing Borderlands 2 file {info['src']} - verify Borderlands 2 in Steam")
            report['skipped_optional'].append(f'{name}.tfc')
            continue
        with open(src, 'rb') as fs, open(tex / f'{name}.tfc', 'wb') as fd:
            for off, size, dst_off in info['ranges']:
                fs.seek(off)
                chunk = fs.read(size)
                if len(chunk) != size or fd.tell() != dst_off:
                    raise BuildError(f'{src.name} is not the expected version')
                fd.write(chunk)
        made += 1
    say(f'  built {made} texture caches')
    return report
