"""Co-op: other players see the heads and skins Krieg gets from Borderlands 2's other DLCs.

The game tells the other players which head and skin each player wears by sending the definition
object itself. That works for Krieg's own heads/skins (they are stored in his DLC package), but
the ones from Borderlands 2's other DLCs (the Scav, Lobelia, holiday ones...) are created by this
mod when the game starts, so they can't be sent - the other game receives "nothing" and shows
the default head and skin.

Every player in a Krieg co-op game runs this mod, so the mod sends the names along itself:
* a joining player tells the host with an unused server command (ServerMutate);
* the host keeps a table of everyone's DLC heads/skins and sends it to every joining player with
  a hidden client message (never shown in the chat);
* each game then puts that head/skin on the player's Krieg itself, and again whenever he respawns.
"""

import time

import unrealsdk
from mods_base import get_pc, hook
from unrealsdk.hooks import Block, Type

PREFIX = "KTPS|CUST|"
SLOTS = {0: "Head", 4: "Skin"}        # index in the player's customization list
DEF_OUTER = "GD_AllCustoms_Lilac.Psycho."

_state = {"next": 0.0, "mine": None, "sent_to": {}, "logs": 0}
_table: dict[str, dict[int, str]] = {}      # player name -> {slot: definition name}


def log(msg: str) -> None:
    if _state["logs"] >= 40:
        return
    _state["logs"] += 1
    from . import log as _log
    _log("co-op heads/skins: " + msg)


def _extra_names() -> set:
    from . import EXTRA_CUSTOMIZATIONS
    return {e[0] for e in EXTRA_CUSTOMIZATIONS}


def _def(name: str):
    try:
        return unrealsdk.find_object("CustomizationDefinition", DEF_OUTER + name)
    except ValueError:
        return None


def _is_server() -> bool:
    pc = get_pc()
    try:
        mode = pc.WorldInfo.NetMode
        name = getattr(mode, "name", str(mode))
        return not name.endswith("NM_Client") and mode != 3
    except Exception:  # noqa: BLE001
        return True


def _pris():
    pc = get_pc()
    try:
        return list(pc.WorldInfo.GRI.PRIArray)
    except Exception:  # noqa: BLE001
        return []


def _pri_by_name(name: str):
    for pri in _pris():
        if str(pri.PlayerName) == name:
            return pri
    return None


def _pawn_of(pri):
    pc = get_pc()
    try:
        pawn = pc.WorldInfo.PawnList
        for _ in range(256):
            if pawn is None:
                return None
            if pawn.PlayerReplicationInfo is not None and pawn.PlayerReplicationInfo._get_address() == pri._get_address():
                return pawn
            pawn = pawn.NextPawn
    except Exception:  # noqa: BLE001
        pass
    return None


def _manager():
    for mgr in unrealsdk.find_all("WillowCustomizationManager", exact=False):
        if "Default__" not in mgr._path_name():
            return mgr
    return None


def _encode(name: str, slots: dict) -> str:
    return PREFIX + name + "|" + "|".join(f"{k}={v}" for k, v in sorted(slots.items()))


def _decode(msg: str):
    parts = msg[len(PREFIX):].split("|")
    if not parts or not parts[0]:
        return None, {}
    slots = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            if k.isdigit() and v.replace("_", "").isalnum():
                slots[int(k)] = v
    return parts[0], slots


def _my_extras() -> dict:
    """My own DLC heads/skins (only those the other games can't receive the normal way)."""
    pc = get_pc()
    pri = getattr(pc, "PlayerReplicationInfo", None) if pc else None
    if pri is None:
        return {}
    extras = _extra_names()
    out = {}
    for idx in SLOTS:
        try:
            cd = pri.RemoteCustomizations[idx]
        except Exception:  # noqa: BLE001
            cd = None
        if cd is not None and cd.Name in extras:
            out[idx] = cd.Name
    return out


def _wears(pawn, cd, kind: str) -> bool:
    data = getattr(pawn, f"{kind}CustomizationData", None)
    try:
        return data is not None and str(data.Name) == str(cd.CustomizationDataName)
    except Exception:  # noqa: BLE001
        return False


def _apply(name: str, slots: dict, why: str) -> None:
    pc = get_pc()
    me = getattr(getattr(pc, "PlayerReplicationInfo", None), "PlayerName", None) if pc else None
    if name == str(me):
        return
    pri = _pri_by_name(name)
    if pri is None:
        return
    pawn = _pawn_of(pri)
    mgr = _manager()
    done = []
    changed_list = False
    for idx, def_name in slots.items():
        cd = _def(def_name)
        if cd is None:
            continue
        kind = SLOTS.get(idx, "Head")
        try:
            if pri.RemoteCustomizations[idx] is None or pri.RemoteCustomizations[idx].Name != def_name:
                pri.RemoteCustomizations[idx] = cd
                changed_list = True
        except Exception:  # noqa: BLE001
            pass
        if pawn is not None and _wears(pawn, cd, kind):
            continue
        if mgr is None or pawn is None:
            continue
        try:
            # keywords: the game's parameter order is not (target, customization)
            mgr.InitiateCustomizationRequest(Target=pawn, NewCustomization=cd)
            done.append(def_name)
        except Exception as ex:  # noqa: BLE001
            log(f"could not put {def_name} on {name}: {type(ex).__name__}: {ex}")
    if changed_list and mgr is not None:
        # tells the menus (the lobby's Krieg for that player) that his head/skin list changed
        try:
            mgr.PlayerCustomizationsUpdated(PRI=pri)
        except Exception as ex:  # noqa: BLE001
            log(f"could not refresh {name}'s look in the menus: {type(ex).__name__}: {ex}")
    if done:
        log(f"{name} wears {', '.join(done)} ({why})")


def _send_to_clients(force: bool = False) -> None:
    """Host: send the table to every joining player that hasn't had the current version."""
    pc = get_pc()
    try:
        controllers = []
        c = pc.WorldInfo.ControllerList
        for _ in range(64):
            if c is None:
                break
            if c.Class.Name == "WillowPlayerController" or "PlayerController" in c.Class.Name:
                controllers.append(c)
            c = c.NextController
    except Exception:  # noqa: BLE001
        return
    version = repr(sorted((k, sorted(v.items())) for k, v in _table.items()))
    for other in controllers:
        if other._get_address() == pc._get_address():
            continue
        key = other._get_address()
        if not force and _state["sent_to"].get(key) == version:
            continue
        for name, slots in _table.items():
            try:
                other.ClientMessage(_encode(name, slots), "None", 0.0)
            except Exception as ex:  # noqa: BLE001
                log(f"could not send to a joining player: {type(ex).__name__}: {ex}")
                break
        _state["sent_to"][key] = version
        if _table:
            log(f"sent {len(_table)} player(s)' DLC heads/skins to "
                f"{getattr(getattr(other, 'PlayerReplicationInfo', None), 'PlayerName', '?')}: {_table}")


def note_disconnect() -> None:
    """Called when a co-op game ends under us (the host left)."""
    _state["restore_until"] = time.monotonic() + 120.0


def note_own_change(*_) -> None:
    """The player picked a head/skin himself: never 'restore' over that."""
    _state["last_mine"] = None


def _restore_own(pc) -> None:
    """When the host leaves first, the game falls back to the default head/skin for the joining
    player's own DLC head/skin (it only had "nothing" from the host for them) and keeps that.
    Put the player's own choice back."""
    last = _state.get("last_mine")
    if not last or time.monotonic() > _state.get("restore_until", 0.0):
        return
    pri = getattr(pc, "PlayerReplicationInfo", None)
    if pri is None:
        return
    put = []
    for idx, name in last.items():
        cd = _def(name)
        if cd is None:
            continue
        try:
            current = pri.RemoteCustomizations[idx]
        except Exception:  # noqa: BLE001
            current = None
        if current is not None and current.Name == name:
            continue
        try:
            pri.InitiateCustomizationRequest(NewCustomization=cd)
            put.append(name)
        except Exception as ex:  # noqa: BLE001
            log(f"could not put my {name} back: {type(ex).__name__}: {ex}")
    if put:
        log(f"the co-op game ended and reset my head/skin; put back {', '.join(put)}")


def upkeep() -> None:
    now = time.monotonic()
    if now < _state["next"]:
        return
    _state["next"] = now + 3.0
    pc = get_pc()
    if pc is None:
        return
    own = _my_extras()
    if own:
        _state["last_mine"] = dict(own)
    else:
        _restore_own(pc)
    if _is_menu() and len(_pris()) >= 2:
        _apply_lobby()
    if len(_pris()) < 2:
        return
    me = str(getattr(pc.PlayerReplicationInfo, "PlayerName", "")) if pc.PlayerReplicationInfo else ""
    mine = _my_extras()
    role = "host" if _is_server() else "joining player"
    if _state.get("said") != (role, repr(mine)):
        _state["said"] = (role, repr(mine))
        log(f"I'm the {role}; my DLC heads/skins: {mine or 'none'}")
    if _is_server():
        if mine:
            _table[me] = mine
        else:
            _table.pop(me, None)
        _send_to_clients()
    elif mine != _state["mine"] or now - _state.get("told", 0.0) > 30.0:
        _state["told"] = now
        try:
            pc.ServerMutate(_encode(me, mine))
        except Exception as ex:  # noqa: BLE001
            log(f"could not tell the host: {type(ex).__name__}: {ex}")
    _state["mine"] = mine
    # keep the others' DLC heads/skins on (a respawn puts the default back)
    for name, slots in list(_table.items()):
        _apply(name, slots, "kept on")


def _is_menu() -> bool:
    try:
        return "menumap" in str(get_pc().WorldInfo.GetMapName(True)).lower()
    except Exception:  # noqa: BLE001
        return False


_lobby_logged = set()


def _apply_lobby() -> None:
    """The main-menu lobby draws every player's Krieg as a stand-in, not as his in-game pawn. Put
    the other players' DLC heads/skins on those stand-ins too."""
    if not _table:
        return
    pc = get_pc()
    me = str(getattr(getattr(pc, "PlayerReplicationInfo", None), "PlayerName", ""))
    mine = {}
    try:
        mine = {i: pc.PlayerReplicationInfo.RemoteCustomizations[i] for i in SLOTS}
    except Exception:  # noqa: BLE001
        pass
    wanted = [(n, sl) for n, sl in _table.items() if n != me]
    if not wanted:
        return
    mgr = _manager()
    if mgr is None:
        return
    my_pawn = getattr(pc, "Pawn", None)
    for body in unrealsdk.find_all("SkeletalMeshComponent", exact=False):
        try:
            sm = body.SkeletalMesh
            if sm is None or str(sm.Name) != "Skel_PsychoBody" or "Default__" in body._path_name():
                continue
            owner = body.Owner
            if owner is None or (my_pawn is not None and owner._get_address() == my_pawn._get_address()):
                continue
            head = getattr(owner, "HeadCustomizationData", None)
            skin = getattr(owner, "SkinCustomizationData", None)
            key = owner._get_address()
            if key not in _lobby_logged and len(_lobby_logged) < 6:
                _lobby_logged.add(key)
                log(f"lobby Krieg {owner.Class.Name} {_short(owner)} wears head {_short(head)} skin {_short(skin)}")
            # skip my own lobby Krieg (it wears my head/skin)
            if mine and _short(head) == str(getattr(mine.get(0), "CustomizationDataName", "?")) and \
                    _short(skin) == str(getattr(mine.get(4), "CustomizationDataName", "?")):
                continue
        except Exception:  # noqa: BLE001
            continue
        # with one other player the remaining lobby Krieg is his
        if len(wanted) != 1:
            continue
        name, slots = wanted[0]
        for idx, def_name in slots.items():
            cd = _def(def_name)
            if cd is None:
                continue
            kind = SLOTS.get(idx, "Head")
            if _wears(owner, cd, kind) or ("lobbydone", key, def_name) in _lobby_logged:
                continue
            _lobby_logged.add(("lobbydone", key, def_name))
            try:
                mgr.InitiateCustomizationRequest(Target=owner, NewCustomization=cd)
                log(f"lobby: put {def_name} on {name}'s Krieg")
            except Exception as ex:  # noqa: BLE001
                if ("lobbyerr", key) not in _lobby_logged:
                    _lobby_logged.add(("lobbyerr", key))
                    log(f"lobby: could not put {def_name} on {name}'s Krieg: {type(ex).__name__}: {ex}")


def _short(obj) -> str:
    try:
        return str(obj.Name) if obj is not None else "None"
    except Exception:  # noqa: BLE001
        return "?"


@hook("WillowGame.CharacterSelectionReduxGFxMovie:CommitHeadCustomization", Type.PRE,
      hook_identifier="KriegTPSOwnHeadPick")
def on_own_head(*_):
    note_own_change()


@hook("WillowGame.CharacterSelectionReduxGFxMovie:CommitSkinCustomization", Type.PRE,
      hook_identifier="KriegTPSOwnSkinPick")
def on_own_skin(*_):
    note_own_change()


@hook("Engine.PlayerController:ServerMutate", Type.PRE, hook_identifier="KriegTPSCoopCustomIn")
def on_server_mutate(obj, args, *_):
    msg = str(args.MutateString)
    if not msg.startswith(PREFIX):
        return None
    # This hook also runs on the joining player's game when it *sends* the message; letting it
    # through there is what sends it to the host. Only the host reads (and swallows) it.
    if not _is_server() or _is_local_pc(obj):
        return None
    name, slots = _decode(msg)
    if name:
        if slots or name in _table:
            log(f"joining player {name} wears {slots or 'nothing special'}")
        if slots:
            _table[name] = slots
        else:
            _table.pop(name, None)
        _apply(name, slots, "from the joining player")
        _send_to_clients()
    return Block


def _is_local_pc(pc) -> bool:
    me = get_pc()
    try:
        return me is not None and pc is not None and pc._get_address() == me._get_address()
    except Exception:  # noqa: BLE001
        return False


def _client_message(obj, args):
    msg = str(args.S)
    if not msg.startswith(PREFIX):
        return None
    # On the host this hook also runs when it *sends* the message to a joining player's
    # controller; it must go through there. Only the receiving game (its own controller) reads it.
    if not _is_local_pc(obj):
        return None
    name, slots = _decode(msg)
    if name:
        log(f"host says {name} wears {slots or 'nothing special'}")
        _table[name] = slots
        _apply(name, slots, "from the host")
    return Block


@hook("Engine.PlayerController:ClientMessage", Type.PRE, hook_identifier="KriegTPSCoopCustomOut")
def on_client_message(obj, args, *_):
    return _client_message(obj, args)


@hook("WillowGame.WillowPlayerController:ClientMessage", Type.PRE, hook_identifier="KriegTPSCoopCustomOutW")
def on_client_message_willow(obj, args, *_):
    return _client_message(obj, args)


custom_hooks = [on_server_mutate, on_client_message, on_client_message_willow, on_own_head, on_own_skin]
