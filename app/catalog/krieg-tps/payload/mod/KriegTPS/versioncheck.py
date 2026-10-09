"""Only the latest Vault Launcher and mods may play.

* The newest versions are read from the launcher's GitHub repository (latest.json for the
  launcher, the Krieg mod's mod.json for the mod) when the game starts and every minute.
* If this game's launcher or Krieg mod is older: in a level, the character is saved and the game
  goes back to the main menu with the update message; at the main menu the message is shown, and
  starting or joining a game sends the player straight back. Solo and co-op alike.
* In co-op the host also checks everyone who joins: the joining game reports its versions; anyone
  who is out of date, or doesn't report within 10 seconds (a mod too old to have this check), is
  told to save and leave, and removed by the host if he is still there a few seconds later.
If the newest versions can't be read (no internet), nobody is blocked for being out of date;
the host still requires joining players to be at least on the host's own versions.
"""

import json
import os
import threading
import time
import urllib.request
from pathlib import Path

import unrealsdk
from mods_base import command, get_pc, hook
from unrealsdk.hooks import Block, Type

MESSAGE = "You must update your launcher and mods to the latest versions to continue playing."
TITLE = "Update required"
REPO = "mkd561234/vault-launcher"
RAW = f"https://raw.githubusercontent.com/{REPO}/main/"
CHECK_EVERY = 60.0
REPORT_WAIT = 10.0          # seconds a joining player has to report his versions
KICK_GRACE = 1.0            # a moment for his game to save before the host removes him
PREFIX_VER = "KTPS|VER|"
PREFIX_KICK = "KTPS|KICK|"

_latest: dict = {"launcher": None, "krieg": None, "at": 0.0, "busy": False, "error": None}
_state = {"next": 0.0, "leaving": None, "show_at": 0.0, "shown_for": None, "told": 0.0,
          "players": {}, "logs": 0}


def log(msg: str) -> None:
    if _state["logs"] >= 120:
        return
    _state["logs"] += 1
    from . import log as _log
    _log("version check: " + msg)


def _vt(v) -> tuple:
    out = []
    for part in str(v or "0").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits or 0))
    return tuple(out)


# ---------------------------------------------------------------------------------------------
# versions
# ---------------------------------------------------------------------------------------------
def _launcher_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "VaultLauncher"


# Other Vault Launcher mods for the Pre-Sequel: launcher id -> (folder in sdk_mods, name shown)
OTHER_MODS = {"infinity-tps": ("InfinityTPS", "Infinity mod")}
SDK_MODS = Path(__file__).resolve().parents[1]


def _folder_version(folder: str):
    try:
        text = (SDK_MODS / folder / "__init__.py").read_text("utf-8", errors="replace")
    except OSError:
        return None
    import re
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)', text)
    return m.group(1) if m else None


def my_versions() -> dict:
    """{"launcher", "krieg", "mod:<id>" for each other launcher mod installed in this game}."""
    from . import __version__
    launcher = None
    try:
        launcher = json.loads((_launcher_dir() / "app" / "release.json").read_text("utf-8")).get("version")
    except (OSError, ValueError):
        pass
    out = {"launcher": launcher, "krieg": __version__}
    for mod_id, (folder, _label) in OTHER_MODS.items():
        v = _folder_version(folder)
        if v:
            out[f"mod:{mod_id}"] = v
    return out


def _label(key: str) -> str:
    if key == "launcher":
        return "launcher"
    if key == "krieg":
        return "Krieg mod"
    return OTHER_MODS.get(key[4:], (None, key[4:]))[1]


def _get_json(path: str):
    req = urllib.request.Request(f"{RAW}{path}?t={int(time.time())}",
                                 headers={"User-Agent": "VaultLauncher-KriegMod", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _fetch() -> None:
    try:
        launcher = str(_get_json("latest.json").get("version") or "").lstrip("vV") or None
        krieg = str(_get_json("app/catalog/krieg-tps/mod.json").get("version") or "") or None
        mods = {}
        for mod_id in OTHER_MODS:
            try:
                mods[f"mod:{mod_id}"] = str(_get_json(f"app/catalog/{mod_id}/mod.json").get("version") or "") or None
            except Exception:  # noqa: BLE001
                pass
        if launcher or krieg:
            _latest.update(launcher=launcher, krieg=krieg, error=None)
            _latest.update(mods)
            log(f"newest versions: launcher {launcher}, Krieg mod {krieg}"
                + "".join(f", {_label(k)} {v}" for k, v in mods.items()))
    except Exception as ex:  # noqa: BLE001
        _latest["error"] = f"{type(ex).__name__}: {ex}"
        # the launcher remembers the newest version it saw on GitHub
        try:
            st = json.loads((_launcher_dir() / "state.json").read_text("utf-8"))
            if st.get("gh_latest") and not _latest["launcher"]:
                _latest["launcher"] = str(st["gh_latest"])
        except (OSError, ValueError):
            pass
        log(f"could not read the newest versions ({_latest['error']}); using what's known: "
            f"launcher {_latest['launcher']}, Krieg mod {_latest['krieg']}")
    finally:
        _latest["at"] = time.monotonic()
        _latest["busy"] = False


def _refresh() -> None:
    if _latest["busy"]:
        return
    if _latest["at"] and time.monotonic() - _latest["at"] < CHECK_EVERY:
        return
    _latest["busy"] = True
    threading.Thread(target=_fetch, name="KriegVersionCheck", daemon=True).start()


def required(mods_of: dict | None = None) -> dict:
    """The versions everyone needs: the newest known ones, for the launcher, the Krieg mod and
    every other launcher mod in mods_of (default: the ones installed in this game)."""
    need = {"launcher": _latest["launcher"], "krieg": _latest["krieg"]}
    for key in (mods_of if mods_of is not None else my_versions()):
        if key.startswith("mod:"):
            need[key] = _latest.get(key)
    return need


def _outdated(have: dict, need: dict) -> list:
    out = []
    for key in need:
        if need.get(key) and have.get(key) and _vt(have[key]) < _vt(need[key]):
            out.append(f"{_label(key)} {have[key]} < {need[key]}")
        elif need.get(key) and not have.get(key):
            out.append(f"{_label(key)} {'missing' if key.startswith('mod:') else 'unknown'} (needs {need[key]})")
    return out


def i_am_outdated() -> list:
    mine = my_versions()
    need = required()
    if not mine["launcher"]:
        need = dict(need, launcher=None)     # no launcher install found: only the mods can be checked
    return _outdated(mine, need)


# ---------------------------------------------------------------------------------------------
# game helpers
# ---------------------------------------------------------------------------------------------
def _map() -> str:
    try:
        return str(get_pc().WorldInfo.GetMapName(True)).lower()
    except Exception:  # noqa: BLE001
        return ""


def _in_menu() -> bool:
    return "menumap" in _map()


def _pris():
    try:
        return list(get_pc().WorldInfo.GRI.PRIArray)
    except Exception:  # noqa: BLE001
        return []


def _is_server() -> bool:
    try:
        mode = get_pc().WorldInfo.NetMode
        return "Client" not in getattr(mode, "name", str(mode))
    except Exception:  # noqa: BLE001
        return True


def _is_local_pc(pc) -> bool:
    me = get_pc()
    try:
        return me is not None and pc is not None and pc._get_address() == me._get_address()
    except Exception:  # noqa: BLE001
        return False


def _save(pc) -> None:
    for how in ("QuickSave", "SaveGame"):
        try:
            getattr(pc, how)()
            log(f"saved the character ({how})")
            return
        except Exception as ex:  # noqa: BLE001
            log(f"saving with {how} failed: {type(ex).__name__}: {ex}")


def _viewport():
    for vp in unrealsdk.find_all("WillowGameViewportClient", exact=False):
        if "Default__" not in vp._path_name():
            return vp
    return None


def _show_message() -> None:
    vp = _viewport()
    if vp is None:
        return
    try:
        vp.NotifyConnectionError(MessageType=4, Title=TITLE, Message=MESSAGE, StringVal="", LoginStatus=0)
        return
    except Exception as ex:  # noqa: BLE001
        log(f"could not show the update message as a dialog: {type(ex).__name__}: {ex}")
    try:
        get_pc().ClientMessage(MESSAGE, "Event", 10.0)
    except Exception:  # noqa: BLE001
        pass


def _leave(why: str) -> None:
    """Save, then go back to the main menu; the message is shown there."""
    if _state["leaving"]:
        return
    pc = get_pc()
    if pc is None:
        return
    log(f"leaving the game: {why}")
    if not _in_menu():
        _save(pc)
    _state["leaving"] = time.monotonic() + (0.5 if not _in_menu() else 0.0)


# ---------------------------------------------------------------------------------------------
# main loop (called every frame; does real work a few times a second)
# ---------------------------------------------------------------------------------------------
def tick() -> None:
    now = time.monotonic()
    if now < _state["next"]:
        return
    _state["next"] = now + 0.25
    _refresh()
    pc = get_pc()
    if pc is None:
        return
    # leaving in progress
    if _state["leaving"]:
        if now >= _state["leaving"]:
            _state["leaving"] = None
            _state["show_at"] = now + 1.0
            try:
                pc.ConsoleCommand("disconnect", False)
            except Exception as ex:  # noqa: BLE001
                log(f"could not leave the game: {type(ex).__name__}: {ex}")
        return
    if _state["show_at"] and now >= _state["show_at"] and _in_menu() and len(_pris()) <= 1:
        _state["show_at"] = 0.0
        _state["shown_for"] = (repr(i_am_outdated()), _latest["at"])
        _show_message()
        return
    # my own versions
    behind = i_am_outdated()
    players = len(_pris())
    if behind:
        if not _in_menu() or players >= 2:
            _leave(", ".join(behind))
            return
        key = (repr(behind), _latest["at"])
        if _state["shown_for"] != key:
            _state["shown_for"] = key
            log(f"out of date: {', '.join(behind)}")
            _show_message()
        return
    if players < 2:
        _state["players"].clear()
        return
    if _is_server():
        _check_players(pc, now)
    elif now - _state["told"] > 5.0:
        _state["told"] = now
        mine = my_versions()
        extra = ",".join(f"{k[4:]}={v}" for k, v in mine.items() if k.startswith("mod:"))
        try:
            pc.ServerMutate(f"{PREFIX_VER}{mine['launcher'] or '?'}|{mine['krieg']}|{extra}")
        except Exception as ex:  # noqa: BLE001
            log(f"could not tell the host my versions: {type(ex).__name__}: {ex}")


def _controllers(pc) -> list:
    out = []
    try:
        c = pc.WorldInfo.ControllerList
        for _ in range(64):
            if c is None:
                break
            if "PlayerController" in c.Class.Name and not _is_local_pc(c):
                out.append(c)
            c = c.NextController
    except Exception:  # noqa: BLE001
        pass
    return out


def _check_players(pc, now: float) -> None:
    """Host: everyone else must report up-to-date versions."""
    mine = my_versions()
    need = required(mine)                   # the host's mods are needed by everyone
    for key in mine:
        if not need.get(key):
            need[key] = mine.get(key)       # newest unknown: at least the host's own
    seen = set()
    for other in _controllers(pc):
        addr = other._get_address()
        seen.add(addr)
        info = _state["players"].setdefault(addr, {"since": now, "report": None, "kick_at": 0.0})
        name = str(getattr(getattr(other, "PlayerReplicationInfo", None), "PlayerName", "?"))
        if info["kick_at"]:
            if now >= info["kick_at"]:
                info["kick_at"] = now + 30.0
                _force_kick(pc, other, name)
            continue
        if info["report"] is None:
            if now - info["since"] < REPORT_WAIT:
                continue
            why = "his game didn't report its versions (launcher or Krieg mod too old)"
        else:
            behind = _outdated(info["report"], need)
            if not behind:
                continue
            why = ", ".join(behind)
        log(f"{name} must update: {why}")
        try:
            other.ClientMessage(f"{PREFIX_KICK}{MESSAGE}", "None", 0.0)
        except Exception:  # noqa: BLE001
            pass
        info["kick_at"] = now + KICK_GRACE
    for addr in list(_state["players"]):
        if addr not in seen:
            del _state["players"][addr]


def _force_kick(pc, other, name: str) -> None:
    game = getattr(pc.WorldInfo, "Game", None)
    for how in ("ForceKickPlayer",):
        try:
            getattr(game, how)(PC=other, KickReason=MESSAGE)
            log(f"removed {name} from the game (out of date)")
            return
        except Exception as ex:  # noqa: BLE001
            log(f"could not remove {name}: {type(ex).__name__}: {ex}")
    try:
        game.AccessControl.KickPlayer(C=other, KickReason=MESSAGE)
        log(f"removed {name} from the game (out of date)")
    except Exception as ex:  # noqa: BLE001
        log(f"could not remove {name}: {type(ex).__name__}: {ex}")


# ---------------------------------------------------------------------------------------------
# messages between the games
# ---------------------------------------------------------------------------------------------
@hook("Engine.PlayerController:ServerMutate", Type.PRE, hook_identifier="KriegTPSVersionIn")
def on_server_mutate(obj, args, *_):
    msg = str(args.MutateString)
    if not msg.startswith(PREFIX_VER):
        return None
    if not _is_server() or _is_local_pc(obj):
        return None          # the joining game sending it: let it through
    parts = msg[len(PREFIX_VER):].split("|")
    report = {"launcher": parts[0] if parts and parts[0] != "?" else None,
              "krieg": parts[1] if len(parts) > 1 else None}
    if len(parts) > 2:
        for pair in parts[2].split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                report[f"mod:{k}"] = v
    info = _state["players"].setdefault(obj._get_address(), {"since": time.monotonic(), "report": None, "kick_at": 0.0})
    if info["report"] != report:
        name = str(getattr(getattr(obj, "PlayerReplicationInfo", None), "PlayerName", "?"))
        log(f"{name} has " + ", ".join(f"{_label(k)} {v}" for k, v in report.items()))
    info["report"] = report
    return Block


def _client_message(obj, args):
    msg = str(args.S)
    if not msg.startswith(PREFIX_KICK):
        return None
    if not _is_local_pc(obj):
        return None          # the host sending it: let it through
    _leave("the host says this game is out of date")
    return Block


@hook("Engine.PlayerController:ClientMessage", Type.PRE, hook_identifier="KriegTPSVersionKick")
def on_client_message(obj, args, *_):
    return _client_message(obj, args)


@hook("WillowGame.WillowPlayerController:ClientMessage", Type.PRE, hook_identifier="KriegTPSVersionKickW")
def on_client_message_willow(obj, args, *_):
    return _client_message(obj, args)


@command("krieg_versions", description="Write this game's launcher/mod versions and the newest ones to the Krieg log.")
def krieg_versions(_args) -> None:
    _state["logs"] = 0
    mine = my_versions()
    need = required()
    log("this game: " + ", ".join(f"{_label(k)} {v}" for k, v in mine.items())
        + "; newest: " + ", ".join(f"{_label(k)} {v}" for k, v in need.items())
        + (f" (last check failed: {_latest['error']})" if _latest["error"] else "")
        + (f"; OUT OF DATE: {', '.join(i_am_outdated())}" if i_am_outdated() else "; up to date"))
    _latest["at"] = 0.0
    _refresh()


version_hooks = [on_server_mutate, on_client_message, on_client_message_willow, krieg_versions]
