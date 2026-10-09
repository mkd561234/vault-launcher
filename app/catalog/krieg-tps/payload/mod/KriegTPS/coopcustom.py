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
    if _state["logs"] >= 120:
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
    """Put another player's DLC head/skin on his Krieg in MY game only.

    Never on the host's copy of a joining player's player info: the host can't send these
    heads/skins, so a change there reaches the joining player as "nothing" and resets his own
    head/skin. Never on a lobby stand-in through the customization manager either: that changes
    the stand-in's player for real (it is how the 2.2.2 lobby code changed both players' looks)."""
    pc = get_pc()
    me = getattr(getattr(pc, "PlayerReplicationInfo", None), "PlayerName", None) if pc else None
    if name == str(me):
        return
    pri = _pri_by_name(name)
    if pri is None:
        return
    pawn = _pawn_of(pri)
    mgr = _manager()
    server = _is_server()
    done = []
    changed_list = False
    for idx, def_name in slots.items():
        cd = _def(def_name)
        if cd is None:
            continue
        kind = SLOTS.get(idx, "Head")
        if not server:
            try:
                if pri.RemoteCustomizations[idx] is None or pri.RemoteCustomizations[idx].Name != def_name:
                    pri.RemoteCustomizations[idx] = cd
                    changed_list = True
            except Exception:  # noqa: BLE001
                pass
        if pawn is None or mgr is None or _wears(pawn, cd, kind):
            continue
        try:
            before = None
            if server:
                try:
                    before = list(pri.RemoteCustomizations)
                except Exception:  # noqa: BLE001
                    before = None
            # keywords: the game's parameter order is not (target, customization)
            mgr.InitiateCustomizationRequest(Target=pawn, NewCustomization=cd)
            if before is not None:
                # On the host this also rewrites the player's own head/skin list, which is sent to
                # his game - as "nothing" for these heads/skins, so his game reset him to the
                # default. Put the list back the same moment, so nothing is sent.
                for i, v in enumerate(before):
                    try:
                        cur = pri.RemoteCustomizations[i]
                        if (cur is None) != (v is None) or (cur is not None and cur._get_address() != v._get_address()):
                            pri.RemoteCustomizations[i] = v
                    except Exception:  # noqa: BLE001
                        pass
            done.append(def_name)
        except Exception as ex:  # noqa: BLE001
            log(f"could not put {def_name} on {name}: {type(ex).__name__}: {ex}")
    if changed_list and mgr is not None:
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
        first = _state["sent_to"].get(key) != version
        _state["sent_to"][key] = version
        if _table and first:
            log(f"sent {len(_table)} player(s)' DLC heads/skins to "
                f"{getattr(getattr(other, 'PlayerReplicationInfo', None), 'PlayerName', '?')}: {_table}")


def note_disconnect() -> None:
    """Called when a co-op game ends under us (the host left)."""
    _state["restore_until"] = time.monotonic() + 120.0


def note_own_change(*_) -> None:
    """The player picked a head/skin himself: remember what he picked (read a moment later)."""
    _state["capture_at"] = time.monotonic() + 1.5


def _net_mode() -> str:
    try:
        mode = get_pc().WorldInfo.NetMode
        return getattr(mode, "name", str(mode))
    except Exception:  # noqa: BLE001
        return "?"


MENU_CLASSES = ("CustomizationGFxMovie", "CharacterSelectionReduxGFxMovie")


def _menu_open() -> bool:
    for cls in MENU_CLASSES:
        try:
            for movie in unrealsdk.find_all(cls, exact=False):
                if "Default__" in movie._path_name():
                    continue
                try:
                    if movie.bMovieIsOpen:
                        return True
                except Exception:  # noqa: BLE001
                    return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _menu_recent(now: float) -> bool:
    return now - _state.get("menu_at", -100.0) < 6.0


def _track_own(pc, players: int) -> None:
    """Remember the player's own DLC head/skin. Only a pick the player makes himself counts (while
    the head/skin menu is open, at character select or the Quick Change station); the game swaps
    in the default head/skin by itself in co-op and while levels load, and that must never count.
    The very first look seen after the game starts counts too."""
    now = time.monotonic()
    if _menu_open():
        _state["menu_at"] = now
    picked = _state.get("capture_at") and now >= _state["capture_at"]
    first = _state.get("own") is None and players <= 1 and not _state.get("was_coop") and \
        getattr(pc, "Pawn", None) is not None
    if not (picked or first or _menu_recent(now)):
        return
    if picked:
        _state["capture_at"] = 0.0
    own = _my_extras()
    pri = getattr(pc, "PlayerReplicationInfo", None)
    try:
        if pri is None or any(pri.RemoteCustomizations[i] is None for i in SLOTS):
            return            # list not filled in yet (loading)
    except Exception:  # noqa: BLE001
        return
    _set_own(own)


def _set_own(own: dict) -> None:
    if own != _state.get("own"):
        if _state.get("own") is not None or own:
            log(f"my own DLC head/skin: {own or 'none'}")
        _state["own"] = dict(own)
        _state["restores"] = 0


def _coop_mine() -> dict:
    """My DLC heads/skins to tell the others: what I picked, not what the game swapped in."""
    own = _state.get("own")
    return dict(own) if own is not None else _my_extras()


def _restore_own(pc, players: int) -> None:
    """The game swaps a DLC head/skin for the default by itself (in co-op the host only has
    "nothing" for it, and when a co-op game ends). Put the player's own pick back whenever his
    Krieg isn't wearing it and he isn't in the head/skin menu."""
    own = _state.get("own")
    now = time.monotonic()
    if not own or _menu_recent(now):
        return
    pri = getattr(pc, "PlayerReplicationInfo", None)
    if pri is None:
        return
    pawn = getattr(pc, "Pawn", None)
    put = []
    for idx, name in own.items():
        cd = _def(name)
        if cd is None:
            continue
        kind = SLOTS.get(idx, "Head")
        if pawn is not None:
            wrong = not _wears(pawn, cd, kind)
        else:
            try:
                current = pri.RemoteCustomizations[idx]
            except Exception:  # noqa: BLE001
                current = None
            wrong = current is not None and current.Name != name
        if not wrong:
            continue
        key = ("restore_at", idx)
        if now - _state.get(key, -100.0) < 15.0 or _state.get("restores", 0) >= 12:
            continue
        _state[key] = now
        _state["restores"] = _state.get("restores", 0) + 1
        try:
            pri.InitiateCustomizationRequest(NewCustomization=cd)
            put.append(name)
        except Exception as ex:  # noqa: BLE001
            log(f"could not put my {name} back: {type(ex).__name__}: {ex}")
    if put:
        log(f"the game swapped my head/skin for the default; put back {', '.join(put)}")


SESSION_END_AFTER = 10.0   # alone this long = the co-op game is over (not just a level loading)


def upkeep() -> None:
    now = time.monotonic()
    if now < _state["next"]:
        return
    _state["next"] = now + 3.0
    pc = get_pc()
    if pc is None:
        return
    players = len(_pris())
    if players >= 2:
        _state["was_coop"] = True
        _state["alone_since"] = None
    else:
        if _state.get("alone_since") is None:
            _state["alone_since"] = now
        if _state.get("was_coop") and now - _state["alone_since"] >= SESSION_END_AFTER:
            # the co-op game is over: forget everyone else and watch for a reset of my own look
            _state["was_coop"] = False
            _table.clear()
            _state["sent_to"].clear()
            _state["mine"] = None
            _state["restore_until"] = now + 120.0
            _lobby_logged.clear()
            log("co-op game over")
    _track_own(pc, players)
    _restore_own(pc, players)
    if players < 2:
        return
    if _is_menu():
        _refresh_lobby()
    me = str(getattr(pc.PlayerReplicationInfo, "PlayerName", "")) if pc.PlayerReplicationInfo else ""
    mine = _coop_mine()
    role = "host" if _is_server() else "joining player"
    if _state.get("said") != (role, repr(mine)):
        _state["said"] = (role, repr(mine))
        log(f"I'm the {role}; my DLC heads/skins: {mine or 'none'}")
    if _is_server():
        if mine:
            _table[me] = mine
        else:
            _table.pop(me, None)
        # again every 20 s too: a joining player's game can lose the list while a level loads
        force = now - _state.get("sent_at", 0.0) > 20.0
        if force:
            _state["sent_at"] = now
        _send_to_clients(force)
    elif mine != _state["mine"] or now - _state.get("told", 0.0) > 20.0:
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


def _same(a, b) -> bool:
    try:
        return a is not None and b is not None and a._get_address() == b._get_address()
    except Exception:  # noqa: BLE001
        return False


def _standin_wants(standin) -> dict:
    """The DLC heads/skins another player's lobby Krieg should wear ({} for my own, or unknown)."""
    pri = getattr(standin, "OwningPRI", None)
    pc = get_pc()
    if pri is None or pc is None or _same(pri, getattr(pc, "PlayerReplicationInfo", None)):
        return {}
    return _table.get(str(pri.PlayerName), {})


def _refresh_lobby() -> None:
    """The lobby draws each player as a stand-in that asks for his head/skin (answered by the hook
    below). Ask the other players' stand-ins to redraw once their DLC heads/skins are known."""
    if not _table:
        return
    for standin in unrealsdk.find_all("PlayerStandIn", exact=False):
        try:
            if "Default__" in standin._path_name():
                continue
            wants = _standin_wants(standin)
            if not wants:
                continue
            key = ("standin", standin._get_address(), repr(sorted(wants.items())))
            if key in _lobby_logged:
                continue
            _lobby_logged.add(key)
            standin.RefreshCustomizationsOnInstanceData()
            log(f"lobby: showing {standin.OwningPRI.PlayerName}'s {', '.join(wants.values())}")
        except Exception as ex:  # noqa: BLE001
            if ("lobbyerr",) not in _lobby_logged:
                _lobby_logged.add(("lobbyerr",))
                log(f"lobby: could not redraw a stand-in: {type(ex).__name__}: {ex}")


@hook("WillowGame.PlayerStandIn:GetDesiredCustomizationOfType", Type.PRE,
      hook_identifier="KriegTPSLobbyCustom")
def on_standin_customization(obj, args, *_):
    """Answer "which head/skin?" for another player's lobby Krieg with his DLC head/skin. Only
    the answer changes; nobody's choice is touched."""
    try:
        wants = _standin_wants(obj)
        if not wants:
            return None
        asked = None
        for prop in args._type._fields():
            if prop.Name != "ReturnValue":
                asked = getattr(args, prop.Name)
                break
        kind = str(getattr(asked, "Name", asked))
        if ("argname",) not in _lobby_logged:
            _lobby_logged.add(("argname",))
            log(f"lobby stand-in asks for {kind}")
        for idx, def_name in wants.items():
            if kind.endswith(SLOTS.get(idx, "?")):
                cd = _def(def_name)
                if cd is not None:
                    return Block, cd
    except Exception as ex:  # noqa: BLE001
        if ("hookerr",) not in _lobby_logged:
            _lobby_logged.add(("hookerr",))
            log(f"lobby stand-in: {type(ex).__name__}: {ex}")
    return None


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
        if _table.get(name) != slots:
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


custom_hooks = [on_standin_customization, on_server_mutate, on_client_message, on_client_message_willow, on_own_head, on_own_skin]
