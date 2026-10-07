"""Pre-Sequel player events for Krieg (Oz kit sounds and effects, butt slam).

Each Pre-Sequel character has a "player events" behaviour list that plays the Oz kit effects:
the air-boost sound and particles (OnAirBoostEffects), the butt-slam hit (DoSlamEffects), and the
oxygen / vacuum notifications (entering and leaving vacuum, oxygen low, depleted, refilled).
Krieg's list comes from Borderlands 2 and has none of these, so boosting was silent.

This copies those sequences from Aurelia's list into Krieg's. Her own skill sequence (Contract)
and her helmet (AirMask_ON / AirMask_OFF) are left out. Her list is kept loaded so the copied
sequences keep working after her character package is unloaded with the level.
"""

import unrealsdk
from mods_base import ObjectFlags

KRIEG_EVENTS = "GD_Lilac_Psycho_Streaming.PlayerEvents_LilacPlayerClass.BehaviorProviderDefinition_0"
AURELIA_EVENTS = "Crocus_Baroness_Streaming.PlayerEvents_Baroness.BehaviorProviderDefinition_0"
# Aurelia sequence -> name it gets in Krieg's list
COPY = {"Default": "TPS_OzEvents", "Slam": "Slam"}
# The air-boost sound is played directly from the boost itself (below): sequences added to an
# already-spawned character are not picked up by the game, so the copied AirBoost sequence stayed
# silent.

_state = {"aurelia": None, "logged": set()}


def log(msg: str) -> None:
    from . import log as _log
    _log(msg)


def _find(path: str):
    try:
        return unrealsdk.find_object("BehaviorProviderDefinition", path)
    except ValueError:
        return None


def upkeep() -> None:
    """Disabled: copying Aurelia's event sequences into Krieg's crashed the game when switching
    to Aurelia afterwards (her package reloaded over objects Krieg still referenced), and the
    copies were added too late to take effect anyway. The boost sound is played directly below."""
    return


# ---------------------------------------------------------------------------
# Air boost sound, played directly when Krieg boosts.
# ---------------------------------------------------------------------------
import time as _time  # noqa: E402

from mods_base import get_pc, hook  # noqa: E402
from unrealsdk.hooks import Type  # noqa: E402

BOOST_START = "Ake_Cork_FX_Global.AirBoost.Ak_Play_Cork_FX_AirBoost_Boost"
BOOST_END = "Ake_Cork_FX_Global.AirBoost.Ak_Play_Cork_FX_AirBoost_End"
_boost = {"last": 0.0, "logged": set()}


def _is_krieg(pc) -> bool:
    try:
        cls = pc.PlayerClass
        return cls is not None and "Lilac" in cls._path_name()
    except Exception:  # noqa: BLE001
        return False


def _is_local_krieg(pc) -> bool:
    local = get_pc()
    return local is not None and pc._get_address() == local._get_address() and _is_krieg(pc)


def _play(pc, event_path: str, why: str) -> None:
    pawn = pc.Pawn if pc is not None else None
    if pawn is None:
        return
    try:
        event = unrealsdk.find_object("AkEvent", event_path)
    except ValueError:
        event = None
    if event is None:
        if event_path not in _boost["logged"]:
            _boost["logged"].add(event_path)
            log(f"Oz kit: sound {event_path} is not loaded")
        return
    try:
        pawn.PostAkEvent(event)
    except Exception as ex:  # noqa: BLE001
        try:
            pawn.PlayAkEvent(event)
        except Exception:  # noqa: BLE001
            if why not in _boost["logged"]:
                _boost["logged"].add(why)
                log(f"Oz kit: could not play the boost sound: {type(ex).__name__}: {ex}")
            return
    if why not in _boost["logged"]:
        _boost["logged"].add(why)
        log(f"Oz kit: playing the air-boost sound for Krieg ({why})")


def _on_begin(obj, *_):
    pc = obj
    if not _is_local_krieg(pc):
        return
    now = _time.monotonic()
    if now - _boost["last"] < 0.3:
        return  # LocalBeginAirBoost and BeginAirBoost both fire for one boost
    _boost["last"] = now
    _play(pc, BOOST_START, "start")


def _on_end(obj, *_):
    pc = obj
    if not _is_local_krieg(pc):
        return
    _play(pc, BOOST_END, "end")


boost_hooks = [
    hook("WillowGame.WillowPlayerController:LocalBeginAirBoost", Type.PRE,
         hook_identifier="KriegTPSBoostLocal")(lambda obj, *a: _on_begin(obj, *a)),
    hook("WillowGame.WillowPlayerController:BeginAirBoost", Type.PRE,
         hook_identifier="KriegTPSBoost")(lambda obj, *a: _on_begin(obj, *a)),
    hook("WillowGame.WillowPlayerController:EndAirBoost", Type.PRE,
         hook_identifier="KriegTPSBoostEnd")(lambda obj, *a: _on_end(obj, *a)),
]
