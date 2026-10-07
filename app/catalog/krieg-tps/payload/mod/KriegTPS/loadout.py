"""Krieg's starting loadout, like Borderlands 2's Gearbox starter kit.

A brand-new (level 1) Krieg gets the Gearbox SMG, Gearbox assault rifle and Gearbox sniper rifle, the
Contraband Sky Rocket grenade mod, and a beginner (common) Oz kit in place of Borderlands 2's relic.
The pistol the Pre-Sequel's intro hands out (Pistol_Jakobs_3_Smasher, or the Pistol_Dahl_Starter
failsafe) is taken away. Gear is added one piece per second, only in a real level, the same way the
game adds its own default weapon. Characters above level 1 are never touched.
"""

import time as _time

import unrealsdk
from mods_base import get_pc, hook
from unrealsdk.hooks import Type

GLOBALS = "GD_Globals.General.Globals"
STARTER_PISTOL = "GD_Weap_Pistol.A_Weapons_Unique.Pistol_Dahl_Starter"
# The pistol a new character is actually handed at the start of the Pre-Sequel (seen in the log).
STARTING_PISTOLS = (STARTER_PISTOL, "GD_Cork_Weap_Pistol.A_Weapons_Unique.Pistol_Jakobs_3_Smasher")
GEARBOX_SMG = "GD_Weap_SMG.A_Weapons_Unique.SMG_Gearbox_1"
# Added after the SMG, in this order (weapon slots 2 and 3 on a new character).
GEARBOX_EXTRA = (
    "GD_Weap_AssaultRifle.A_Weapons_Unique.AR_Dahl_1_GBX",
    "GD_Weap_SniperRifles.A_Weapons_Unique.Sniper_Gearbox_1",
)

# Items (not weapons): the Contraband Sky Rocket grenade mod from Borderlands 2's starting kit, and
# a beginner (common) Oz kit in place of the relic.
SKY_ROCKET = "GD_GrenadeMods.A_Item_Custom.GM_SkyRocket"
BEGINNER_OZ_KIT = "GD_MoonItems.BalanceDefinitions.A_Hyperventilator_01_Common"
STARTING_ITEMS = (SKY_ROCKET, BEGINNER_OZ_KIT)
WANTED = (GEARBOX_SMG, *GEARBOX_EXTRA, *STARTING_ITEMS)

_state = {"before": None, "swapped": None, "pending": False, "calls": 0, "checked": 0.0, "fallback_done": False, "seen": set(), "spawned": {}, "last_give": 0.0, "tries": {}}


def log(msg: str) -> None:
    from . import log as _log
    _log(msg)


def _find(path: str):
    try:
        return unrealsdk.find_object("Object", path)
    except ValueError:
        return None


def _is_krieg(pc) -> bool:
    try:
        cls = pc.PlayerClass
        return cls is not None and "Lilac" in cls._path_name()
    except Exception:  # noqa: BLE001
        return False


def _is_local(pc) -> bool:
    local = get_pc()
    return local is not None and pc is not None and local._get_address() == pc._get_address()


@hook("WillowGame.WillowPlayerController:GrantDefaultWeaponIfEligible", Type.PRE,
      hook_identifier="KriegTPSLoadoutPre")
def on_grant_pre(obj, *_):
    _state["before"] = None
    if _state["calls"] < 3 and _is_local(obj):
        log(f"loadout: GrantDefaultWeaponIfEligible (Krieg: {_is_krieg(obj)})")
    if not (_is_local(obj) and _is_krieg(obj)):
        return
    _state["before"] = bool(obj.bReceivedDefaultWeapon)
    _state["calls"] += 1
    if _state["calls"] <= 3:
        log(f"loadout: default weapon check (already received: {_state['before']})")
    if _state["before"]:
        return
    globals_def = _find(GLOBALS)
    smg = _find(GEARBOX_SMG)
    if globals_def is None or smg is None:
        log(f"loadout: could not find {GLOBALS if globals_def is None else GEARBOX_SMG}")
        return
    _state["swapped"] = (globals_def, globals_def.DefaultWeapon)
    globals_def.DefaultWeapon = smg


@hook("WillowGame.WillowPlayerController:GrantDefaultWeaponIfEligible", Type.POST,
      hook_identifier="KriegTPSLoadoutPost")
def on_grant_post(obj, *_):
    swapped = _state["swapped"]
    if swapped is not None:
        swapped[0].DefaultWeapon = swapped[1]  # back to the starter pistol for everyone else
        _state["swapped"] = None
    before = _state["before"]
    _state["before"] = None
    if before is False and obj.bReceivedDefaultWeapon:
        log("loadout: new Krieg got the Gearbox SMG; adding the Gearbox assault rifle and sniper rifle")
        _state["pending"] = True


def _spawn(balance_path: str, pawn, level: int):
    balance = _find(balance_path)
    if balance is None:
        log(f"loadout: {balance_path} not found")
        return None
    pool = unrealsdk.find_class("ItemPool").ClassDefaultObject
    result = pool.SpawnBalancedInventoryFromInventoryBalanceDefinition(balance, 1, level, 0, pawn, [], True)
    spawned = result[1] if isinstance(result, tuple) else []
    return spawned[0] if len(spawned) else None


def _owned(inv_manager) -> list:
    """Weapons in Krieg's weapon slots and backpack."""
    items = []
    seen = set()
    for chain in ("InventoryChain", "ItemChain"):
        try:
            inv = getattr(inv_manager, chain)
            count = 0
            while inv is not None and count < 64:
                count += 1
                addr = inv._get_address()
                if addr in seen:
                    break  # never loop forever on a broken chain
                seen.add(addr)
                items.append(inv)
                inv = inv.Inventory
        except Exception:  # noqa: BLE001
            pass
    try:
        for x in inv_manager.Backpack:
            if x is not None and x._get_address() not in seen:
                seen.add(x._get_address())
                items.append(x)
    except Exception:  # noqa: BLE001
        pass
    return items


def _balance_of(inv):
    try:
        return inv.DefinitionData.BalanceDefinition
    except Exception:  # noqa: BLE001
        return None


def _player_level(pc) -> int:
    for get in (lambda: pc.PlayerReplicationInfo.ExpLevel, lambda: pc.Pawn.GetExpLevel(),
                lambda: pc.GetExpLevel()):
        try:
            value = int(get())
            if value > 0:
                return value
        except Exception:  # noqa: BLE001
            pass
    return 0


def _is_starter(balance) -> bool:
    path = balance._path_name()
    if path in STARTING_PISTOLS or "Starter" in path:
        return True
    globals_def = _find(GLOBALS)
    try:
        default = globals_def.DefaultWeapon if globals_def is not None else None
        return default is not None and default._path_name() == path
    except Exception:  # noqa: BLE001
        return False


def _map_name(pc) -> str:
    try:
        return str(pc.WorldInfo.GetStreamingPersistentMapName()).lower()
    except Exception:  # noqa: BLE001
        try:
            return str(pc.WorldInfo.GetMapName(True)).lower()
        except Exception:  # noqa: BLE001
            return ""


def _in_gameplay(pc, pawn, now: float) -> bool:
    """Only touch the inventory in a real level, a few seconds after Krieg spawned: the main menu
    has its own Krieg (with the save's inventory), and changing that one hung the game while the
    level was loading."""
    name = _map_name(pc)
    if name != _state.get("map"):
        _state["map"] = name
        log(f"loadout: map is {name or '(unknown)'}")
    if not name or "menu" in name:
        return False
    try:
        if pc.IsInLoadingScreen() or pawn.Health <= 0:
            return False
    except Exception:  # noqa: BLE001
        pass
    addr = pawn._get_address()
    first = _state["spawned"].setdefault(addr, now)
    return now - first >= 5.0


def _check_starter_pistol() -> None:
    """Keep a brand-new (level 1) Krieg on the Gearbox loadout: if he is missing any of the three
    Gearbox weapons, or is holding the intro's starting pistol, fix it up. Runs whenever his
    inventory changes. (The pistol is not handed out through GrantDefaultWeaponIfEligible.)"""
    now = _time.monotonic()
    if now - _state["checked"] < 2.0:
        return
    _state["checked"] = now
    pc = get_pc()
    if pc is None or not _is_krieg(pc):
        return
    pawn = pc.Pawn
    if pawn is None or pawn.InvManager is None or not _in_gameplay(pc, pawn, now):
        return
    level = _player_level(pc)
    balances = [b for b in map(_balance_of, _owned(pawn.InvManager)) if b is not None]
    names = tuple(sorted(b._path_name() for b in balances))
    has_starter = any(_is_starter(b) for b in balances)
    key = (pawn._get_address(), level, names)
    if key in _state["seen"] and not has_starter:
        return  # nothing changed since the last check
    if key not in _state["seen"]:
        _state["seen"].add(key)
        log(f"loadout: Krieg level {level}, weapons/items: "
            f"{[n.rsplit('.', 1)[-1] for n in names] or 'none yet'}")
    if level != 1 or len(balances) > 10:
        return  # not a brand-new character
    missing = [p for p in WANTED if p not in names]
    if missing or has_starter:
        log(f"loadout: setting up the Gearbox loadout (missing {len(missing)}, "
            f"starting pistol {'yes' if has_starter else 'no'})")
        _state["pending"] = True


def _give(inv_manager, path: str, inv) -> None:
    """Add gear the way the game adds its own default weapon (GrantDefaultWeaponIfEligible):
    spawn it from its balance, then add a copy from its definition data."""
    if path in STARTING_ITEMS:
        inv_manager.AddBackpackItemFromDefinitionData(inv.DefinitionData)
        _equip_item(inv_manager, path)
    else:
        inv_manager.AddBackpackWeaponFromDefinitionData(inv.DefinitionData)


def _equip_item(inv_manager, path: str) -> None:
    """Equip the grenade mod / Oz kit that was just put in the backpack (if the slot is free)."""
    try:
        for x in inv_manager.Backpack:
            balance = _balance_of(x) if x is not None else None
            if balance is not None and balance._path_name() == path:
                inv_manager.ReadyBackpackInventory(x)
                return
    except Exception as ex:  # noqa: BLE001
        log(f"loadout: {path.rsplit('.', 1)[1]} is in the backpack (could not equip: {type(ex).__name__}: {ex})")


def _in_backpack(inv_manager, inv) -> bool:
    try:
        addr = inv._get_address()
        return any(x is not None and x._get_address() == addr for x in inv_manager.Backpack)
    except Exception:  # noqa: BLE001
        return False


def _remove(inv_manager, inv) -> None:
    name = _balance_of(inv)._path_name().rsplit('.', 1)[1]
    try:
        if _in_backpack(inv_manager, inv):
            inv_manager.RemoveInventoryFromBackpack(inv)
            where = "backpack"
        else:
            inv_manager.RemoveFromInventory(inv, False)
            where = "weapon slot"
        try:
            inv.Destroy()
        except Exception:  # noqa: BLE001
            pass
        log(f"loadout: removed {name} from the {where}")
    except Exception as ex:  # noqa: BLE001
        log(f"loadout: could not remove {name}: {type(ex).__name__}: {ex}")


def upkeep() -> None:
    _check_starter_pistol()
    if not _state["pending"]:
        return
    pc = get_pc()
    pawn = pc.Pawn if pc is not None else None
    now = _time.monotonic()
    if pawn is None or pawn.InvManager is None or not _in_gameplay(pc, pawn, now):
        return  # try again once Krieg is in a level
    if now - _state["last_give"] < 1.0:
        return  # one thing per second
    _state["last_give"] = now
    inv_manager = pawn.InvManager
    owned = _owned(inv_manager)
    owned_paths = {b._path_name() for b in map(_balance_of, owned) if b is not None}
    missing = [p for p in WANTED if p not in owned_paths and _state["tries"].get(p, 0) < 3]

    if missing:
        path = missing[0]
        short = path.rsplit('.', 1)[1]
        _state["tries"][path] = _state["tries"].get(path, 0) + 1
        try:
            spawned = _spawn(path, pawn, max(1, _player_level(pc)))
            if spawned is None:
                log(f"loadout: {short} did not spawn")
                return
            _give(inv_manager, path, spawned)
            log(f"loadout: gave {short}")
        except Exception as ex:  # noqa: BLE001
            log(f"loadout: could not give {short}: {type(ex).__name__}: {ex}")
        return

    _state["pending"] = False
    for inv in owned:  # the intro's starting pistol goes once the Gearbox weapons are in
        balance = _balance_of(inv)
        if balance is not None and _is_starter(balance):
            _remove(inv_manager, inv)


loadout_hooks = [on_grant_pre, on_grant_post]
