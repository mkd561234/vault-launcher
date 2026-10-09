"""Laser animations for Krieg (Splitter, Rail, Beam, Blaster... every Pre-Sequel laser).

How a character holds a gun comes from his body class: a list of "weapon holds" picked by the gun
type's hold name ("Pistol", "Rifle", "Laser"...), each with the animation sets to play.
* First person: Krieg's hands share the Pre-Sequel's player hands rig, and the Pre-Sequel has a
  shared first-person "Laser" hold (GD_PlayerShared...WeaponHold_Player_Laser, animations
  Anim_Co_1st_Person.1st_Person_Laser). Krieg comes from Borderlands 2, where neither exists, and
  his body class only falls back to the shared hold list that is in memory - Borderlands 2's copy,
  without lasers once his own package has replaced the Pre-Sequel one. So lasers played the
  generic hold: wrong grip, no reload or fire animations.
* Third person (what co-op partners see): his body class has no "Laser" hold at all.

Fix: give his body class the Pre-Sequel's first-person Laser hold (loaded from Aurelia's package,
which the mod already uses for his materials), and a third-person Laser hold made from his own
rifle hold, so his body animations come from his own skeleton.
"""

from pathlib import Path

import unrealsdk
from mods_base import ObjectFlags, command

KRIEG_BODY = "GD_Lilac_Psycho_Streaming.BodyClass_LilacPlayerClass"
KRIEG_RIFLE_HOLD = "GD_Lilac_Psycho_Streaming.WeaponHolds.WeaponHold_LilacPlayerClass_Rifle"
LASER_1P_HOLD = "GD_PlayerShared.WeaponHolds1st.WeaponHold_Player_Laser"
SHARED_BODY = "GD_PlayerShared.Character.BodyClass_PlayerShared"
NEW_3P_NAME = "WeaponHold_LilacPlayerClass_Laser"

_state = {"body": None, "logged_missing": False, "wilhelm_body": None, "wilhelm_tried": False, "orig": {}}

# Third-person gun animations from Wilhelm (the Pre-Sequel's Enforcer). Krieg is from Borderlands 2,
# where he holds every gun with one set of rifle animations and has nothing for lasers. Wilhelm's
# body uses the same bones as Krieg's (Root, Hips, Spine1-3, arms, weapon bones, legs), so his
# per-gun animations play on Krieg: his pistol, rifle (rifles, SMGs, shotguns, snipers), rocket
# launcher and laser holds, with their left-hand grip and reloads. Krieg keeps his own walk/run and
# his own aiming (his body's aim profile); Krieg's own animations stay underneath, so anything
# Wilhelm's set doesn't have still plays Krieg's. krieg_holds krieg puts Krieg's own holds back.
WILHELM_PACKAGE = "GD_Enforcer_Streaming_SF"
WILHELM_HOLD = "GD_Enforcer_Streaming.WeaponHolds.WeaponHold_Enforcer_{}"
WILHELM_HOLDS = ("Pistol", "Rifle", "SMG", "Shotgun", "SniperRifle", "RocketLauncher", "Laser")
SETTING = Path(__file__).with_name("gun_holds.txt")


def _style() -> str:
    try:
        return "krieg" if SETTING.read_text().strip().lower() == "krieg" else "wilhelm"
    except OSError:
        return "wilhelm"


def log(msg: str) -> None:
    from . import log as _log
    _log(msg)


def _find(cls: str, path: str):
    try:
        return unrealsdk.find_object(cls, path)
    except ValueError:
        return None


def _keep(obj) -> None:
    obj.ObjectFlags |= ObjectFlags.KEEP_ALIVE
    try:
        for s in obj.AnimSetList:
            if s is not None:
                s.ObjectFlags |= ObjectFlags.KEEP_ALIVE
    except Exception:  # noqa: BLE001
        pass


def _has(holds, name: str) -> bool:
    return any(h is not None and str(h.HoldName) == name for h in holds)


def _laser_1p():
    hold = _find("BodyWeaponHoldDefinition", LASER_1P_HOLD)
    if hold is None:
        from . import materials
        materials._get_template(materials.TEMPLATE_BODY)   # loads Aurelia's package once
        hold = _find("BodyWeaponHoldDefinition", LASER_1P_HOLD)
    return hold


def upkeep() -> None:
    body = _find("BodyClassDefinition", KRIEG_BODY)
    if body is None:
        return
    address = body._get_address()
    if _state["body"] == address:
        return
    done = []
    # first person
    hold = _laser_1p()
    if hold is None:
        if not _state["logged_missing"]:
            _state["logged_missing"] = True
            log("lasers: the Pre-Sequel's first-person laser hold isn't loaded yet")
        return
    _keep(hold)
    if not _has(body.FirstPersonWeaponHoldDefs, "Laser"):
        body.FirstPersonWeaponHoldDefs.append(hold)
        done.append("first-person laser hold")
    shared = _find("BodyClassDefinition", SHARED_BODY)
    if shared is not None and not _has(shared.FirstPersonWeaponHoldDefs, "Laser"):
        shared.FirstPersonWeaponHoldDefs.append(hold)
        done.append("shared first-person laser hold")
    # third person
    if not _has(body.WeaponHoldDefs, "Laser"):
        rifle = _find("BodyWeaponHoldDefinition", KRIEG_RIFLE_HOLD)
        if rifle is not None:
            laser3 = _find("BodyWeaponHoldDefinition", f"{rifle.Outer._path_name()}.{NEW_3P_NAME}")
            if laser3 is None:
                laser3 = unrealsdk.construct_object("BodyWeaponHoldDefinition", rifle.Outer, NEW_3P_NAME,
                                                    template_obj=rifle)
            laser3.HoldName = "Laser"
            _keep(laser3)
            body.WeaponHoldDefs.append(laser3)
            done.append("third-person laser hold (from his rifle hold)")
    _state["body"] = address
    if done:
        log(f"lasers: Krieg now has {', '.join(done)}")
    _state["wilhelm_body"] = None      # his body class was (re)loaded: put Wilhelm's holds in again


def upkeep_all() -> None:
    upkeep()
    apply_wilhelm()


def _wilhelm_hold(name: str):
    hold = _find("BodyWeaponHoldDefinition", WILHELM_HOLD.format(name))
    if hold is None and not _state["wilhelm_tried"]:
        _state["wilhelm_tried"] = True
        try:
            unrealsdk.load_package(WILHELM_PACKAGE)
        except Exception as ex:  # noqa: BLE001
            log(f"gun holds: could not load Wilhelm's animations ({WILHELM_PACKAGE}): {ex}")
            return None
        hold = _find("BodyWeaponHoldDefinition", WILHELM_HOLD.format(name))
    return hold


def _krieg_copy(body, name: str, wil):
    """A copy of Wilhelm's hold for Krieg: Wilhelm's gun animations on top of Krieg's own set,
    with Krieg's aim profile (his animation tree only knows his own)."""
    holds = list(body.WeaponHoldDefs)
    mine = next((h for h in holds if h is not None and str(h.HoldName) == name
                 and not str(h.Name).endswith("_Wilhelm")), None)
    if mine is None:
        mine = _state["orig"].get(name)
    outer = mine.Outer if mine is not None else body.Outer
    path = f"{outer._path_name()}.WeaponHold_LilacPlayerClass_{name}_Wilhelm"
    new = _find("BodyWeaponHoldDefinition", path)
    if new is None:
        new = unrealsdk.construct_object("BodyWeaponHoldDefinition", outer,
                                         f"WeaponHold_LilacPlayerClass_{name}_Wilhelm", template_obj=wil)
    sets = []
    for src in ((mine.AnimSetList if mine is not None else []), wil.AnimSetList):
        for a in src:
            if a is not None and all(a._get_address() != b._get_address() for b in sets):
                sets.append(a)
    new.AnimSetList = sets
    new.HoldName = name
    if mine is not None:
        new.AimOffsetProfileName = mine.AimOffsetProfileName
    else:
        new.AimOffsetProfileName = "Psycho"
    _keep(new)
    return mine, new


def apply_wilhelm(force: bool = False) -> None:
    body = _find("BodyClassDefinition", KRIEG_BODY)
    if body is None:
        return
    address = body._get_address()
    if not force and _state["wilhelm_body"] == address:
        return
    style = _style()
    holds = list(body.WeaponHoldDefs)
    changed = []
    if style == "krieg":
        for i, h in enumerate(holds):
            if h is not None and str(h.Name).endswith("_Wilhelm"):
                orig = _state["orig"].get(str(h.HoldName))
                if orig is not None:
                    holds[i] = orig
                    changed.append(str(h.HoldName))
        if changed:
            body.WeaponHoldDefs = holds
            log(f"gun holds: Krieg's own animations back for {', '.join(changed)}")
        _state["wilhelm_body"] = address
        return
    for name in WILHELM_HOLDS:
        wil = _wilhelm_hold(name)
        if wil is None:
            continue
        _keep(wil)
        mine, new = _krieg_copy(body, name, wil)
        if mine is not None:
            _state["orig"][name] = mine
        for i, h in enumerate(holds):
            if h is not None and str(h.HoldName) == name:
                if h._get_address() != new._get_address():
                    holds[i] = new
                    changed.append(name)
                break
        else:
            holds.append(new)
            changed.append(name)
    if changed:
        body.WeaponHoldDefs = holds
        log(f"gun holds: Krieg now uses Wilhelm's third-person animations for {', '.join(changed)}")
    elif _state["wilhelm_body"] != address:
        log("gun holds: Wilhelm's animations aren't available; Krieg keeps his own")
    _state["wilhelm_body"] = address


@command("krieg_holds", description="Krieg's third-person gun animations: 'wilhelm' (default) or 'krieg' (his own).")
def krieg_holds(args) -> None:
    want = (getattr(args, "style", "") or "").strip().lower()
    if want in ("wilhelm", "krieg"):
        try:
            SETTING.write_text(want)
        except OSError as ex:
            log(f"gun holds: could not save the setting: {ex}")
        apply_wilhelm(force=True)
        log(f"gun holds: now '{want}' (switch weapons to see it)")
    else:
        log(f"gun holds: currently '{_style()}'. Use krieg_holds wilhelm or krieg_holds krieg")


krieg_holds.add_argument("style", nargs="?", default="")
hold_hooks = [krieg_holds]
