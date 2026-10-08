"""Krieg speaks when he's picked at character select, like the Pre-Sequel's own Vault Hunters.

Each Pre-Sequel character's body class names a "MenuSelectDialog" sound event that the character
select screen plays (PlayCharacterSelectDialog). Borderlands 2 had no such line, so Krieg's is empty.
Right before the screen plays it, one of his own recorded Borderlands 2 voice events is chosen at
random (never the same one twice in a row). Each of those events is itself a set of recorded takes
that Wwise picks from at random: rampage cries, idle rants, kill taunts, inner-voice moments and
laughter.
"""

import random

import unrealsdk
from mods_base import ObjectFlags, hook
from unrealsdk.hooks import Type

KRIEG_BODY = "GD_Lilac_Psycho_Streaming.BodyClass_LilacPlayerClass"
_VOBD = "Ake_Lilac_VOBD.Ak_Play_VOBD_Lilac_PlayPsycho_PL_"
EVENTS = tuple(_VOBD + n for n in (
    "Start_Action_Skill",
    "CO_Idle",
    "Generic_Laughter",
    "React_Kill_Streak",
    "React_Skill_Kill",
    "React_Gib_Enemy",
    "Start_BloodlustFirst",
    "Start_BloodlustSecond",
    "Start_BloodlustThird",
    "Start_PsychoticFit",
    "React_HitSelf_Sane",
    "CO_Enter_CoOp_Game",
    "Start_ElFrenzy",
))

_state = {"last": None, "logs": 0}


def log(msg: str) -> None:
    from . import log as _log
    _log(msg)


def _find(path: str):
    try:
        return unrealsdk.find_object("AkEvent", path)
    except ValueError:
        return None


def _pick():
    found = [e for e in (_find(p) for p in EVENTS) if e is not None]
    if not found:
        return None
    choices = [e for e in found if e._path_name() != _state["last"]] or found
    ev = random.choice(choices)
    _state["last"] = ev._path_name()
    return ev


def _ui_sound_manager():
    try:
        return unrealsdk.find_class("WorldSoundManager").ClassDefaultObject
    except Exception:  # noqa: BLE001
        return None


# Ways to post the event, most suitable first. A plain PlayAkEvent on the player controller ran
# without error but stayed silent: his voice lines are 3D sounds, and at the menu the controller
# sits nowhere near the camera, so the line faded out by distance. The UI paths play it flat (2D),
# the way the menus play their own sounds.
METHODS = {
    "ui": lambda pc, ev: pc.PlayUIAkEvent(ev),
    "world": lambda pc, ev: _ui_sound_manager().StaticPlayUIAkEvent(ev),
    "pawn": lambda pc, ev: pc.Pawn.PlayAkEvent(ev),
    "pc": lambda pc, ev: pc.PlayAkEvent(ev),
}
ORDER = ("ui", "world", "pawn", "pc")


def _play(ev, only: str | None = None) -> str:
    from mods_base import get_pc
    pc = get_pc()
    if pc is None:
        return "no player controller"
    last = "nothing tried"
    for name in ((only,) if only else ORDER):
        try:
            result = METHODS[name](pc, ev)
            return f"played with {name}" + (f" -> {result}" if result is not None else "")
        except Exception as ex:  # noqa: BLE001
            last = f"{name}: {type(ex).__name__}: {ex}"
    return last


@hook("WillowGame.CharacterSelectionReduxGFxMovie:PlayCharacterSelectDialog", Type.PRE,
      hook_identifier="KriegTPSSelectVoice")
def on_select_dialog(obj, args, *_):
    try:
        body = args.BodyClass
        if body is None or body._path_name() != KRIEG_BODY:
            return
        ev = _pick()
        if ev is None:
            if _state["logs"] < 3:
                _state["logs"] += 1
                log("character select voice: none of Krieg's voice events are loaded")
            return
        ev.ObjectFlags |= ObjectFlags.KEEP_ALIVE
        # The screen's own path stayed silent for Krieg (set as his MenuSelectDialog, nothing was
        # heard), so the line is played directly as a flat (2D) UI sound.
        body.MenuSelectDialog = None
        result = _play(ev)
        if _state["logs"] < 10:
            _state["logs"] += 1
            log(f"character select voice: {ev.Name} ({result})")
    except Exception as ex:  # noqa: BLE001
        log(f"character select voice failed: {type(ex).__name__}: {ex}")


def upkeep() -> None:
    """Keeps Krieg's voice events in memory once his class has loaded."""
    try:
        body = unrealsdk.find_object("BodyClassDefinition", KRIEG_BODY)
    except ValueError:
        return
    if _state.get("kept"):
        return
    found = 0
    for path in EVENTS:          # keep his voice events loaded for the menu
        ev = _find(path)
        if ev is not None:
            ev.ObjectFlags |= ObjectFlags.KEEP_ALIVE
            found += 1
    _state["kept"] = found == len(EVENTS)


from mods_base import command  # noqa: E402


TPS_TEST_EVENT = "Ake_Cork_VOBD.Cork_VOBD_PL_Gladiator.Ak_Play_VOBD_Cork_Gladiator_PL_Menu_Select"


@command("krieg_voice", description="Sound test for Krieg's character select line. "
         "Optional: a method (ui, world, pawn, pc) and/or 'tps' to play Athena's menu line instead.")
def krieg_voice(args) -> None:
    words = [w.lower() for w in (getattr(args, "words", None) or [])]
    only = next((w for w in words if w in METHODS), None)
    if "tps" in words:
        ev = _find(TPS_TEST_EVENT)
        name = "Athena's menu line" if ev else "Athena's menu line (not loaded)"
    else:
        ev = _pick()
        name = ev.Name if ev else "no voice events loaded"
    log(f"krieg_voice: {name}" + (f" ({_play(ev, only)})" if ev else ""))


krieg_voice.add_argument("words", nargs="*")


voice_hooks = [on_select_dialog, krieg_voice]
