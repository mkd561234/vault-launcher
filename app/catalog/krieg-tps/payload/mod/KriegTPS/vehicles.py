"""Krieg's seating in the Pre-Sequel's vehicles.

A character's vehicle poses come from its body class: DLCVehicleAnimSetMappings lists, per vehicle
archetype name, the AnimSet with that character's seat animations. Krieg's list only names
Borderlands 2 vehicles, so in a Moon Buggy or Stingray he had no seat animation and just stood on
top of the vehicle.

Aurelia's mappings show what the Pre-Sequel vehicles need. Her Moon Buggy set has exactly the same
16 animations (Driver_Idle, Driver_Enter_Left, Gunner_Idle, Driver_to_Gunner, ...) as Krieg's
Borderlands 2 Runner set, so the Runner set is used for both Moon Buggies. The Stingray (driver
only) uses the same set's driver animations.
"""

import unrealsdk

BODY = "GD_Lilac_Psycho_Streaming.BodyClass_LilacPlayerClass"
RUNNER = "Anim_PsychoDLC.LightRunner_PsychoDLC"
MAPPINGS = (
    ("Vehicle_MoonBuggy_Laser", RUNNER),
    ("Vehicle_MoonBuggy_MissilePod", RUNNER),
    ("Vehicle_StingRay_CryoRocket", RUNNER),
    ("Vehicle_StingRay_FlakBurst", RUNNER),
)

_state = {"done_for": None, "logged": False}


def log(msg: str) -> None:
    from . import log as _log
    _log(msg)


def _find(cls: str, path: str):
    try:
        return unrealsdk.find_object(cls, path)
    except ValueError:
        return None


def upkeep() -> None:
    body = _find("BodyClassDefinition", BODY)
    if body is None:
        return
    addr = body._get_address()
    if _state["done_for"] == addr:
        return
    animset = _find("AnimSet", RUNNER)
    if animset is None:
        if not _state["logged"]:
            _state["logged"] = True
            log(f"vehicles: {RUNNER} is not loaded yet")
        return
    mappings = body.DLCVehicleAnimSetMappings
    have = {str(m.VehicleArchetypeName) for m in mappings}
    added = []
    for vehicle, _ in MAPPINGS:
        if vehicle in have:
            continue
        template = mappings[0] if len(mappings) else None
        type_name = template._type.Name if template is not None else "VehicleCrewMappingStruct"
        mappings.append(unrealsdk.make_struct(type_name, VehicleArchetypeName=vehicle, AnimSet=animset,
                                              bUseSecondarySeatAnchor=False))
        added.append(vehicle)
    _state["done_for"] = addr
    if added:
        log(f"vehicles: Krieg now has seat animations for {', '.join(added)}")


def upkeep_all() -> None:
    upkeep()
    keep_seat_animset()
    tick()          # backup for the per-frame call: never leave Krieg hidden
    diagnose()


# ---------------------------------------------------------------------------
# Diagnostics: while Krieg is in a vehicle, write what the game is doing with him to the log
# (vehicle, seat, which animation set it picked, which animations are actually playing, where he
# sits relative to the vehicle), so a wrong pose can be fixed from the log alone.
# ---------------------------------------------------------------------------
import math  # noqa: E402
import time  # noqa: E402

from mods_base import get_pc, hook  # noqa: E402
from unrealsdk.hooks import Type  # noqa: E402

_diag = {"next": 0.0, "last_key": None, "lines": 0, "max": 120}


def _dlog(msg: str) -> None:
    if _diag["lines"] < _diag["max"]:
        _diag["lines"] += 1
        log("vehicle diag: " + msg)


def _name(obj) -> str:
    try:
        return obj.Name if obj is not None else "None"
    except Exception:  # noqa: BLE001
        return "?"


def _is_krieg(pc) -> bool:
    try:
        return pc.PlayerClass is not None and "Lilac" in pc.PlayerClass._path_name()
    except Exception:  # noqa: BLE001
        return False


def _krieg_and_vehicle(pc):
    """(Krieg's body, the vehicle, the seat pawn he directly controls). While driving, the
    controller possesses the vehicle (or a gunner-seat weapon pawn) and Krieg is its Driver."""
    p = pc.Pawn
    if p is None:
        return None, None, None
    driver = getattr(p, "Driver", None)
    if driver is not None:
        krieg, driven = driver, p
    else:
        krieg, driven = p, getattr(p, "DrivenVehicle", None)
    if driven is None:
        return krieg, None, None
    base = getattr(driven, "MyVehicle", None) or driven
    return krieg, base, driven


def _archetype(vehicle) -> str:
    try:
        return vehicle.ObjectArchetype.Name
    except Exception:  # noqa: BLE001
        return _name(vehicle)


def _axes(rot):
    """Unreal's rotation matrix rows (forward, right, up) for a rotator, including pitch and roll -
    on the Moon's slopes the buggy is rarely level, and yaw alone made the seat look like it moved."""
    k = math.pi / 32768.0
    p, y, r = rot.Pitch * k, rot.Yaw * k, rot.Roll * k
    sp, cp, sy, cy, sr, cr = math.sin(p), math.cos(p), math.sin(y), math.cos(y), math.sin(r), math.cos(r)
    return ((cp * cy, cp * sy, sp),
            (sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp),
            (-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp))


def _rel_tuple(vehicle, loc):
    d = (loc.X - vehicle.Location.X, loc.Y - vehicle.Location.Y, loc.Z - vehicle.Location.Z)
    return tuple(sum(a * b for a, b in zip(axis, d)) for axis in _axes(vehicle.Rotation))


def _local_offset(pawn, vehicle):
    try:
        f, r, u = _rel_tuple(vehicle, pawn.Location)
        return f"forward {f:.0f}, right {r:.0f}, up {u:.0f}"
    except Exception as ex:  # noqa: BLE001
        return f"? ({ex})"


def _playing(mesh):
    out = []
    addr = mesh._get_address()
    for node in unrealsdk.find_all("AnimNodeSequence", exact=False):
        try:
            sk = node.SkelComponent
            if sk is None or sk._get_address() != addr:
                continue
            w = float(node.NodeTotalWeight)
            if w < 0.05:
                continue
            seq = node.AnimSeq
            where = seq.Outer.Name if seq is not None else "NOT FOUND"
            out.append(f"{node.AnimSeqName}@{where} w{w:.2f}{' playing' if node.bPlaying else ''}")
        except Exception:  # noqa: BLE001
            continue
    return sorted(out)


def _rel(vehicle, loc) -> str:
    """A world position as forward/right/up from the vehicle's centre, in the vehicle's own frame."""
    f, r, u = _rel_tuple(vehicle, loc)
    return f"({f:.0f}, {r:.0f}, {u:.0f})"


_bones_logged: set = set()


def _pose_report(pawn, vehicle, seat: int) -> None:
    """Where Krieg's pelvis, head and hands are compared with the vehicle's seat sockets - shows
    whether he sits in the seat, floats above it, sinks into it or stands."""
    if seat in _bones_logged or seat < 0:
        return
    mesh = pawn.Mesh
    try:
        res = mesh.GetBoneNames([])
        names = [str(n) for n in (res[1] if isinstance(res, tuple) else res)]
    except Exception as ex:  # noqa: BLE001
        _dlog(f"  bones: could not list ({ex})")
        return
    _bones_logged.add(seat)
    wanted = [n for n in names if any(k in n.lower() for k in ("pelvis", "head", "hand", "foot", "spine3"))][:10]
    parts = []
    for n in wanted:
        try:
            loc = mesh.GetBoneLocation(n, 0)
            parts.append(f"{n} {_rel(vehicle, loc)}")
        except Exception:  # noqa: BLE001
            pass
    _dlog(f"  Krieg's bones (forward, right, up from the vehicle centre): {'; '.join(parts)}")
    try:
        sockets = []
        for sock in vehicle.Mesh.SkeletalMesh.Sockets:
            nm = str(sock.SocketName)
            if not any(k in nm.lower() for k in ("seat", "driver", "gunner", "passenger", "exit", "enter")):
                continue
            res = vehicle.Mesh.GetSocketWorldLocationAndRotation(
                nm, unrealsdk.make_struct("Vector"), unrealsdk.make_struct("Rotator"))
            loc = None
            for v in (res if isinstance(res, tuple) else (res,)):
                if hasattr(v, "X") and hasattr(v, "Z"):
                    loc = v
                    break
            if loc is not None:
                sockets.append(f"{nm} {_rel(vehicle, loc)}")
        _dlog(f"  vehicle seat sockets: {'; '.join(sockets) or 'none found'}")
    except Exception as ex:  # noqa: BLE001
        _dlog(f"  vehicle seat sockets: could not read ({type(ex).__name__}: {ex})")


def diagnose(force: bool = False, why: str = "") -> None:
    now = time.monotonic()
    if not force and now < _diag["next"]:
        return
    _diag["next"] = now + 2.0
    pc = get_pc()
    if pc is None or not _is_krieg(pc) or pc.Pawn is None:
        return
    pawn, vehicle, driven = _krieg_and_vehicle(pc)
    if pawn is None:
        return
    if vehicle is None:
        if _diag["last_key"] is not None:
            _diag["last_key"] = None
            _dlog(f"out of the vehicle {why}".strip())
        return
    arch = _archetype(vehicle)
    try:
        seat = int(vehicle.GetSeatIndexForController(pc))
    except Exception:  # noqa: BLE001
        seat = -1
    mesh = pawn.Mesh
    anims = _playing(mesh) if mesh is not None else []
    key = (arch, seat, tuple(a.split(" w")[0] for a in anims))
    if key == _diag["last_key"] and not force:
        return
    _diag["last_key"] = key
    body = _find("BodyClassDefinition", BODY)
    mapped = "none"
    try:
        for m in body.DLCVehicleAnimSetMappings:
            if str(m.VehicleArchetypeName) == arch:
                mapped = _name(m.AnimSet)
    except Exception:  # noqa: BLE001
        pass
    try:
        sets = [_name(s) for s in mesh.AnimSets]
    except Exception:  # noqa: BLE001
        sets = []
    try:
        extra = (f"physics {pawn.Physics}, base {_name(pawn.Base)}, hidden {pawn.bHidden}, "
                 f"mesh hidden {mesh.HiddenGame}, mesh offset {mesh.Translation.X:.0f},{mesh.Translation.Y:.0f},{mesh.Translation.Z:.0f}")
    except Exception as ex:  # noqa: BLE001
        extra = f"? ({ex})"
    _dlog(f"{why} vehicle {arch} ({_name(driven)}), seat {seat}, mapped anim set {mapped}; "
          f"Krieg is {_local_offset(pawn, vehicle)} from the vehicle; {extra}".strip())
    _dlog(f"  anim sets on Krieg: {sets}")
    _dlog(f"  playing: {anims or 'nothing'}")
    if any(a.startswith(("Driver_Idle", "Gunner_Idle")) for a in anims):
        try:
            _pose_report(pawn, vehicle, seat)
        except Exception as ex:  # noqa: BLE001
            _dlog(f"  pose report failed: {type(ex).__name__}: {ex}")


def _on_event(why):
    def cb(obj, *_):
        try:
            diagnose(force=True, why=why)
        except Exception as ex:  # noqa: BLE001
            _dlog(f"{why}: {type(ex).__name__}: {ex}")
    return cb


diag_hooks = [
    hook("Engine.Pawn:StartDriving", Type.POST, hook_identifier="KriegTPSVehStart")(_on_event("[got in]")),
    hook("Engine.Pawn:StopDriving", Type.POST, hook_identifier="KriegTPSVehStop")(_on_event("[got out]")),
    hook("WillowGame.WillowVehicle:ChangeSeat", Type.POST, hook_identifier="KriegTPSVehSeat")(_on_event("[changed seat]")),
]


# ---------------------------------------------------------------------------
# No standing-on-the-buggy flash when getting in.
# When Krieg gets into a seat (or spawns straight into a vehicle) the game attaches him first and
# switches to the seat animation a moment later; for that moment he stands upright in the seat,
# which puts him up at the turret. Two things fix it:
#  * his seat animation set is kept on his mesh all the time, so the seat animation is found at once;
#  * his body is hidden for a few frames right after he gets in or changes seats, until the seat
#    animation has taken over.
# ---------------------------------------------------------------------------
HIDE_MIN = 0.15      # never show him sooner than this
HIDE_MAX = 0.60      # ...or later than this, whatever the animation does
SEAT_ANIMS = ("Driver_", "Gunner_")
_hide = {"until": 0.0, "max": 0.0, "mesh": None, "nodes": [], "switching": 0.0, "since": 0.0}


def _krieg_body():
    pc = get_pc()
    if pc is None or not _is_krieg(pc):
        return None
    krieg, _, _ = _krieg_and_vehicle(pc)
    return krieg


def keep_seat_animset() -> None:
    krieg = _krieg_body()
    mesh = getattr(krieg, "Mesh", None) if krieg is not None else None
    animset = _find("AnimSet", RUNNER)
    if mesh is None or animset is None:
        return
    try:
        sets = mesh.AnimSets
        if any(s is not None and s._get_address() == animset._get_address() for s in sets):
            return
        sets.append(animset)
    except Exception as ex:  # noqa: BLE001
        _dlog(f"could not add the seat animations to Krieg's mesh: {type(ex).__name__}: {ex}")


def _my_vehicle_addrs() -> set:
    out = set()
    try:
        _, base, driven = _krieg_and_vehicle(get_pc())
        for v in (base, driven):
            if v is not None:
                out.add(v._get_address())
    except Exception:  # noqa: BLE001
        pass
    return out


def _seat_switch_starting(obj, *_) -> None:
    """ChangeSeat wraps the game's "get out of this seat + get into that one". The seat-switch
    animation covers that, so Krieg must not be hidden for it."""
    if obj is not None and obj._get_address() in _my_vehicle_addrs():
        _hide["switching"] = time.monotonic() + 1.0


def _seat_nodes(mesh) -> list:
    addr = mesh._get_address()
    nodes = []
    for node in unrealsdk.find_all("AnimNodeSequence", exact=False):
        try:
            sk = node.SkelComponent
            if sk is not None and sk._get_address() == addr:
                nodes.append(node)
        except Exception:  # noqa: BLE001
            continue
    return nodes


def _seat_anim_showing() -> bool:
    for node in _hide["nodes"]:
        try:
            if str(node.AnimSeqName).startswith(SEAT_ANIMS) and float(node.NodeTotalWeight) > 0.9:
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _hide_briefly(obj, *_) -> None:
    krieg = _krieg_body()
    mesh = getattr(krieg, "Mesh", None) if krieg is not None else None
    if mesh is None or obj is None:
        return
    # StartDriving runs on the pawn getting in - only act for Krieg himself, never AI drivers.
    if obj._get_address() != krieg._get_address():
        return
    now = time.monotonic()
    if now < _hide["switching"]:
        return
    try:
        mesh.SetHidden(True)
        _hide["since"] = now
        _hide["until"] = now + HIDE_MIN
        _hide["max"] = now + HIDE_MAX
        _hide["mesh"] = mesh
        _hide["nodes"] = _seat_nodes(mesh)
        _dlog("Krieg hidden while he sits down")
    except Exception as ex:  # noqa: BLE001
        _dlog(f"could not hide Krieg while seating: {type(ex).__name__}: {ex}")


def _show(mesh) -> bool:
    try:
        mesh.SetHidden(False)
    except Exception:  # noqa: BLE001
        pass
    try:
        if mesh.HiddenGame:
            mesh.HiddenGame = False
        return not mesh.HiddenGame
    except Exception:  # noqa: BLE001
        return True


def tick() -> None:
    """Called every frame: shows Krieg again once his seat animation has fully taken over (he is
    shown after HIDE_MAX regardless, so he can never stay invisible)."""
    mesh = _hide["mesh"]
    if mesh is None:
        return
    now = time.monotonic()
    if now < _hide["until"]:
        return
    seated = _seat_anim_showing()
    if not seated and now < _hide["max"]:
        return
    if not _show(mesh):
        _dlog("Krieg's body is still hidden after seating; trying again")
        return
    _hide["mesh"] = None
    _hide["nodes"] = []
    _dlog(f"Krieg shown again after seating ({now - _hide['since']:.2f}s, "
          f"{'seat animation playing' if seated else 'time limit'})")


def _unhide_now(*_) -> None:
    _hide["until"] = 0.0
    _hide["max"] = 0.0
    tick()


seat_hooks = [
    hook("WillowGame.WillowVehicle:ChangeSeat", Type.PRE, hook_identifier="KriegTPSSeatSwitch")(_seat_switch_starting),
    hook("Engine.Pawn:StartDriving", Type.PRE, hook_identifier="KriegTPSSeatHideIn")(_hide_briefly),
    hook("Engine.Pawn:StopDriving", Type.POST, hook_identifier="KriegTPSSeatShowOut")(_unhide_now),
]
