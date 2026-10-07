"""Thrown Buzz Axe: faster clean-up and a real disintegration.

The thrown axe (GD_Lilac_SkillsBase.Buzzaxe.Projectile_Buzzaxe) runs this chain once it sticks:
    stop colliding --0.5s--> trail off --3.5s--> "DisappearSwitch" on (vanish particles) and the
    BuzzAxe_Dissolve effect --2s--> removed (ProjectileBehavior_Detonate_1)
so it lay there for ~6 seconds, and the Borderlands 2 burn-away shader it used doesn't exist in the
Pre-Sequel.

Here:
* the 3.5s wait and the 2s fade are shortened (STICK_SECONDS / FADE_SECONDS) by editing the delays
  in the projectile's behavior graph;
* when DisappearSwitch turns on, the axe's mesh gets its own material instances and the mod drives
  the Pre-Sequel gun shader's digistruct parameter (p_DigiStruct 0 -> 1.25, the same values the
  game's own Digistruct_Out_Weapon effect uses) while the axe shrinks away into the fire burst.
"""

import time

import unrealsdk
from mods_base import hook
from unrealsdk.hooks import Type

PROJECTILE = "GD_Lilac_SkillsBase.Buzzaxe.Projectile_Buzzaxe"
BPD = PROJECTILE + ".BehaviorProviderDefinition_0"
DISSOLVE_CE = "GD_Lilac_CE.CordinatedFX.BuzzAxe_Dissolve"
STICK_SECONDS = 0.75   # was 3.5: time stuck in the target before it starts to disappear
FADE_SECONDS = 0.8     # was 2.0: how long the disintegration takes
DIGI_PARAM = "p_DigiStruct"
DIGI_END = 1.25
MIN_SCALE = 0.05

_state = {"bpd": None, "logs": 0, "dlogs": 0}
_active: dict[int, dict] = {}
_thrown: dict[int, dict] = {}
# The game's chain after the axe sticks: 0.5s, then STICK_SECONDS, then the vanish starts and the
# axe is removed FADE_SECONDS later. The disintegration starts with the vanish.
STUCK_TO_DISINTEGRATE = 0.5 + STICK_SECONDS


def log(msg: str) -> None:
    from . import log as _log
    _log(msg)


def _find(cls: str, path: str):
    try:
        return unrealsdk.find_object(cls, path)
    except ValueError:
        return None


# ---------------------------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------------------------
def upkeep() -> None:
    bpd = _find("Object", BPD)
    if bpd is None or _state["bpd"] == bpd._get_address():
        return
    _state["bpd"] = bpd._get_address()
    changed = []
    try:
        seq = bpd.BehaviorSequences[0]
        behaviors = seq.BehaviorData2
        for link in seq.ConsolidatedOutputLinkData:
            target = int(link.LinkIdAndLinkedBehavior) & 0xFFFFFF
            name = behaviors[target].Behavior.Name if 0 <= target < len(behaviors) and behaviors[target].Behavior else ""
            delay = float(link.ActivateDelay)
            if name.startswith("Behavior_ChangeInstanceDataSwitch") and abs(delay - 3.5) < 0.01:
                link.ActivateDelay = STICK_SECONDS
                changed.append(f"wait before disappearing {delay:g}s -> {STICK_SECONDS:g}s")
            elif name == "ProjectileBehavior_Detonate_1" and abs(delay - 2.0) < 0.01:
                link.ActivateDelay = FADE_SECONDS
                changed.append(f"removal after fade {delay:g}s -> {FADE_SECONDS:g}s")
    except Exception as ex:  # noqa: BLE001
        log(f"buzz axe timing: {type(ex).__name__}: {ex}")
    ce = _find("Object", DISSOLVE_CE)
    if ce is not None:
        try:
            ce.EffectDuration = FADE_SECONDS
        except Exception:  # noqa: BLE001
            pass
    log(f"buzz axe timing: {'; '.join(changed) or 'no matching delays found'}")


# ---------------------------------------------------------------------------------------------
# Disintegration
# ---------------------------------------------------------------------------------------------
def _is_axe(proj) -> bool:
    try:
        d = proj.Definition
        return d is not None and d._path_name() == PROJECTILE
    except Exception:  # noqa: BLE001
        return False


def _is_disappear(proj, switch) -> bool:
    text = str(switch)
    if "Disappear" in text:
        return True
    try:
        idx = int(switch)
    except (TypeError, ValueError):
        return False
    try:
        atts = proj.Definition.BodyComposition.Attachments
        return 0 <= idx < len(atts) and str(atts[idx].Data.Name) == "DisappearSwitch"
    except Exception:  # noqa: BLE001
        return False


def _mesh(proj):
    for attr in ("MyMeshClone",):
        try:
            m = getattr(proj, attr)
            if m is not None:
                return m
        except Exception:  # noqa: BLE001
            pass
    try:
        return proj.GetMesh()
    except Exception:  # noqa: BLE001
        return None


def _start(proj) -> None:
    key = proj._get_address()
    if key in _active:
        return
    mesh = _mesh(proj)
    mics = []
    if mesh is not None:
        try:
            for i in range(int(mesh.GetNumElements())):
                mic = mesh.CreateAndSetMaterialInstanceConstant(i)
                if mic is not None:
                    mics.append(mic)
        except Exception as ex:  # noqa: BLE001
            log(f"buzz axe disintegrate: could not make material instances: {type(ex).__name__}: {ex}")
    try:
        scale = float(proj.DrawScale) or 1.0
    except Exception:  # noqa: BLE001
        scale = 1.0
    _active[key] = {"proj": proj, "mesh": mesh, "mics": mics, "start": time.monotonic(), "scale": scale}
    if _state["dlogs"] < 6:
        _state["dlogs"] += 1
        log(f"buzz axe disintegrating ({len(mics)} material slots, mesh {mesh.Name if mesh else None})")


def _track(proj, why: str) -> None:
    """Remember a thrown axe from the moment it exists; tick() watches for it to stick."""
    if proj is None or not _is_axe(proj):
        return
    key = proj._get_address()
    if key in _thrown or key in _active:
        return
    _thrown[key] = {"proj": proj, "seen": time.monotonic(), "stuck": None, "last": None}
    if _state["logs"] < 6:
        _state["logs"] += 1
        log(f"buzz axe thrown ({why})")


def _hook_spawn(name: str, ident: str):
    def cb(obj, *_):
        try:
            _track(obj, name.split(":")[-1])
        except Exception as ex:  # noqa: BLE001
            log(f"buzz axe {name}: {type(ex).__name__}: {ex}")
    return hook(name, Type.POST, hook_identifier=ident)(cb)


@hook("WillowGame.WillowProjectile:ChangeInstanceDataSwitch", Type.POST, hook_identifier="KriegTPSAxeSwitch")
def on_switch(obj, args, *_):
    try:
        if not _is_axe(obj):
            return
        _track(obj, "switch")
        if int(args.NewValue) == 1 and _is_disappear(obj, args.Switch):
            _thrown.pop(obj._get_address(), None)
            _start(obj)
    except Exception as ex:  # noqa: BLE001
        log(f"buzz axe switch hook: {type(ex).__name__}: {ex}")


def _speed(proj) -> float:
    v = proj.Velocity
    return (v.X * v.X + v.Y * v.Y + v.Z * v.Z) ** 0.5


def _watch_thrown(now: float) -> None:
    """An axe counts as stuck once it is attached or stops moving. The game removes it
    STUCK_TO_REMOVAL seconds later; the disintegration is timed to end right then."""
    for key in list(_thrown):
        e = _thrown[key]
        proj = e["proj"]
        try:
            loc = proj.Location
            here = (loc.X, loc.Y, loc.Z)
            moved = e["last"] is None or sum((a - b) ** 2 for a, b in zip(here, e["last"])) > 1.0
            e["last"] = here
            attached = bool(getattr(proj, "bIsProjectileAttached", False))
            if e["stuck"] is None and (attached or (not moved and _speed(proj) < 5.0 and now - e["seen"] > 0.1)):
                e["stuck"] = now
            if e["stuck"] is not None and now - e["stuck"] >= STUCK_TO_DISINTEGRATE:
                del _thrown[key]
                _start(proj)
            elif now - e["seen"] > 20.0:
                del _thrown[key]
        except Exception:  # noqa: BLE001 - gone
            _thrown.pop(key, None)


def _animate(now: float) -> None:
    """Drives each disintegrating axe: the digistruct shader parameter climbs to DIGI_END while
    the axe shrinks, over FADE_SECONDS."""
    for key in list(_active):
        e = _active[key]
        t = (now - e["start"]) / FADE_SECONDS
        try:
            proj = e["proj"]
            if t >= 1.0 or proj is None or getattr(proj, "bDeleteMe", False):
                del _active[key]
                continue
            for mic in e["mics"]:
                mic.SetScalarParameterValue(DIGI_PARAM, DIGI_END * t)
            proj.SetDrawScale(max(MIN_SCALE, e["scale"] * (1.0 - t)))
        except Exception:  # noqa: BLE001 - the axe is gone
            _active.pop(key, None)


def tick() -> None:
    """Called every frame (the mod's PlayerTick and viewport hooks)."""
    if not _thrown and not _active:
        return
    now = time.monotonic()
    _watch_thrown(now)
    _animate(now)


axe_hooks = [
    on_switch,
    _hook_spawn("WillowGame.WillowProjectile:DoOnSpawn", "KriegTPSAxeSpawn1"),
    _hook_spawn("WillowGame.WillowProjectile:InitializeFromDefinition", "KriegTPSAxeSpawn2"),
    _hook_spawn("WillowGame.WillowProjectile:PostBeginPlay", "KriegTPSAxeSpawn3"),
]
