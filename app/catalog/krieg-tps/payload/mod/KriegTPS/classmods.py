"""Krieg's class mods in the Pre-Sequel.

* His 11 Borderlands 2 class mods (Blister, Crunch, Meat, Reaper, Sickle, Slab, Toast, Torch, Wound,
  Legendary Psycho, Slayer of Terramorphous) come with his character package, but they point at
  Borderlands 2's GD_ClassMods / GD_ItemGrades objects, which the Pre-Sequel renamed to
  GD_Cork_ClassMods / GD_Cork_ItemGrades. Without them the class mods had no parts or bonuses and
  could not drop. Those references are re-pointed here (CLASSMOD_REFS).
* The legendary Reaper/Sickle/Torch (Ultimate Vault Hunter pack 2) and the nine Barbarian class mods
  (Tiny Tina's Assault on Dragon Keep) live in two small class-mod-only packages in Krieg's DLC
  folder, loaded once his character is loaded.
* Dropping: the Pre-Sequel picks class mods from each player's class pools (Krieg's are already set
  on his class), so once they work they drop like everyone else's. The DLC ones are added to his
  legendary and rare pools.
"""

import unrealsdk
from mods_base import ObjectFlags
from unrealsdk.unreal import WrappedStruct

from .classmod_refs import CLASSMOD_REFS

KRIEG_BALANCE = "GD_Lilac_ClassMods.BalanceDefs.BalDef_ClassMod_Psycho"
KRIEG_ITEM_SET = "GD_LilacPackageDef.CustomItemSetDef_Lilac"
POOLS = "GD_Lilac_Itempools.ClassModPools.Pool_ClassMod_LilacPlayerClass_"
# (package, balance definition, Krieg pool suffix, weight)
DLC_CLASSMODS = (
    ("Krieg_ClassMods_Lobelia_SF", "GD_Lobelia_ItemGrades.ClassMods.BalDef_ClassMod_Lobelia_Psycho_05_Legendary",
     "05_Legendary", 3.0),
    ("Krieg_ClassMods_Aster_SF", "GD_Aster_ItemGrades.ClassMods.BalDef_ClassMod_Aster_Psycho",
     "03_Rare", 1.0),
)

_loaded: set[str] = set()

# Co-op: the host tells joining players which packages its objects come from, by package name. These
# live inside Krieg's two class-mod files (whose file names differ), so a player who doesn't already
# have them in memory can't find them and the join fails with "Downloading package
# 'GD_Lobelia_ClassMods' failed". So every player loads both files at startup, whatever character
# they play, and keeps everything in them loaded for the whole session.
NETWORK_PACKAGES = {
    "Krieg_ClassMods_Lobelia_SF": ("GD_Lobelia_ClassMods", "GD_Lobelia_ItemGrades", "Lobelia_Char_Psycho"),
    "Krieg_ClassMods_Aster_SF": ("GD_Aster_ClassMods", "GD_Aster_ItemGrades", "Aster_Char_Psycho"),
}
_kept: set[str] = set()
_net_retry: dict[str, float] = {}
_net_tries: dict[str, int] = {}


def _keep_package_loaded(names: tuple) -> int:
    prefixes = tuple(n + "." for n in names)
    kept = 0
    for obj in unrealsdk.find_all("Object", exact=False):
        try:
            path = obj._path_name()
        except Exception:  # noqa: BLE001
            continue
        if path in names or path.startswith(prefixes):
            obj.ObjectFlags |= ObjectFlags.KEEP_ALIVE
            kept += 1
    return kept


def ensure_network_packages() -> None:
    """Load Krieg's class-mod files for every player (see NETWORK_PACKAGES), once."""
    import time as _time

    now = _time.monotonic()
    for package, inner in NETWORK_PACKAGES.items():
        if package in _kept or now < _net_retry.get(package, 0.0):
            continue
        if _find(inner[0]) is None:
            # The DLC folder may not be mounted yet this early in startup: try again shortly.
            _net_tries[package] = _net_tries.get(package, 0) + 1
            if _net_tries[package] > 24:      # not there (that Borderlands 2 DLC isn't owned)
                _kept.add(package)
                continue
            _net_retry[package] = now + 5.0
            try:
                unrealsdk.load_package(package)
                _loaded.add(package)
            except Exception as ex:  # noqa: BLE001
                if package not in _logged:
                    _logged.add(package)
                    log(f"co-op: could not load {package} yet: {type(ex).__name__}: {ex}")
                continue
            if _find(inner[0]) is None:
                continue
        _kept.add(package)
        try:
            n = _keep_package_loaded(inner)
            log(f"co-op: {package} loaded and kept ({n} objects in {', '.join(inner)})")
        except Exception as ex:  # noqa: BLE001
            log(f"co-op: could not keep {package} loaded: {type(ex).__name__}: {ex}")
_logged: set[str] = set()


def log(msg: str) -> None:
    from . import log as _log
    _log(msg)


def _find(path: str):
    try:
        return unrealsdk.find_object("Object", path)
    except ValueError:
        return None


def _get(container, key):
    return container[key] if isinstance(key, int) else getattr(container, key)


def _set(container, key, value) -> None:
    if isinstance(key, int):
        container[key] = value
    else:
        setattr(container, key, value)


def _set_path(container, path, value) -> bool:
    """Set container.<path> = value; returns True if it changed. Structs are written back."""
    key = path[0]
    if len(path) == 1:
        try:
            current = _get(container, key)
        except (IndexError, AttributeError):
            return False
        if current is not None:
            return False  # already resolved (or set by us earlier)
        _set(container, key, value)
        return True
    child = _get(container, key)
    changed = _set_path(child, path[1:], value)
    if changed and isinstance(child, WrappedStruct):
        _set(container, key, child)
    return changed


def _remap() -> int:
    targets: dict[str, object] = {}
    fixed = 0
    for obj_path, prop_path, target_path in CLASSMOD_REFS:
        obj = _find(obj_path)
        if obj is None:
            continue
        target = targets.get(target_path)
        if target is None:
            target = _find(target_path)
            if target is None:
                if target_path not in _logged:
                    _logged.add(target_path)
                    log(f"class mods: {target_path} not found")
                continue
            targets[target_path] = target
        try:
            if _set_path(obj, prop_path, target):
                fixed += 1
        except Exception as ex:  # noqa: BLE001
            key = f"{obj_path}:{prop_path}"
            if key not in _logged:
                _logged.add(key)
                log(f"class mods: could not set {obj_path}.{prop_path}: {type(ex).__name__}: {ex}")
    return fixed


def _add_to_pool(pool, balance, weight: float) -> bool:
    items = pool.BalancedItems
    for entry in items:
        if entry.InvBalanceDefinition is not None and \
                entry.InvBalanceDefinition._path_name() == balance._path_name():
            return False
    if len(items) == 0:
        return False
    template = items[0]
    prob = unrealsdk.make_struct(template.Probability._type.Name, BaseValueConstant=weight,
                                 BaseValueAttribute=None, InitializationDefinition=None,
                                 BaseValueScaleConstant=1.0)
    entry = unrealsdk.make_struct(template._type.Name, ItmPoolDefinition=None, InvBalanceDefinition=balance,
                                  Probability=prob, bDropOnDeath=True)
    items.append(entry)
    return True


def upkeep() -> None:
    try:
        ensure_network_packages()
    except Exception as ex:  # noqa: BLE001
        log(f"co-op package load failed: {type(ex).__name__}: {ex}")
    try:
        _cleanup_if_not_krieg()
    except Exception as ex:  # noqa: BLE001
        log(f"class mod cleanup failed: {type(ex).__name__}: {ex}")
    krieg_balance = _find(KRIEG_BALANCE)
    if krieg_balance is None:
        return  # Krieg's character package is not loaded yet
    fixed = _remap()
    item_set = _find(KRIEG_ITEM_SET)
    for package, balance_path, pool_suffix, weight in DLC_CLASSMODS:
        balance = _find(balance_path)
        if balance is None and package not in _loaded:
            _loaded.add(package)  # one attempt per session
            try:
                unrealsdk.load_package(package)
            except Exception as ex:  # noqa: BLE001
                log(f"class mods: could not load {package}: {type(ex).__name__}: {ex}")
                continue
            balance = _find(balance_path)
            log(f"class mods: loaded {package} ({'ok' if balance is not None else 'balance missing'})")
            fixed += _remap()
        if balance is None:
            continue
        balance.ObjectFlags |= ObjectFlags.KEEP_ALIVE
        if item_set is not None and balance.DlcItemSet is None:
            balance.DlcItemSet = item_set
        pool = _find(POOLS + pool_suffix)
        try:
            if pool is not None and _add_to_pool(pool, balance, weight):
                log(f"class mods: {balance_path.rsplit('.', 1)[1]} now drops from Krieg's {pool_suffix} pool")
        except Exception as ex:  # noqa: BLE001
            if balance_path not in _logged:
                _logged.add(balance_path)
                log(f"class mods: could not add {balance_path} to the {pool_suffix} pool: {type(ex).__name__}: {ex}")
    if fixed:
        log(f"class mods: re-pointed {fixed} references to the Pre-Sequel's class mod parts")
    try:
        drop_check()
    except Exception as ex:  # noqa: BLE001
        _check["done"] = True
        log(f"class mod check failed: {type(ex).__name__}: {ex}")


# ---------------------------------------------------------------------------
# Drop check: once per session, in a real level, roll the game's own class mod drop pools a few
# times for Krieg and log what comes out, so it's clear from the log whether his class mods can
# actually drop. If the game's pools never pick his, his pools are added to them directly.
# ---------------------------------------------------------------------------
import time as _time  # noqa: E402

from mods_base import get_pc  # noqa: E402

GAME_POOLS = (
    ("GD_Itempools.ClassModPools.Pool_ClassMod_01_Common", "01_Common"),
    ("GD_Itempools.ClassModPools.Pool_ClassMod_02_Uncommon", "02_Uncommon"),
    ("GD_Itempools.ClassModPools.Pool_ClassMod_04_Rare", "03_Rare"),
    ("GD_Itempools.ClassModPools.Pool_ClassMod_05_VeryRare", "04_VeryRare"),
    ("GD_Itempools.ClassModPools.Pool_ClassMod_06_Legendary", "05_Legendary"),
)
ROLLS = 12
_check = {"done": False, "start": None, "injected": False}


def _is_krieg(pc) -> bool:
    try:
        return pc.PlayerClass is not None and "Lilac" in pc.PlayerClass._path_name()
    except Exception:  # noqa: BLE001
        return False


def _level(pc) -> int:
    try:
        return max(1, int(pc.PlayerReplicationInfo.ExpLevel))
    except Exception:  # noqa: BLE001
        return 1


def _roll(pool, pawn, level: int):
    cdo = unrealsdk.find_class("ItemPool").ClassDefaultObject
    result = cdo.SpawnBalancedInventoryFromPool(Definition=pool, GameStage=level, AwesomeLevel=0,
                                                ContextSource=pawn, SpawnedInventory=[],
                                                GameStageVarianceFormula=None, OuterPoolChance=1.0,
                                                bInventoryMayDropOnDeath=False,
                                                bIgnoreGameStageRequirement=True)
    spawned = result[1] if isinstance(result, tuple) and len(result) > 1 else []
    names = []
    for inv in spawned:
        try:
            bal = inv.DefinitionData.BalanceDefinition
            names.append(bal.Name if bal is not None else "?")
        except Exception:  # noqa: BLE001
            names.append("?")
        try:
            inv.Destroy()
        except Exception:  # noqa: BLE001
            pass
    return names


def _inject(pool, krieg_pool) -> bool:
    """Make the game's class mod pool also offer Krieg's pool (only while playing Krieg)."""
    items = pool.BalancedItems
    for entry in items:
        if entry.ItmPoolDefinition is not None and entry.ItmPoolDefinition._path_name() == krieg_pool._path_name():
            return False
    template = items[0] if len(items) else None
    entry_type = template._type.Name if template is not None else "BalancedInventoryInteractionData"
    prob_type = template.Probability._type.Name if template is not None else "AttributeInitializationData"
    prob = unrealsdk.make_struct(prob_type, BaseValueConstant=1.0, BaseValueAttribute=None,
                                 InitializationDefinition=None, BaseValueScaleConstant=1.0)
    items.append(unrealsdk.make_struct(entry_type, ItmPoolDefinition=krieg_pool, InvBalanceDefinition=None,
                                       Probability=prob, bDropOnDeath=True))
    return True


def _uninject() -> None:
    for path, _ in GAME_POOLS:
        pool = _find(path)
        if pool is None:
            continue
        items = pool.BalancedItems
        for i in reversed(range(len(items))):
            p = items[i].ItmPoolDefinition
            if p is not None and p._path_name().startswith(POOLS):
                del items[i]
    _check["injected"] = False
    log("class mod check: someone else is played; Krieg's pools taken back out of the game's pools")


def _cleanup_if_not_krieg() -> None:
    """Krieg's pools must never stay in the game's pools once someone else is played: his package
    gets unloaded and reloaded, and a leftover reference to it could crash the game."""
    if not _check["injected"]:
        return
    pc = get_pc()
    if pc is not None and pc.PlayerClass is not None and not _is_krieg(pc):
        _uninject()
        _check["done"] = False
        _check["start"] = None


def drop_check() -> None:
    pc = get_pc()
    if _check["done"]:
        return
    if pc is None or not _is_krieg(pc) or pc.Pawn is None:
        return
    try:
        world = str(pc.WorldInfo.GetStreamingPersistentMapName()).lower()
    except Exception:  # noqa: BLE001
        world = ""
    if not world or "menu" in world:
        return
    now = _time.monotonic()
    if _check["start"] is None:
        _check["start"] = now
    if now - _check["start"] < 10.0:   # let the level settle first
        return
    _check["done"] = True
    level = _level(pc)
    krieg_hits = 0
    for path, suffix in GAME_POOLS:
        pool = _find(path)
        if pool is None:
            log(f"class mod check: {path} not loaded")
            continue
        try:
            got = []
            for _ in range(ROLLS):
                got += _roll(pool, pc.Pawn, level)
            mine = [n for n in got if "Psycho" in n or "Lilac" in n]
            krieg_hits += len(mine)
            listed = any(e.ItmPoolDefinition is not None and e.ItmPoolDefinition._path_name().startswith(POOLS)
                         for e in pool.BalancedItems)
            log(f"class mod check: {suffix}: {ROLLS} rolls (ignoring the level requirement) gave {len(got)} items, "
                f"{len(mine)} Krieg's; e.g. {sorted(set(got))[:6]}; "
                f"pool lists {len(pool.BalancedItems)} entries, Krieg's pool {'included' if listed else 'MISSING'}")
        except Exception as ex:  # noqa: BLE001
            log(f"class mod check: rolling {suffix} failed: {type(ex).__name__}: {ex}")
    # Krieg's own pool directly: do his class mods spawn at all?
    own = _find(POOLS + "01_Common")
    if own is not None:
        try:
            got = []
            for _ in range(4):
                got += _roll(own, pc.Pawn, level)
            log(f"class mod check: Krieg's own common pool gave {got}")
        except Exception as ex:  # noqa: BLE001
            log(f"class mod check: rolling Krieg's own pool failed: {type(ex).__name__}: {ex}")
    if krieg_hits == 0:
        added = 0
        for path, suffix in GAME_POOLS:
            pool, mine = _find(path), _find(POOLS + suffix)
            if pool is None or mine is None:
                continue
            try:
                added += _inject(pool, mine)
            except Exception as ex:  # noqa: BLE001
                log(f"class mod check: could not add Krieg's {suffix} pool: {type(ex).__name__}: {ex}")
        _check["injected"] = added > 0
        log(f"class mod check: no Krieg class mods came out; added his pools to {added} of the game's pools "
            f"(the rest already had them)")
