"""Krieg speaks when he's picked at character select, like the Pre-Sequel's own Vault Hunters.

Each Pre-Sequel character's body class names a "MenuSelectDialog" sound event that the character
select screen plays (PlayCharacterSelectDialog). Borderlands 2 had no such line, so Krieg's is empty.
Right before the screen plays it, one of his own recorded Borderlands 2 voice events is chosen at
random (never the same one twice in a row). Each of those events is itself a set of recorded takes
that Wwise picks from at random: rampage cries, idle rants, kill taunts, inner-voice moments and
laughter.

Borderlands 2 routes his voice through the Pre-Sequel's gameplay voice buses, which are silent at
the menus (the Pre-Sequel's own select lines use a separate menu voice bus). The launcher adds a
"_Menu" copy of each of these events to his voice bank, routed to that menu bus; the matching
events are posted by swapping in the copy's ID for the moment of the call.
"""

import random
import time

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


def _fnv(name: str) -> int:
    h = 2166136261
    for c in name.lower().encode():
        h = (h * 16777619) & 0xFFFFFFFF
        h ^= c
    return h - (1 << 32) if h >= 1 << 31 else h


_offset = {"value": None}


def _wwise_id(ev) -> int:
    name = ev.Name
    return _fnv(name[3:] if name.startswith("Ak_") else name)


def _id_offset(ev):
    """Where the event keeps its Wwise ID in memory (the Pre-Sequel doesn't expose it to scripts)."""
    if _offset["value"] is not None:
        return _offset["value"]
    import ctypes
    want = _wwise_id(ev)
    base = ev._get_address()
    hits = [o for o in range(0x3C, 0x100, 4) if ctypes.c_int32.from_address(base + o).value == want]
    if len(hits) != 1:
        raise RuntimeError(f"found the event ID at {len(hits)} places")
    # check the same spot on another of his events
    for other in (e for e in (_find(p) for p in EVENTS) if e is not None and e is not ev):
        if ctypes.c_int32.from_address(other._get_address() + hits[0]).value != _wwise_id(other):
            raise RuntimeError("event ID offset differs between events")
        break
    _offset["value"] = hits[0]
    log(f"character select voice: event ID kept at +0x{hits[0]:X}")
    return hits[0]


def _play_menu(ev, only: str | None = None) -> str:
    """Posts the menu copy of the event (its ID + '_Menu'), routed to the menu voice bus."""
    import ctypes
    slot = ctypes.c_int32.from_address(ev._get_address() + _id_offset(ev))
    original = slot.value
    slot.value = _fnv(ev.Name[3:] + "_Menu")
    try:
        return _play(ev, only) + " [menu copy]"
    finally:
        slot.value = original


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
ORDER = ("world", "ui", "pawn", "pc")


def _play(ev, only: str | None = None) -> str:
    from mods_base import get_pc
    pc = get_pc()
    if pc is None:
        return "no player controller"
    last = "nothing tried"
    for name in ((only,) if only else ORDER):
        try:
            result = METHODS[name](pc, ev)
            try:
                _state["playing"] = (result.SourceComponent, result.AkPlayingId)
                _state["played_at"] = time.monotonic()
            except Exception:  # noqa: BLE001
                _state["playing"] = None
            return f"played with {name}" + (f" -> {result}" if result is not None else "")
        except Exception as ex:  # noqa: BLE001
            last = f"{name}: {type(ex).__name__}: {ex}"
    return last


@hook("WillowGame.CharacterSelectionReduxGFxMovie:PlayCharacterSelectDialog", Type.PRE,
      hook_identifier="KriegTPSSelectVoice")
def on_select_dialog(obj, args, *_):
    try:
        body = args.BodyClass
        _state["current"] = body._path_name() if body is not None else None
        _state["pending"] = False
        if body is None or body._path_name() != KRIEG_BODY:
            return
        # The screen also "selects" the last-played character when it opens; only speak when the
        # player actually picked him (a click or a key/pad press shortly before).
        if time.monotonic() - _state.get("input_at", -99.0) > INPUT_WINDOW:
            return
        _say(body)
    except Exception as ex:  # noqa: BLE001
        log(f"character select voice failed: {type(ex).__name__}: {ex}")


def _still_talking() -> bool:
    info = _state.get("playing")
    if not info:
        return False
    comp, pid = info
    if time.monotonic() - _state.get("played_at", 0.0) > 12.0:   # no line of his is this long
        return False
    try:
        return bool(comp.IsPlayingId(pid))
    except Exception:  # noqa: BLE001
        return False


def _selected_index(obj) -> int:
    sel = obj.SelectedCharacterIndex
    try:
        return int(sel)
    except TypeError:
        return int(sel[0])


INPUT_WINDOW = 6.0     # seconds between the player's click/press and the screen's select call


@hook("WillowGame.CharacterSelectionReduxGFxMovie:HandleChooseCharacterInput", Type.PRE,
      hook_identifier="KriegTPSSelectVoiceInput")
def on_choose_input(obj, args, *_):
    # Only key/pad presses: releasing the key that opened the screen also lands here, and that
    # made him talk as soon as the screen opened.
    ev = args.Event
    name = getattr(ev, "name", str(ev))
    if name.endswith("IE_Pressed") or name.endswith("IE_Repeat") or ev in (0, 2):
        _state["input_at"] = time.monotonic()


@hook("WillowGame.CharacterSelectionReduxGFxMovie:OnClose", Type.PRE,
      hook_identifier="KriegTPSSelectVoiceClose")
def on_select_close(*_):
    _state["pending"] = False
    _state["current"] = None


@hook("WillowGame.CharacterSelectionReduxGFxMovie:HandleCharacterClicked", Type.PRE,
      hook_identifier="KriegTPSSelectVoiceReclick")
def on_character_clicked(obj, args, *_):
    """The game only speaks when the selection changes; clicking Krieg again gets a new line too.
    A click while he's still talking queues the next line, which starts as soon as he finishes."""
    _state["input_at"] = time.monotonic()
    try:
        if _state.get("current") != KRIEG_BODY or args.CharacterIndex != _selected_index(obj):
            return
        if _still_talking():
            _state["pending"] = True
            return
        _say(unrealsdk.find_object("BodyClassDefinition", KRIEG_BODY))
    except Exception as ex:  # noqa: BLE001
        log(f"character select voice (click again) failed: {type(ex).__name__}: {ex}")


def _say(body) -> None:
    try:
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
        try:
            result = _play_menu(ev)
        except Exception as ex:  # noqa: BLE001
            result = f"menu copy failed ({type(ex).__name__}: {ex}); " + _play(ev)
        if _state["logs"] < 10:
            _state["logs"] += 1
            log(f"character select voice: {ev.Name} ({result})")
    except Exception as ex:  # noqa: BLE001
        log(f"character select voice failed: {type(ex).__name__}: {ex}")


def tick() -> None:
    """Plays a queued line once the current one has finished (per frame, cheap when idle)."""
    if not _state.get("pending") or _still_talking():
        return
    _state["pending"] = False
    if _state.get("current") != KRIEG_BODY:
        return
    try:
        _say(unrealsdk.find_object("BodyClassDefinition", KRIEG_BODY))
    except ValueError:
        pass


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
         "Optional: a method (world, ui, pawn, pc), 'orig' for the gameplay version, "
         "or 'tps' to play a Pre-Sequel menu line instead.")
def krieg_voice(args) -> None:
    words = [w.lower() for w in (getattr(args, "words", None) or [])]
    only = next((w for w in words if w in METHODS), None)
    if "tps" in words:
        ev = _find(TPS_TEST_EVENT) or next(
            (e for e in unrealsdk.find_all("AkEvent", exact=False) if "Menu_Select" in e.Name), None)
        name = f"Pre-Sequel menu line {ev.Name}" if ev else "no Pre-Sequel menu line loaded"
    else:
        ev = _pick()
        menu = ev is not None and "orig" not in words
        name = ev.Name if ev else "no voice events loaded"
        if menu:
            log(f"krieg_voice: {name} ({_play_menu(ev, only)})")
            return
    log(f"krieg_voice: {name}" + (f" ({_play(ev, only)})" if ev else ""))


krieg_voice.add_argument("words", nargs="*")


voice_hooks = [on_select_dialog, on_character_clicked, on_choose_input, on_select_close, krieg_voice]
