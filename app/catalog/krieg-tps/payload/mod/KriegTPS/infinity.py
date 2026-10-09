"""Borderlands 2's Infinity pistol, made in the Grinder.

The Infinity is a Vladof legendary pistol: it never uses ammo, fires in a figure-8 (an infinity
sign), spins up two barrels, and has its own skin ("Infinity" pattern) and red text ("It's closer
than you think! (no it isn't)"). The Pre-Sequel still has everything it is built from - the Vladof
pistol body, barrel model, parts, elements and the Infinity pattern texture - but not the gun
itself. This rebuilds it from Borderlands 2's own data (infinity_data.py, read from Borderlands 2's
Startup.upk) under the same names it has in Borderlands 2:
* barrel (no ammo use, one-round display, two spinning barrels, accuracy, legendary rarity),
* the figure-8 firing pattern, the title "Infinity" with its red text,
* the Dva accessory (25% chance of an extra shot) and its legendary skin,
* its parts list: Borderlands 2's elements (none, fire, shock, corrosive) and accessories; grips,
  sights and the rest come from the purple Vladof pistol, so every one rolls differently.
Grinder: three purple Vladof pistols make an Infinity.
"""

import unrealsdk
from mods_base import ObjectFlags, command

from .infinity_data import MATERIAL, OBJECTS

BALANCE = "GD_Weap_Pistol.A_Weapons_Legendary.Pistol_Vladof_5_Infinity"
MIC_PATH = "Common_GunMaterials.Materials.Pistol.Mati_VladofLegendaryPistol_Infinity"
MIC_PARENT = "Common_GunMaterials.MasterMaterials.Vladof.MasterMati_VladofLegendary"
RECIPE_INPUT = "GD_Weap_Pistol.A_Weapons.Pistol_Vladof_4_VeryRare"     # purple Vladof pistol
RECIPES = "GD_GrinderRecipes.GrinderRecipes"
POOL_TEMPLATE = "GD_Itempools.GrinderPools.Pool_Recipe_Upgrade_SMG_04_GoodTouch"
POOL_NAME = "Pool_Recipe_Infinity"

# what each new object is made from (a Pre-Sequel object of the same kind)
SHELLS = (
    # (path, class, template or None)
    ("GD_Weap_Pistol.FiringModes.Bullet_Pistol_Infinity", "FiringModeDefinition",
     "GD_Weap_Pistol.FiringModes.Bullet_Pistol_Default"),
    ("GD_Weap_Pistol.Name.Title_Vladof.Title_Legendary_Infinity", "WeaponNamePartDefinition",
     "GD_Weap_Pistol.Name.Title_Vladof.Title_Barrel_Vladof_Rapid"),
    ("GD_Weap_Pistol.Name.Title_Vladof.Title_Legendary_Infinity.AttributePresentationDefinition_8",
     "AttributePresentationDefinition", None),
    (MIC_PATH, "MaterialInstanceConstant", None),
    ("GD_Weap_Pistol.ManufacturerMaterials.Mat_Vladof_5_Legendary", "WeaponPartDefinition",
     "GD_Weap_Pistol.ManufacturerMaterials.Mat_Vladof_4"),
    ("GD_Weap_Pistol.Accessory.Pistol_Accessory_Laser_Double_DvaInfinity", "WeaponPartDefinition",
     "GD_Weap_Pistol.Accessory.Pistol_Accessory_Laser_Double"),
    ("GD_Weap_Pistol.Barrel.Pistol_Barrel_Vladof_Infinity", "WeaponPartDefinition",
     "GD_Weap_Pistol.Barrel.Pistol_Barrel_Vladof"),
    (BALANCE, "WeaponBalanceDefinition", None),
    (BALANCE + ".PartList", "WeaponPartListCollectionDefinition", None),
)
ENUM_FALLBACK = {"MT_Scale": 0, "MT_PreAdd": 1, "MT_PostAdd": 2,
                 "EPRM_Additive": 0, "EPRM_Selective": 1, "EPRM_Complete": 2}

_state = {"done": False, "tries": 0, "objects": [], "recipe": False, "errors": 0}


def log(msg: str) -> None:
    from . import log as _log
    _log("Infinity: " + msg)


def _find(path: str, cls: str = "Object"):
    try:
        return unrealsdk.find_object(cls, path)
    except ValueError:
        return None


def _keep(obj) -> None:
    obj.ObjectFlags |= ObjectFlags.KEEP_ALIVE
    _state["objects"].append(obj)


def _make(path: str, cls: str, template_path):
    obj = _find(path)
    if obj is not None:
        return obj
    outer_path, name = path.rsplit(".", 1)
    outer = _find(outer_path)
    if outer is None:
        raise LookupError(f"{outer_path} isn't loaded")
    template = _find(template_path) if template_path else None
    if template_path and template is None:
        raise LookupError(f"{template_path} isn't loaded")
    if template is not None:
        return unrealsdk.construct_object(cls, outer, name, template_obj=template)
    return unrealsdk.construct_object(cls, outer, name)


# ---------------------------------------------------------------------------------------------
# writing Borderlands 2's values onto the new objects
# ---------------------------------------------------------------------------------------------
def _resolve(v):
    if isinstance(v, str) and v.startswith("@"):
        obj = _find(v[1:])
        if obj is None:
            raise LookupError(v[1:])
        return obj
    return v


def _enum_value(owner, key: str, name: str):
    try:
        prop = owner._type._find_prop(key) if hasattr(owner, "_type") else owner.Class._find_prop(key)
        enum = unrealsdk.find_enum(prop.Enum.Name)
        return enum[name]
    except Exception:  # noqa: BLE001
        return ENUM_FALLBACK[name]


def _new_struct(arr):
    try:
        arr.emplace_struct()
        return
    except Exception:  # noqa: BLE001
        pass
    arr.append(unrealsdk.make_struct(arr._type.Inner.Struct.Name))


def _set(target, key: str, val) -> None:
    if val is None:
        setattr(target, key, None)
        return
    if isinstance(val, dict):
        if "struct" in val:
            cur = getattr(target, key)
            _apply(cur, val["struct"])
            setattr(target, key, cur)
        elif "enum" in val:
            setattr(target, key, _enum_value(target, key, val["enum"]))
        elif "name" in val:
            setattr(target, key, val["name"])
        return
    if isinstance(val, list):
        arr = getattr(target, key)
        while len(arr):
            arr.pop()
        for item in val:
            if isinstance(item, dict) and "struct" in item:
                _new_struct(arr)
                el = arr[len(arr) - 1]
                _apply(el, item["struct"])
                arr[len(arr) - 1] = el
            else:
                arr.append(_resolve(item))
        return
    setattr(target, key, _resolve(val))


def _apply(target, props: dict) -> None:
    for key, val in props.items():
        try:
            _set(target, key, val)
        except Exception as ex:  # noqa: BLE001
            _state["errors"] += 1
            if _state["errors"] <= 25:
                log(f"could not set {key}: {type(ex).__name__}: {ex}")


def _material(mic) -> None:
    parent = _find(MIC_PARENT)
    if parent is not None:
        try:
            mic.SetParent(parent)
        except Exception:  # noqa: BLE001
            mic.Parent = parent
    for name, value in MATERIAL["scalar"]:
        mic.SetScalarParameterValue(name, float(value))
    for name, ref in MATERIAL["texture"]:
        tex = _find(ref[1:])
        if tex is not None:
            mic.SetTextureParameterValue(name, tex)
    for name, c in MATERIAL["vector"]:
        mic.SetVectorParameterValue(name, unrealsdk.make_struct("LinearColor", R=c["R"], G=c["G"], B=c["B"], A=c["A"]))


# ---------------------------------------------------------------------------------------------
# Grinder recipe: three purple Vladof pistols -> an Infinity
# ---------------------------------------------------------------------------------------------
def _add_recipe(balance) -> None:
    holder = _find(RECIPES)
    template_pool = _find(POOL_TEMPLATE)
    purple = _find(RECIPE_INPUT)
    if holder is None or template_pool is None or purple is None:
        log("the Grinder's recipes aren't loaded yet")
        return
    pool = _find(f"{template_pool.Outer._path_name()}.{POOL_NAME}")
    if pool is None:
        pool = unrealsdk.construct_object("ItemPoolDefinition", template_pool.Outer, POOL_NAME,
                                          template_obj=template_pool)
    _keep(pool)
    items = pool.BalancedItems
    while len(items) > 1:
        items.pop()
    first = items[0]
    first.ItmPoolDefinition = None
    first.InvBalanceDefinition = balance
    first.ProbabilityDisplayString = "100.00%"
    items[0] = first
    try:
        pool.MinGameStageRequirement = None
    except Exception:  # noqa: BLE001
        pass
    recipes = holder.GrinderRecipes
    for r in recipes:
        if r.OutputItemPoolDefinition is not None and r.OutputItemPoolDefinition._get_address() == pool._get_address():
            _state["recipe"] = True
            return
    model = next((r for r in recipes if len(r.InputInvBalanceDefinitions)), None)
    if model is None:
        log("no balance-based Grinder recipe to copy")
        return
    recipes.append(model)
    new = recipes[len(recipes) - 1]
    new.InputItemPoolDefinitions = []
    new.InputInvBalanceDefinitions = [purple, purple, purple]
    new.OutputItemPoolDefinition = pool
    new.OutputInvBalanceDefinition = None
    locked = new.OutputLockedItemPoolDefinition
    locked.LockedItemPoolDefinition = pool
    new.OutputLockedItemPoolDefinition = locked
    recipes[len(recipes) - 1] = new
    _state["recipe"] = True
    log("Grinder recipe added: 3 purple Vladof pistols -> Infinity")


# ---------------------------------------------------------------------------------------------
def build() -> None:
    if _state["done"] or _state["tries"] >= 5:
        return
    _state["tries"] += 1
    try:
        made = {}
        for path, cls, template in SHELLS:
            made[path] = _make(path, cls, template)
            _keep(made[path])
        for path, props in OBJECTS.items():
            _apply(made[path], props)
        _material(made[MIC_PATH])
        bal = made[BALANCE]
        _add_recipe(bal)
        _state["done"] = True
        log(f"ready ({len(made)} parts made from Borderlands 2's data"
            + (f", {_state['errors']} setting(s) skipped" if _state["errors"] else "") + ")")
    except Exception as ex:  # noqa: BLE001
        log(f"not ready yet (try {_state['tries']}): {type(ex).__name__}: {ex}")


def upkeep() -> None:
    build()


@command("krieg_infinity", description="Write whether the Infinity pistol and its Grinder recipe are set up to the Krieg log.")
def krieg_infinity(_args) -> None:
    bal = _find(BALANCE)
    log(f"balance {'present' if bal is not None else 'MISSING'}, Grinder recipe "
        f"{'added' if _state['recipe'] else 'not added'}, {_state['errors']} setting(s) skipped")
    if not _state["done"]:
        _state["tries"] = 0
        build()


infinity_hooks = [krieg_infinity]
