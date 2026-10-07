"""Builds the small texture cache files Krieg's skins and heads need.

Krieg's textures stream their high-resolution mips from texture cache (.tfc) files. Borderlands 2's
shared CharTextures.tfc / Textures.tfc have namesakes in the Pre-Sequel with different contents
(reading them crashed the game), and the DLC heads/skins use their own DLC's cache files, which the
Pre-Sequel doesn't have. The textures were re-pointed at compact files in Krieg's DLC folder
(CharTextures_0.tfc, CharTextures_allium_ct_0.tfc, ...); this copies just the needed byte ranges out
of your Borderlands 2 install to create them, once. It runs before the game scans the DLC folder.
"""

import json
from pathlib import Path

LZO_TAG = bytes.fromhex("c1832a9e")


def build(log) -> None:
    mod_dir = Path(__file__).resolve().parent
    tps_root = mod_dir.parents[1]
    bl2_root = tps_root.parent / "Borderlands 2"
    out_dir = tps_root / "DLC" / "Lilac" / "Compat" / "Textures"
    manifest = json.loads((mod_dir / "tfc_manifest.json").read_text())
    for name, info in manifest.items():
        dst = out_dir / f"{name}.tfc"
        if dst.exists() and dst.stat().st_size == info["size"]:
            continue
        src = bl2_root / info["src"]
        if not src.exists():
            log(f"cannot build {dst.name}: {src} not found (is Borderlands 2 installed next to the Pre-Sequel?)")
            continue
        try:
            tmp = dst.with_suffix(".tmp")
            bad = 0
            with open(src, "rb") as fs, open(tmp, "wb") as fd:
                for off, size, dst_off in info["ranges"]:
                    if fd.tell() != dst_off:
                        raise RuntimeError(f"{dst.name}: layout mismatch at {dst_off}")
                    fs.seek(off)
                    chunk = fs.read(size)
                    if len(chunk) != size:
                        raise RuntimeError(f"{src.name} is shorter than expected (offset {off})")
                    if chunk[:4] != LZO_TAG:
                        bad += 1
                    fd.write(chunk)
            tmp.replace(dst)
        except Exception as ex:  # noqa: BLE001 - one bad file must not stop the others
            log(f"texture cache {dst.name} failed: {type(ex).__name__}: {ex}")
            continue
        log(f"built {dst.name} ({info['size']} bytes, {len(info['ranges'])} mips"
            f"{f', {bad} without the usual header' if bad else ''}) from {src}")
