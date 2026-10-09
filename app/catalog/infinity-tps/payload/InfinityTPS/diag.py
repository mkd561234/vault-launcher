"""Checks for the Infinity: does the game make one from its pool, and what the Grinder does.

* Once you are in the game, one Infinity is made from the Grinder's output pool and thrown away
  again, and what came out (or why nothing did) is written to infinity_log.txt.
* Pressing the Grinder's button, the recipe check and the spawn are written to the log.
"""

import unrealsdk
from mods_base import get_pc, hook
from unrealsdk.hooks import Type

from . import infinity

POOL = "GD_Itempools.GrinderPools." + infinity.POOL_NAME
_state = {"tested": False, "logs": 0}


def log(msg: str) -> None:
    if _state["logs"] >= 120:
        return
    _state["logs"] += 1
    infinity.log(msg)


def _name(obj) -> str:
    if obj is None:
        return "None"
    try:
        return obj._path_name()
    except Exception:  # noqa: BLE001
        return str(obj)


def _pawn():
    pc = get_pc()
    return getattr(pc, "Pawn", None) if pc is not None else None


def _level() -> int:
    pawn = _pawn()
    for get in (lambda: pawn.GetExpLevel(), lambda: get_pc().PlayerReplicationInfo.ExpLevel):
        try:
            return int(get())
        except Exception:  # noqa: BLE001
            pass
    return 70


def _spawn() -> list:
    """Makes Infinities from the output pool; returns the items (empty if the game made none)."""
    pool = infinity._find(POOL)
    pawn = _pawn()
    if pool is None:
        log("test: the Infinity's pool doesn't exist")
        return []
    if pawn is None:
        return []
    cdo = unrealsdk.find_class("ItemPool").ClassDefaultObject
    result = cdo.SpawnBalancedInventoryFromPool(pool, _level(), 0, pawn, [])
    items = []
    for part in result if isinstance(result, tuple) else (result,):
        try:
            items += [x for x in part if x is not None]
        except TypeError:
            pass
    return items


def _describe(inv) -> str:
    out = [inv.Class.Name]
    try:
        data = inv.DefinitionData
        out.append("balance " + _name(data.BalanceDefinition).rsplit(".", 1)[-1])
        for field in ("BarrelPartDefinition", "ElementalPartDefinition", "Accessory1PartDefinition",
                      "MaterialPartDefinition", "TitlePartDefinition"):
            part = getattr(data, field, None)
            out.append(f"{field.replace('PartDefinition', '').lower()} {_name(part).rsplit('.', 1)[-1]}")
    except Exception as ex:  # noqa: BLE001
        out.append(f"(could not read its parts: {type(ex).__name__}: {ex})")
    for get in ("GetShortHumanReadableName", "GetHumanReadableName"):
        try:
            out.append(f'named "{getattr(inv, get)()}"')
            break
        except Exception:  # noqa: BLE001
            pass
    return ", ".join(out)


def self_test() -> None:
    """Once per game: make an Infinity from the Grinder's output pool and throw it away again."""
    if _state["tested"] or not infinity._state["done"] or _pawn() is None:
        return
    _state["tested"] = True
    try:
        items = _spawn()
    except Exception as ex:  # noqa: BLE001
        log(f"test: making an Infinity failed: {type(ex).__name__}: {ex}")
        return
    if not items:
        log("test: the game made NOTHING from the Infinity's pool - the Grinder can't give one either")
        return
    _library_test()
    for inv in items:
        log("test: the game can make an Infinity: " + _describe(inv))
        _serial_test(inv)
        try:
            inv.Destroy()
        except Exception:  # noqa: BLE001
            pass


def _library_manager():
    for mgr in unrealsdk.find_all("AssetLibraryManager", exact=False):
        if "Default__" not in mgr._path_name():
            return mgr
    return None


def _library_test() -> None:
    """Can the game write each Infinity part into a save (and read it back)? The Maggie is the
    control: a gun the game itself saves."""
    mgr = _library_manager()
    if mgr is None:
        log("test: no asset library manager found")
        return
    paths = ["GD_Cork_Weap_Pistol.A_Weapons_Legendary.Pistol_Jakobs_5_Maggie"] + list(infinity.LIBRARY_SLOTS)
    for path in paths:
        obj = infinity._find(path)
        if obj is None:
            log(f"test: save code for {path}: object missing")
            continue
        try:
            code = mgr.Encode(obj, 0)
        except Exception as ex:  # noqa: BLE001
            log(f"test: save code for {path.rsplit('.', 1)[-1]}: {type(ex).__name__}: {ex}")
            continue
        back = None
        try:
            res = mgr.Decode(code, 0, 0, None)
            back = next((x for x in (res if isinstance(res, tuple) else (res,)) if hasattr(x, "_path_name")), None)
        except Exception as ex:  # noqa: BLE001
            back = f"{type(ex).__name__}: {ex}"
        log(f"test: save code for {path.rsplit('.', 1)[-1]}: {code} -> reads back as {_name(back) if not isinstance(back, str) else back}")


def _serial_test(inv) -> None:
    try:
        serial = inv.CreateSerialNumber()
    except Exception as ex:  # noqa: BLE001
        log(f"test: making its serial number failed: {type(ex).__name__}: {ex}")
        return
    try:
        text = inv.GetSerialNumberString(serial) if serial is not None else None
    except Exception:  # noqa: BLE001
        try:
            text = inv.GetSerialNumberString()
        except Exception as ex:  # noqa: BLE001
            text = f"({type(ex).__name__}: {ex})"
    log(f"test: its serial number: {text}")
    try:
        cdo = unrealsdk.find_class("WillowWeapon").ClassDefaultObject
        copy = cdo.CreateWeaponFromSerialNumber(serial, get_pc())
        if isinstance(copy, tuple):
            copy = next((x for x in copy if hasattr(x, "Class")), None)
        log("test: rebuilt from the serial number: " + (_describe(copy) if copy is not None else "NOTHING (it can't be saved)"))
        if copy is not None:
            copy.Destroy()
    except Exception as ex:  # noqa: BLE001
        log(f"test: rebuilding from the serial number failed: {type(ex).__name__}: {ex}")


# ---------------------------------------------------------------------------------------------
# what the Grinder does
# ---------------------------------------------------------------------------------------------
@hook("WillowGame.GrinderGFxMovie:GrindItems", Type.PRE, hook_identifier="InfinityTPSGrind")
def on_grind(obj, args, *_) -> None:
    log(f"Grinder: grind pressed (moonstone version: {bool(getattr(args, 'bUnlockItemPool', False))})")


@hook("WillowGame.GrinderGFxMovie:CheckGrinderOpStatus", Type.POST, hook_identifier="InfinityTPSGrindStatus")
def on_status(obj, args, ret, *_) -> None:
    key = repr(ret)
    if _state.get("status") != key:
        _state["status"] = key
        log(f"Grinder: status {ret}")


@hook("WillowGame.GrinderRecipe:HasRecipe", Type.POST, hook_identifier="InfinityTPSHasRecipe")
def on_has_recipe(obj, args, ret, *_) -> None:
    try:
        inputs = [_name(b).rsplit(".", 1)[-1] for b in args.BalanceDefinitions]
    except Exception:  # noqa: BLE001
        inputs = ["?"]
    key = (tuple(inputs), repr(ret))
    if _state.get("recipe_check") != key:
        _state["recipe_check"] = key
        pool = getattr(args, "OutputLockedItemPoolDefinition", None)
        log(f"Grinder: recipe check for {', '.join(inputs)} -> {ret}, output {_name(pool)}")


@hook("WillowGame.GrinderRecipe:SpawnBalancedInventoryFromRecipe", Type.POST, hook_identifier="InfinityTPSGrindSpawn")
def on_spawn(obj, args, ret, *_) -> None:
    log(f"Grinder: made the item -> result {ret} (rarity total {getattr(args, 'TotalItemRarity', '?')}, "
        f"level total {getattr(args, 'TotalItemExpLevel', '?')})")


@hook("WillowGame.GrinderRecipe:SpawnLockedBalancedInventoryFromRecipe", Type.POST, hook_identifier="InfinityTPSGrindSpawnLocked")
def on_spawn_locked(obj, args, ret, *_) -> None:
    log(f"Grinder: made the moonstone item -> result {ret}")


diag_hooks = [on_grind, on_status, on_has_recipe, on_spawn, on_spawn_locked]
