"""Checks for the Infinity: does the game make one from its pool, and what the Grinder does.

* Once you are in the game, one Infinity is made from the Grinder's output pool and thrown away
  again, and what came out (or why nothing did) is written to infinity_log.txt.
* Pressing the Grinder's button, the recipe check and the spawn are written to the log.
* Console command `infinity_give` puts an Infinity in your backpack (for testing).
"""

import unrealsdk
from mods_base import command, get_pc, hook
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
    for inv in items:
        log("test: the game can make an Infinity: " + _describe(inv))
        try:
            inv.Destroy()
        except Exception:  # noqa: BLE001
            pass


@command("infinity_give", description="Put an Infinity pistol in your backpack (for testing the Infinity mod).")
def infinity_give(_args) -> None:
    try:
        items = _spawn()
    except Exception as ex:  # noqa: BLE001
        log(f"give: failed: {type(ex).__name__}: {ex}")
        return
    if not items:
        log("give: the game made nothing from the Infinity's pool")
        return
    pawn = _pawn()
    mgr = getattr(pawn, "InvManager", None)
    for inv in items:
        for add in (lambda: mgr.AddInventoryToBackpack(inv), lambda: mgr.AddInventory(inv, True)):
            try:
                add()
                log("give: put in your backpack: " + _describe(inv))
                break
            except Exception as ex:  # noqa: BLE001
                log(f"give: could not add it: {type(ex).__name__}: {ex}")


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
        log(f"Grinder: recipe check for {', '.join(inputs)} -> {ret}")


@hook("WillowGame.GrinderRecipe:SpawnBalancedInventoryFromRecipe", Type.POST, hook_identifier="InfinityTPSGrindSpawn")
def on_spawn(obj, args, ret, *_) -> None:
    log(f"Grinder: made the item -> result {ret} (rarity total {getattr(args, 'TotalItemRarity', '?')}, "
        f"level total {getattr(args, 'TotalItemExpLevel', '?')})")


@hook("WillowGame.GrinderRecipe:SpawnLockedBalancedInventoryFromRecipe", Type.POST, hook_identifier="InfinityTPSGrindSpawnLocked")
def on_spawn_locked(obj, args, ret, *_) -> None:
    log(f"Grinder: made the moonstone item -> result {ret}")


diag_hooks = [infinity_give, on_grind, on_status, on_has_recipe, on_spawn, on_spawn_locked]
