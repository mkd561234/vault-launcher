"""The Grinder: legendary pistol + any legendary weapon + any purple pistol -> Infinity.

A recipe of our own in the Grinder's list was matched by the game but it then refused to make
anything ("FailedToSpawnItem"), and grinding a few times in a row crashed the game. So no recipe
is added. The same three guns already fit the game's own "two legendaries and a purple" recipe;
just while the Grinder makes its item, every Grinder output pool is switched to give the Infinity
(all its other entries at chance 0), and switched straight back afterwards. Any other three guns
grind exactly as before.
"""

import itertools

from mods_base import hook
from unrealsdk.hooks import Type

from . import infinity

ROLES = (infinity.LEGENDARY_PISTOLS, infinity.LEGENDARY_WEAPONS, infinity.PURPLE_PISTOLS)
_state = {"inputs": [], "saved": None, "members": {}}


def log(msg: str) -> None:
    infinity.log(msg)


def _addr(obj):
    return obj._get_address() if obj is not None else None


def _members(pool_path: str) -> set:
    """Addresses of every balance a pool (and the pools inside it) can give."""
    if pool_path in _state["members"]:
        return _state["members"][pool_path]
    found, seen = set(), set()
    stack = [infinity._find(pool_path)]
    while stack:
        pool = stack.pop()
        if pool is None or _addr(pool) in seen:
            continue
        seen.add(_addr(pool))
        for item in pool.BalancedItems:
            if item.InvBalanceDefinition is not None:
                found.add(_addr(item.InvBalanceDefinition))
            if item.ItmPoolDefinition is not None:
                stack.append(item.ItmPoolDefinition)
    if found:
        _state["members"][pool_path] = found
    return found


def _fits(balances) -> bool:
    balances = [b for b in balances if b is not None]
    if len(balances) != 3:
        return False
    groups = [_members(path) for path in ROLES]
    for order in itertools.permutations(balances):
        if all(_addr(b) in group for b, group in zip(order, groups)):
            return True
    return False


def _output_pools() -> list:
    holder = infinity._find(infinity.RECIPES)
    pools, seen = [], set()
    if holder is None:
        return pools
    for recipe in holder.GrinderRecipes:
        for pool in (recipe.OutputItemPoolDefinition, recipe.OutputLockedItemPoolDefinition.LockedItemPoolDefinition):
            if pool is not None and _addr(pool) not in seen:
                seen.add(_addr(pool))
                pools.append(pool)
    return pools


def _chance(item, constant, attribute, init, scale):
    p = item.Probability
    p.BaseValueConstant = constant
    p.BaseValueAttribute = attribute
    p.InitializationDefinition = init
    p.BaseValueScaleConstant = scale
    item.Probability = p


def _switch_to_infinity() -> None:
    balance = infinity._find(infinity.BALANCE)
    if balance is None:
        return
    saved = []
    for pool in _output_pools():
        items = pool.BalancedItems
        if not len(items):
            continue
        rows = []
        for i in range(len(items)):
            it = items[i]
            p = it.Probability
            rows.append((it.ItmPoolDefinition, it.InvBalanceDefinition, p.BaseValueConstant, p.BaseValueAttribute,
                         p.InitializationDefinition, p.BaseValueScaleConstant))
            if i == 0:
                it.ItmPoolDefinition = None
                it.InvBalanceDefinition = balance
                _chance(it, 1.0, None, None, 1.0)
            else:
                _chance(it, 0.0, None, None, 0.0)
            items[i] = it
        saved.append((pool, rows))
    _state["saved"] = saved


def _switch_back() -> None:
    saved, _state["saved"] = _state["saved"], None
    for pool, rows in saved or []:
        items = pool.BalancedItems
        for i, (sub, bal, const, attr, init, scale) in enumerate(rows):
            if i >= len(items):
                break
            it = items[i]
            it.ItmPoolDefinition = sub
            it.InvBalanceDefinition = bal
            _chance(it, const, attr, init, scale)
            items[i] = it


@hook("WillowGame.GrinderRecipe:HasRecipe", Type.PRE, hook_identifier="InfinityTPSGrinderInputs")
def on_has_recipe(obj, args, *_) -> None:
    try:
        _state["inputs"] = list(args.BalanceDefinitions)
    except Exception:  # noqa: BLE001
        _state["inputs"] = []


def _before(label: str) -> None:
    if _state["saved"] is not None:
        _switch_back()
    try:
        if not _fits(_state["inputs"]):
            return
        _switch_to_infinity()
        log(f"Grinder: these three make an Infinity ({label})")
    except Exception as ex:  # noqa: BLE001
        log(f"Grinder: could not switch to the Infinity: {type(ex).__name__}: {ex}")
        try:
            _switch_back()
        except Exception:  # noqa: BLE001
            pass


def _after(ret) -> None:
    if _state["saved"] is None:
        return
    try:
        _switch_back()
    except Exception as ex:  # noqa: BLE001
        log(f"Grinder: could not switch the pools back: {type(ex).__name__}: {ex}")
    log(f"Grinder: done ({ret})")


@hook("WillowGame.GrinderRecipe:SpawnBalancedInventoryFromRecipe", Type.PRE, hook_identifier="InfinityTPSGrinderBefore")
def before_spawn(*_) -> None:
    _before("normal grind")


@hook("WillowGame.GrinderRecipe:SpawnBalancedInventoryFromRecipe", Type.POST, hook_identifier="InfinityTPSGrinderAfter")
def after_spawn(obj, args, ret, *_) -> None:
    _after(ret)


@hook("WillowGame.GrinderRecipe:SpawnLockedBalancedInventoryFromRecipe", Type.PRE, hook_identifier="InfinityTPSGrinderBeforeLocked")
def before_spawn_locked(*_) -> None:
    _before("moonstone grind")


@hook("WillowGame.GrinderRecipe:SpawnLockedBalancedInventoryFromRecipe", Type.POST, hook_identifier="InfinityTPSGrinderAfterLocked")
def after_spawn_locked(obj, args, ret, *_) -> None:
    _after(ret)


grinder_hooks = [on_has_recipe, before_spawn, after_spawn, before_spawn_locked, after_spawn_locked]
