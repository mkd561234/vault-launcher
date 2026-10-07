"""Health bar for Krieg.

The Pre-Sequel HUD draws the health bar through a Flash clip whose name it caches in
WillowHUDGFxMovie.CachedGFxHealthBarPath ("p1.<name>.health_disp", "p1.<name>.bar", ...). The
native code takes <name> from a string 4 objects deep (HUD +0x260 -> +0xC40 -> +0x3DC -> FString at
+0xDC) and only refreshes it when the object at +0x3DC changes (it remembers it at HUD +0x490).
Krieg's object has an empty string there, so the HUD has no clip to draw his health in.

This module walks that chain in memory, names each object, copies the missing string from
Aurelia's equivalent object, and clears the HUD's remembered pointer so it rebuilds the path.
Offsets are for BorderlandsPreSequel.exe build 2863302. All reads are checked before use.
"""

import ctypes
from ctypes import wintypes

import unrealsdk

k32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD), ("RegionSize", ctypes.c_size_t),
                ("State", wintypes.DWORD), ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD)]


k32.VirtualQuery.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MBI), ctypes.c_size_t]

OFF_OWNER, OFF_A, OFF_B, OFF_STR, OFF_CACHE = 0x260, 0xC40, 0x3DC, 0xDC, 0x490


def _readable(addr: int, size: int) -> bool:
    mbi = _MBI()
    if addr < 0x10000 or not k32.VirtualQuery(ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
        return False
    return (mbi.State == 0x1000 and (mbi.Protect & 0x66) != 0 and not (mbi.Protect & 0x100)
            and addr + size <= mbi.BaseAddress + mbi.RegionSize)


def _u32(addr: int) -> int:
    if not _readable(addr, 4):
        return 0
    return int.from_bytes(ctypes.string_at(addr, 4), "little")


def _fstring(addr: int) -> str:
    ptr, num = _u32(addr), _u32(addr + 4)
    if not ptr or not 0 < num < 512 or not _readable(ptr, num * 2):
        return ""
    return ctypes.wstring_at(ptr, num - 1)


def _addr(obj) -> int:
    try:
        return obj._get_address()
    except Exception:  # noqa: BLE001
        return 0


def _object_props(obj):
    try:
        for prop in obj.Class._properties():
            if prop.Class.Name == "ObjectProperty" and getattr(prop, "ArrayDim", 1) == 1:
                try:
                    val = getattr(obj, prop.Name)
                except Exception:  # noqa: BLE001
                    continue
                if val is not None and hasattr(val, "_path_name"):
                    yield prop.Name, val
    except Exception:  # noqa: BLE001
        return


def _identify(addr: int, roots) -> tuple[str, object] | tuple[None, None]:
    for root in roots:
        if root is None:
            continue
        if _addr(root) == addr:
            return "(root)", root
        for name, val in _object_props(root):
            if _addr(val) == addr:
                return f"{root.Class.Name}.{name}", val
    return None, None


def _str_props(obj) -> dict[str, str]:
    out = {}
    try:
        for prop in obj.Class._properties():
            if prop.Class.Name == "StrProperty":
                try:
                    out[prop.Name] = str(getattr(obj, prop.Name))
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001
        pass
    return out


_state = {"done": False, "logged": False}


def fix_health_bar(movie, pc, log, template_paths=("Baroness", "Crocus")) -> None:
    if _state["done"]:
        return
    hud = _addr(movie)
    a = _u32(hud + OFF_OWNER)
    b = _u32(a + OFF_A) if a else 0
    c = _u32(b + OFF_B) if b else 0
    if not c:
        return
    current = _fstring(c + OFF_STR)
    name_a, obj_a = _identify(a, [movie, pc, pc.Pawn, pc.PlayerReplicationInfo])
    name_b, obj_b = _identify(b, [obj_a, pc, pc.Pawn, pc.PlayerReplicationInfo])
    name_c, obj_c = _identify(c, [obj_b, pc, pc.Pawn])
    if not _state["logged"]:
        _state["logged"] = True
        log(f"health bar chain: {name_a}={obj_a} -> {name_b}={obj_b} -> {name_c}={obj_c}; "
            f"string at +0xDC = {current!r}; HUD path = {movie.CachedGFxHealthBarPath!r}")
        if obj_c is not None:
            log(f"  string properties of {obj_c}: {_str_props(obj_c)}")
    if current or obj_c is None:
        _state["done"] = bool(current)
        return

    # Find the Pre-Sequel equivalent of obj_c (same class, from Aurelia) and copy its strings.
    analog = None
    for cand in unrealsdk.find_all(obj_c.Class.Name, exact=True):
        p = cand._path_name()
        if "Default__" not in p and any(t in p for t in template_paths):
            analog = cand
            break
    if analog is None:
        log(f"no Pre-Sequel {obj_c.Class.Name} found to copy the health bar name from")
        return
    copied = []
    mine, theirs = _str_props(obj_c), _str_props(analog)
    for key, val in theirs.items():
        if val and not mine.get(key):
            try:
                setattr(obj_c, key, val)
                copied.append(f"{key}={val!r}")
            except Exception:  # noqa: BLE001
                pass
    now = _fstring(c + OFF_STR)
    log(f"copied {copied} from {analog}; string at +0xDC is now {now!r}")
    if now:
        # Make the HUD rebuild its cached clip path on its next update.
        cache_addr = hud + OFF_CACHE
        if _u32(cache_addr) == c and _readable(cache_addr, 4):
            ctypes.memmove(cache_addr, (ctypes.c_uint32 * 1)(0), 4)
        _state["done"] = True
