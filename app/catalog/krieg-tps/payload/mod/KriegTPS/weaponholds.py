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

import unrealsdk
from mods_base import ObjectFlags

KRIEG_BODY = "GD_Lilac_Psycho_Streaming.BodyClass_LilacPlayerClass"
KRIEG_RIFLE_HOLD = "GD_Lilac_Psycho_Streaming.WeaponHolds.WeaponHold_LilacPlayerClass_Rifle"
LASER_1P_HOLD = "GD_PlayerShared.WeaponHolds1st.WeaponHold_Player_Laser"
SHARED_BODY = "GD_PlayerShared.Character.BodyClass_PlayerShared"
NEW_3P_NAME = "WeaponHold_LilacPlayerClass_Laser"

_state = {"body": None, "logged_missing": False}


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
