"""Co-op diagnostics: what each game knows about every player's head/skin, and how the players are
drawn when the trade screen opens.

Two co-op problems are being tracked down with this:
* a joining Krieg sees the host's Krieg in the default head and skin;
* a joining Krieg's own body is missing from his trade screen (the host's shows fine).
Nothing here changes the game; it only writes to the Krieg log (at most a few lines per change).
"""

import time

import unrealsdk
from mods_base import command, get_pc, hook
from unrealsdk.hooks import Type

_state = {"seen": {}, "next": 0.0, "trade_at": 0.0, "trade_logged": 0, "lines": 0}
MAX_LINES = 200


def log(msg: str) -> None:
    if _state["lines"] >= MAX_LINES:
        return
    _state["lines"] += 1
    from . import log as _log
    _log("co-op diag: " + msg)


def _name(obj) -> str:
    if obj is None:
        return "None"
    try:
        return obj._path_name()
    except Exception:  # noqa: BLE001
        return str(obj)


def _get(obj, attr, default="?"):
    try:
        return getattr(obj, attr)
    except Exception:  # noqa: BLE001
        return default


def _role(actor) -> str:
    r = _get(actor, "Role", None)
    return getattr(r, "name", str(r))


def _list(arr) -> str:
    try:
        return "[" + ", ".join(_name(x).split(".")[-1] for x in arr) + "]"
    except Exception:  # noqa: BLE001
        return str(arr)


def _pris():
    pc = get_pc()
    try:
        return list(pc.WorldInfo.GRI.PRIArray)
    except Exception:  # noqa: BLE001
        return []


def _pawns():
    pc = get_pc()
    out = []
    try:
        pawn = pc.WorldInfo.PawnList
        for _ in range(256):
            if pawn is None:
                break
            if _get(pawn, "SlamForceBaseValue", None) is not None:   # player pawns only
                out.append(pawn)
            pawn = pawn.NextPawn
    except Exception:  # noqa: BLE001
        pass
    return out


def _pri_line(pri) -> str:
    cls = _get(pri, "CharacterClass", None) or _get(pri, "PlayerClass", None)
    return (f"{_get(pri, 'PlayerName', '?')} ({_name(cls).split('.')[-1]}, role {_role(pri)}): "
            f"local {_list(_get(pri, 'LocalCustomizations', []))} "
            f"remote {_list(_get(pri, 'RemoteCustomizations', []))}")


def _mesh_line(comp) -> str:
    if comp is None or comp == "?":
        return "None"
    return (f"{_name(_get(comp, 'SkeletalMesh', None)).split('.')[-1]} hidden={_get(comp, 'HiddenGame')} "
            f"ownerNoSee={_get(comp, 'bOwnerNoSee')} onlyOwnerSee={_get(comp, 'bOnlyOwnerSee')} "
            f"attached={_get(comp, 'bAttached')}")


def _pawn_line(pawn) -> str:
    pc = get_pc()
    mine = pc is not None and pc.Pawn is not None and pc.Pawn._get_address() == pawn._get_address()
    pri = _get(pawn, "PlayerReplicationInfo", None)
    return (f"{'my' if mine else 'other'} pawn {_get(pri, 'PlayerName', '?')} role {_role(pawn)} "
            f"arch {_name(_get(pawn, 'ObjectArchetype', None)).split('.')[-1]} hidden={_get(pawn, 'bHidden')} "
            f"head={_name(_get(pawn, 'HeadCustomizationData', None)).split('.')[-1]} "
            f"skin={_name(_get(pawn, 'SkinCustomizationData', None)).split('.')[-1]} "
            f"mesh: {_mesh_line(_get(pawn, 'Mesh', None))}")


def snapshot(why: str) -> None:
    pc = get_pc()
    log(f"--- {why} (behind view {_get(pc, 'bBehindView') if pc else '?'}) ---")
    for pri in _pris():
        log("PRI " + _pri_line(pri))
    for pawn in _pawns():
        log(_pawn_line(pawn))
    if "trade" in why or "command" in why:
        _bodies()


def _bodies() -> None:
    """Every Krieg body mesh in memory (the trade screen may draw a stand-in, not the pawn)."""
    count = 0
    for comp in unrealsdk.find_all("SkeletalMeshComponent", exact=False):
        mesh = _get(comp, "SkeletalMesh", None)
        if mesh is None or "Psycho" not in str(mesh.Name) or "Default__" in comp._path_name():
            continue
        count += 1
        if count > 8:
            break
        owner = _get(comp, "Owner", None)
        log(f"body {comp._path_name().split('.')[-1]} owner={_name(owner).split('.')[-1]} "
            f"ownerHidden={_get(owner, 'bHidden') if owner else '?'} {_mesh_line(comp)} "
            f"depth={_get(comp, 'DepthPriorityGroup')} scene={_get(comp, 'bAttached')}")
    log(f"{count} Krieg body mesh(es) found")


def upkeep() -> None:
    """Writes each player's head/skin lists once when they change (checked every few seconds)."""
    now = time.monotonic()
    if now < _state["next"]:
        return
    _state["next"] = now + 5.0
    pris = _pris()
    if len(pris) < 2:
        return  # only interesting in co-op
    for pri in pris:
        line = _pri_line(pri)
        key = pri._get_address()
        if _state["seen"].get(key) != line:
            _state["seen"][key] = line
            log("PRI " + line)
    for pawn in _pawns():
        line = _pawn_line(pawn)
        key = ("pawn", pawn._get_address())
        short = line.split(" mesh:")[0]
        if _state["seen"].get(key) != short:
            _state["seen"][key] = short
            log(line)


def tick() -> None:
    at = _state["trade_at"]
    if at and time.monotonic() - at > 1.5:
        _state["trade_at"] = 0.0
        snapshot("trade screen, 1.5 s later")


@hook("WillowGame.TradingGFxMovie:Start", Type.POST, hook_identifier="KriegTPSCoopDiagTrade")
def on_trade_start(*_):
    if _state["trade_logged"] >= 3:
        return
    _state["trade_logged"] += 1
    snapshot("trade screen opened")
    _state["trade_at"] = time.monotonic()


@command("krieg_coop", description="Write every player's head/skin and how their bodies are drawn to the Krieg log.")
def krieg_coop(_args) -> None:
    _state["lines"] = 0
    snapshot("krieg_coop command")


coop_hooks = [on_trade_start, krieg_coop]
