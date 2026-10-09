"""Everything useful in one log, so a problem can be tracked down from krieg_log.txt alone.

* At start-up: mod, Python and SDK versions.
* Errors from the SDK's own log (Python tracebacks from any mod, SDK warnings) are copied in as
  they happen, so nothing is lost when only krieg_log.txt is sent.
* A full snapshot is written whenever a level finishes loading, a player joins or leaves, and on
  the krieg_dump console command: the map, every player (class, head/skin), every Krieg (role,
  physics, health/shield/oxygen, the parts attached to his body and where), his gear (weapons,
  shield, grenade, Oz kit with its slam element and grade, class mod) and the class mod spot.
The log is capped so a long session can't grow it without limit.
"""

import re
import sys
import time
from pathlib import Path

import unrealsdk
from mods_base import command, get_pc

MAX_LINES = 2500
GAME_DIR = Path(__file__).resolve().parents[2]
SDK_LOG = GAME_DIR / "Binaries" / "Win32" / "Plugins" / "unrealsdk.log"
_state = {"lines": 0, "next": 0.0, "map": None, "players": None, "snap_at": 0.0, "sdk_pos": None,
          "sdk_in_trace": False, "header": False}
_IMPORTANT = re.compile(r"Traceback|Error|ERROR|Exception|\[WARN|\bwarning\b|failed", re.IGNORECASE)


def log(msg: str) -> None:
    if _state["lines"] >= MAX_LINES:
        return
    _state["lines"] += 1
    from . import log as _log
    _log(msg)


def _get(obj, attr, default="?"):
    try:
        return getattr(obj, attr)
    except Exception:  # noqa: BLE001
        return default


def _short(obj) -> str:
    if obj is None:
        return "None"
    try:
        return obj._path_name().split(".")[-1]
    except Exception:  # noqa: BLE001
        return str(obj)


def _enum(v) -> str:
    return getattr(v, "name", str(v))


# ---------------------------------------------------------------------------------------------
def header() -> None:
    if _state["header"]:
        return
    _state["header"] = True
    from . import __version__
    sdk = "?"
    try:
        import pyunrealsdk
        sdk = ".".join(str(x) for x in getattr(pyunrealsdk, "__version_info__", ())) or "?"
    except Exception:  # noqa: BLE001
        pass
    log(f"diag: Krieg mod {__version__}, Python {sys.version.split()[0]}, pyunrealsdk {sdk}, "
        f"game folder {GAME_DIR}, SDK log {'found' if SDK_LOG.exists() else 'not found'}")


def mirror_sdk_log() -> None:
    """Copy new errors/warnings (and whole Python tracebacks) from the SDK's log."""
    try:
        size = SDK_LOG.stat().st_size
    except OSError:
        return
    pos = _state["sdk_pos"]
    if pos is None or size < pos:
        _state["sdk_pos"] = size if pos is None else 0   # skip what was there before we started
        if pos is None:
            return
        pos = 0
    if size == pos:
        return
    try:
        with open(SDK_LOG, "rb") as f:
            f.seek(pos)
            chunk = f.read(min(size - pos, 256 * 1024))
    except OSError:
        return
    _state["sdk_pos"] = pos + len(chunk)
    for raw in chunk.decode("utf-8", "replace").splitlines():
        line = raw.rstrip()
        if not line or "[KriegTPS]" in line:
            continue
        text = line.split("] ", 1)[-1] if line.startswith("[") or line[:2].isdigit() else line
        if "Traceback" in line:
            _state["sdk_in_trace"] = True
            log("sdk: " + text)
            continue
        if _state["sdk_in_trace"]:
            log("sdk: " + text)
            if not text.startswith((" ", "\t")) and "File " not in text:
                _state["sdk_in_trace"] = False
            continue
        if _IMPORTANT.search(line):
            log("sdk: " + text)


# ---------------------------------------------------------------------------------------------
def _pris():
    try:
        return list(get_pc().WorldInfo.GRI.PRIArray)
    except Exception:  # noqa: BLE001
        return []


def _player_pawns():
    out = []
    try:
        pawn = get_pc().WorldInfo.PawnList
        for _ in range(512):
            if pawn is None:
                break
            if _get(pawn, "SlamForceBaseValue", None) is not None:
                out.append(pawn)
            pawn = pawn.NextPawn
    except Exception:  # noqa: BLE001
        pass
    return out


def _mesh_name(comp) -> str:
    for attr in ("SkeletalMesh", "StaticMesh"):
        m = _get(comp, attr, None)
        if m is not None and m != "?":
            return str(m.Name)
    return comp.Class.Name if comp is not None else "?"


def _pool(pool_struct) -> str:
    data = _get(pool_struct, "Data", None)
    if data is None or data == "?":
        return "?"
    try:
        return f"{float(data.CurrentValue):.0f}/{float(data.GetMaxValue()):.0f}"
    except Exception:  # noqa: BLE001
        return "?"


def _inventory(pawn) -> list:
    items = []
    mgr = _get(pawn, "InvManager", None)
    inv = _get(mgr, "InventoryChain", None) if mgr not in (None, "?") else None
    for _ in range(64):
        if inv is None or inv == "?":
            break
        defn = _get(inv, "DefinitionData", None)
        name = _short(_get(defn, "BalanceDefinition", None)) if defn not in (None, "?") else _short(inv)
        items.append(f"{inv.Class.Name}:{name}")
        inv = _get(inv, "Inventory", None)
    return items


def _krieg_details(pawn) -> None:
    from . import slam
    pri = _get(pawn, "PlayerReplicationInfo", None)
    who = _get(pri, "PlayerName", "?")
    loc = _get(pawn, "Location", None)
    log(f"diag:  Krieg {who}: role {_enum(_get(pawn, 'Role'))}, physics {_enum(_get(pawn, 'Physics'))}, "
        f"at ({_get(loc, 'X', 0):.0f}, {_get(loc, 'Y', 0):.0f}, {_get(loc, 'Z', 0):.0f}), "
        f"health {_pool(_get(pawn, 'HealthPool', None))}, shield {_pool(_get(pawn, 'ShieldArmor', None))}, "
        f"oxygen {_pool(_get(pawn, 'OxygenPool', None))}, slam force {_get(pawn, 'SlamForce')} "
        f"enabled {_get(pawn, 'SlamEnabled')}, head {_short(_get(pawn, 'HeadCustomizationData', None))}, "
        f"skin {_short(_get(pawn, 'SkinCustomizationData', None))}, hidden {_get(pawn, 'bHidden')}")
    try:
        grade = slam._attr(slam.GRADE_ATTR, pawn)
        elems = {k: slam._attr(slam.ELEMENTS[k][0], pawn) for k in slam.CHECK_ORDER}
        log(f"diag:    Oz kit slam: grade {grade:g}, elements {', '.join(f'{k} {v:g}' for k, v in elems.items())}")
    except Exception as ex:  # noqa: BLE001
        log(f"diag:    Oz kit slam: {type(ex).__name__}: {ex}")
    gear = _inventory(pawn)
    if gear:
        log(f"diag:    gear: {', '.join(gear)}")
    mesh = _get(pawn, "Mesh", None)
    if mesh not in (None, "?"):
        log(f"diag:    body {_mesh_name(mesh)} hidden={_get(mesh, 'HiddenGame')} "
            f"ownerNoSee={_get(mesh, 'bOwnerNoSee')}")
        try:
            for att in mesh.Attachments:
                c = att.Component
                if c is None:
                    continue
                rl = att.RelativeLocation
                log(f"diag:      attached {_mesh_name(c)} at {att.BoneName} "
                    f"offset ({rl.X:.1f}, {rl.Y:.1f}, {rl.Z:.1f}) hidden={_get(c, 'HiddenGame')}")
        except Exception as ex:  # noqa: BLE001
            log(f"diag:      attachments: {type(ex).__name__}: {ex}")


def snapshot(why: str) -> None:
    pc = get_pc()
    if pc is None:
        log(f"diag: === {why}: no player controller ===")
        return
    world = _get(pc, "WorldInfo", None)
    mode = _enum(_get(world, "NetMode")) if world not in (None, "?") else "?"
    try:
        map_name = str(world.GetMapName(True))
    except Exception:  # noqa: BLE001
        map_name = "?"
    log(f"diag: === {why}: map {map_name}, {mode}, {len(_pris())} player(s) ===")
    for pri in _pris():
        cls = _get(pri, "CharacterClass", None) or _get(pri, "PlayerClass", None)
        try:
            custom = ", ".join(_short(x) for x in pri.RemoteCustomizations if x is not None)
        except Exception:  # noqa: BLE001
            custom = "?"
        log(f"diag:  player {_get(pri, 'PlayerName')} ({_short(cls)}), level {_get(pri, 'ExpLevel')}, "
            f"head/skin [{custom}]")
    for pawn in _player_pawns():
        try:
            arch = _short(_get(pawn, "ObjectArchetype", None))
            if "Lilac" in arch:
                _krieg_details(pawn)
            else:
                log(f"diag:  other player pawn {arch} ({_get(_get(pawn, 'PlayerReplicationInfo', None), 'PlayerName')})")
        except Exception as ex:  # noqa: BLE001
            log(f"diag:  pawn: {type(ex).__name__}: {ex}")
    try:
        from . import CLASSMOD_LOCATION, CLASSMOD_SCALE
        log(f"diag:  class mod spot {CLASSMOD_LOCATION} scale {CLASSMOD_SCALE}")
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------------------------
def upkeep() -> None:
    header()
    now = time.monotonic()
    if now < _state["next"]:
        return
    _state["next"] = now + 2.0
    mirror_sdk_log()
    pc = get_pc()
    if pc is None:
        return
    try:
        map_name = str(pc.WorldInfo.GetMapName(True))
    except Exception:  # noqa: BLE001
        map_name = None
    players = len(_pris())
    changed = None
    if map_name != _state["map"]:
        changed = f"level {map_name} loaded"
    elif players != _state["players"]:
        changed = f"players now {players}"
    _state["map"], _state["players"] = map_name, players
    if changed:
        _state["snap_at"] = now + 5.0          # give the level/players a moment to settle
        _state["snap_why"] = changed
    if _state["snap_at"] and now >= _state["snap_at"]:
        _state["snap_at"] = 0.0
        snapshot(_state.get("snap_why", "state"))


@command("krieg_dump", description="Write everything about the current game, players and Krieg to krieg_log.txt.")
def krieg_dump(_args) -> None:
    _state["lines"] = min(_state["lines"], MAX_LINES - 200)
    snapshot("krieg_dump command")
    mirror_sdk_log()


diag_hooks = [krieg_dump]
