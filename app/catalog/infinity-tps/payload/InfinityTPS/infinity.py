"""Borderlands 2's Infinity pistol, made in the Grinder.

The Infinity is a Vladof legendary pistol: it never uses ammo, fires in a figure-8 (an infinity
sign), spins up two barrels, and has its own skin ("Infinity" pattern) and red text ("It's closer
than you think! (no it isn't)"). The Pre-Sequel still has everything it is built from - the Vladof
pistol body, barrel model, parts, elements and the Infinity pattern texture - but not the gun
itself. This rebuilds it from Borderlands 2's own data (infinity_data.py, read from Borderlands 2's
Startup.upk). The gun and its own parts get the names the Pre-Sequel's item lists already keep
for it (GD_Cork_Weap_Pistol..., left over from when Gearbox cut it), so an Infinity saves and
loads like any other gun:
* barrel (no ammo use, one-round display, two spinning barrels, accuracy, legendary rarity),
* the figure-8 firing pattern, the title "Infinity" with its red text,
* the Dva accessory (25% chance of an extra shot) and its legendary skin,
* its parts list: Borderlands 2's elements (none, fire, shock, corrosive) and accessories; grips,
  sights and the rest come from the purple Vladof pistol, so every one rolls differently.
Grinder: a legendary pistol, any legendary weapon and any purple pistol make an Infinity.
"""

import unrealsdk
from mods_base import ObjectFlags, command

from .infinity_data import MATERIAL, OBJECTS as _BL2_OBJECTS

# Borderlands 2 name -> the name the Pre-Sequel's asset libraries list it under. Saves store a gun
# as positions in those lists, so the objects have to live exactly there.
RENAME = {
    "GD_Weap_Pistol.A_Weapons_Legendary.Pistol_Vladof_5_Infinity":
        "GD_Cork_Weap_Pistol.A_Weapons_Legendary.Pistol_Vladof_5_Infinity",
    "GD_Weap_Pistol.Barrel.Pistol_Barrel_Vladof_Infinity":
        "GD_Cork_Weap_Pistol.Barrel.Pistol_Barrel_Vladof_Infinity",
    "GD_Weap_Pistol.Accessory.Pistol_Accessory_Laser_Double_DvaInfinity":
        "GD_Cork_Weap_Pistol.Accessory.Pistol_Accessory_Laser_Double_DvaInfinity",
    "GD_Weap_Pistol.Name.Title_Vladof.Title_Legendary_Infinity":
        "GD_Cork_Weap_Pistol.Name.Title_Vladof.Title_Legendary_Infinity",
}


def _renamed(path: str) -> str:
    for old, new in RENAME.items():
        if path == old or path.startswith(old + "."):
            return new + path[len(old):]
    return path


def _rename_refs(v):
    if isinstance(v, str) and v.startswith("@"):
        return "@" + _renamed(v[1:])
    if isinstance(v, dict):
        return {k: _rename_refs(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_rename_refs(x) for x in v]
    return v


OBJECTS = {_renamed(k): _rename_refs(v) for k, v in _BL2_OBJECTS.items()}


def _pre_sequel_weights(objects: dict) -> None:
    """Borderlands 2 lists each Infinity part with a 'Manufacturers' entry of None (any maker) and
    a 0 default weight on the barrel and skin. The Pre-Sequel reads those as weight 0, so every
    Infinity part was skipped and the gun came out with the purple Vladof pistol's normal parts.
    Written the way the Pre-Sequel's own legendaries (the Maggie) are: no maker list, and the
    barrel and skin at weight 1 (ConsolidatedAttributeInitData[0] is 1.0)."""
    for path, props in objects.items():
        if not path.endswith(".PartList"):
            continue
        for slot, data in props.items():
            if not (slot.endswith("PartData") and isinstance(data, dict) and "struct" in data):
                continue
            for entry in data["struct"].get("WeightedParts", []):
                fields = entry["struct"]
                fields["Manufacturers"] = []
                if slot in ("BarrelPartData", "MaterialPartData"):
                    fields["DefaultWeightIndex"] = 0


_pre_sequel_weights(OBJECTS)

# (asset library, sublibrary, index) each new object is listed at in the Pre-Sequel
LIBRARY_SLOTS = {
    "GD_Cork_Weap_Pistol.A_Weapons_Legendary.Pistol_Vladof_5_Infinity": ("AL_Balance", 122, 19),
    "GD_Cork_Weap_Pistol.Barrel.Pistol_Barrel_Vladof_Infinity": ("AL_WeaponParts", 11, 43),
    "GD_Cork_Weap_Pistol.Accessory.Pistol_Accessory_Laser_Double_DvaInfinity": ("AL_WeaponParts", 11, 50),
    "GD_Cork_Weap_Pistol.Name.Title_Vladof.Title_Legendary_Infinity": ("AL_WeaponParts", 11, 52),
    "GD_Weap_Pistol.ManufacturerMaterials.Mat_Vladof_5_Legendary": ("AL_WeaponParts", 19, 296),
}

BALANCE = "GD_Cork_Weap_Pistol.A_Weapons_Legendary.Pistol_Vladof_5_Infinity"
MIC_PATH = "Common_GunMaterials.Materials.Pistol.Mati_VladofLegendaryPistol_Infinity"
MIC_PARENT = "Common_GunMaterials.MasterMaterials.Vladof.MasterMati_VladofLegendary"
LEGENDARY_PISTOLS = "GD_Itempools.WeaponPools.Pool_Weapons_Pistols_06_Legendary"
LEGENDARY_WEAPONS = "GD_Itempools.GrinderPools.Pool_Weapons_All_06_Legendary_Grinder"
PURPLE_PISTOLS = "GD_Itempools.WeaponPools.Pool_Weapons_Pistols_05_VeryRare"   # any purple pistol
RECIPES = "GD_GrinderRecipes.GrinderRecipes"
POOL_TEMPLATE = "GD_Itempools.GrinderPools.Pool_Recipe_Upgrade_SMG_04_GoodTouch"
POOL_NAME = "Pool_Recipe_Infinity"

# what each new object is made from (a Pre-Sequel object of the same kind)
SHELLS = (
    # (path, class, template or None)
    ("GD_Weap_Pistol.FiringModes.Bullet_Pistol_Infinity", "FiringModeDefinition",
     "GD_Weap_Pistol.FiringModes.Bullet_Pistol_Default"),
    ("GD_Cork_Weap_Pistol.Name.Title_Vladof.Title_Legendary_Infinity", "WeaponNamePartDefinition",
     "GD_Weap_Pistol.Name.Title_Vladof.Title_Barrel_Vladof_Rapid"),
    ("GD_Cork_Weap_Pistol.Name.Title_Vladof.Title_Legendary_Infinity.AttributePresentationDefinition_8",
     "AttributePresentationDefinition", None),
    (MIC_PATH, "MaterialInstanceConstant", None),
    ("GD_Weap_Pistol.ManufacturerMaterials.Mat_Vladof_5_Legendary", "WeaponPartDefinition",
     "GD_Weap_Pistol.ManufacturerMaterials.Mat_Vladof_4"),
    ("GD_Cork_Weap_Pistol.Accessory.Pistol_Accessory_Laser_Double_DvaInfinity", "WeaponPartDefinition",
     "GD_Weap_Pistol.Accessory.Pistol_Accessory_Laser_Double"),
    ("GD_Cork_Weap_Pistol.Barrel.Pistol_Barrel_Vladof_Infinity", "WeaponPartDefinition",
     "GD_Weap_Pistol.Barrel.Pistol_Barrel_Vladof"),
    (BALANCE, "WeaponBalanceDefinition", None),
    (BALANCE + ".PartList", "WeaponPartListCollectionDefinition", None),
)
ENUM_FALLBACK = {"MT_Scale": 0, "MT_PreAdd": 1, "MT_PostAdd": 2,
                 "EPRM_Additive": 0, "EPRM_Selective": 1, "EPRM_Complete": 2}

_state = {"done": False, "tries": 0, "objects": [], "recipe": False, "errors": 0, "listed": 0}


def log(msg: str) -> None:
    from . import log as _log
    _log(msg)


def _find(path: str, cls: str = "Object"):
    try:
        return unrealsdk.find_object(cls, path)
    except ValueError:
        return None


def _keep(obj) -> None:
    obj.ObjectFlags |= ObjectFlags.KEEP_ALIVE
    _state["objects"].append(obj)


def _package(path: str):
    """The object at path; missing packages inside an already loaded one are made empty."""
    obj = _find(path)
    if obj is not None:
        return obj
    if "." not in path:
        raise LookupError(f"{path} isn't loaded")
    outer_path, name = path.rsplit(".", 1)
    outer = _package(outer_path)
    pkg = unrealsdk.construct_object("Package", outer, name)
    _keep(pkg)
    return pkg


def _make(path: str, cls: str, template_path):
    obj = _find(path)
    if obj is not None:
        return obj
    outer_path, name = path.rsplit(".", 1)
    outer = _package(outer_path)
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


# Borderlands 2 keeps a part's game stages and weight both as values and as indexes into the part
# list's ConsolidatedAttributeInitData; the Pre-Sequel only has the indexes, which are set too.
BL2_ONLY = {"MinGameStage", "MaxGameStage", "DefaultWeight"}


def _apply(target, props: dict) -> None:
    for key, val in props.items():
        if key in BL2_ONLY and not hasattr(target, key):
            continue
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
# Grinder recipe: legendary pistol + any legendary weapon + any purple pistol -> an Infinity
# ---------------------------------------------------------------------------------------------
def _pool_of_one(template, name: str, balance):
    """An item pool holding just one gun (a copy of template with its list cut to that gun)."""
    pool = _find(f"{template.Outer._path_name()}.{name}")
    if pool is None:
        pool = unrealsdk.construct_object("ItemPoolDefinition", template.Outer, name, template_obj=template)
    _keep(pool)
    items = pool.BalancedItems
    while len(items) > 1:
        items.pop()
    first = items[0]
    first.ItmPoolDefinition = None
    first.InvBalanceDefinition = balance
    # a plain 100% chance: the template's chance is worked out from the Grinder's context,
    # which came out as nothing ("FailedToSpawnItem") for the Infinity
    try:
        chance = first.Probability
        chance.BaseValueConstant = 1.0
        chance.BaseValueAttribute = None
        chance.InitializationDefinition = None
        chance.BaseValueScaleConstant = 1.0
        first.Probability = chance
    except Exception as ex:  # noqa: BLE001
        log(f"could not set the pool's chance: {type(ex).__name__}: {ex}")
    items[0] = first
    for field in ("MinGameStageRequirement", "MaxGameStageRequirement"):
        try:
            setattr(pool, field, None)
        except Exception:  # noqa: BLE001
            pass
    return pool


def _add_recipe(balance) -> None:
    """Grinder: legendary pistol + any legendary weapon + any purple pistol -> Infinity.
    Put first in the Grinder's list, ahead of the game's own "two legendaries and a purple
    pistol make a legendary pistol" recipe, which the same three guns also fit."""
    holder = _find(RECIPES)
    out_template = _find(POOL_TEMPLATE)
    leg_pistols = _find(LEGENDARY_PISTOLS)
    leg_any = _find(LEGENDARY_WEAPONS)
    purple_pistols = _find(PURPLE_PISTOLS)
    if None in (holder, out_template, leg_pistols, leg_any, purple_pistols):
        if _state.get("recipe_note") != "missing":
            _state["recipe_note"] = "missing"
            log("the Grinder's recipes aren't loaded yet (they load with Concordia)")
        _state["recipe"] = False
        return
    output = _pool_of_one(out_template, POOL_NAME, balance)
    recipes = holder.GrinderRecipes
    for r in recipes:
        if r.OutputItemPoolDefinition is not None and r.OutputItemPoolDefinition._get_address() == output._get_address():
            _state["recipe"] = True
            return
    _state["recipe_note"] = "adding"
    model = next((r for r in recipes if len(r.InputItemPoolDefinitions) == 3), None)
    if model is None:
        log("no Grinder recipe to copy")
        return
    recipes.insert(0, model)
    new = recipes[0]
    new.InputItemPoolDefinitions = [leg_pistols, leg_any, purple_pistols]
    new.InputInvBalanceDefinitions = []
    new.OutputItemPoolDefinition = output
    new.OutputInvBalanceDefinition = None
    locked = new.OutputLockedItemPoolDefinition
    locked.LockedItemPoolDefinition = output
    new.OutputLockedItemPoolDefinition = locked
    recipes[0] = new
    _state["recipe"] = True
    log("Grinder recipe added: legendary pistol + legendary weapon + any purple pistol -> Infinity")


# ---------------------------------------------------------------------------------------------
# asset libraries: what lets an Infinity be saved, loaded and sent to the other player in co-op
# ---------------------------------------------------------------------------------------------
def _list_in_libraries(made: dict) -> None:
    """The game finds a saved gun's parts by these paths (each library entry is a package name
    plus a path), so having the objects at exactly those paths is what lets an Infinity save.
    This only checks and logs that every entry now finds its object."""
    found = 0
    for path in LIBRARY_SLOTS:
        if _find(path) is not None:
            found += 1
        else:
            log(f"missing for saving: {path}")
    _state["listed"] = found
    log(f"{found} of {len(LIBRARY_SLOTS)} Infinity parts are where the game's item lists look for them")


# ---------------------------------------------------------------------------------------------
def build() -> None:
    if _state["done"]:
        # the Grinder's recipe list is reloaded with the level, so check it is still there
        _add_recipe(_find(BALANCE))
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
        _list_in_libraries(made)
        _add_recipe(bal)
        _state["done"] = True
        log(f"ready ({len(made)} parts made from Borderlands 2's data"
            + (f", {_state['errors']} setting(s) skipped" if _state["errors"] else "") + ")")
    except Exception as ex:  # noqa: BLE001
        if _state["tries"] <= 5 or _state["tries"] % 60 == 0:
            log(f"not ready yet (try {_state['tries']}): {type(ex).__name__}: {ex}")


def upkeep() -> None:
    build()


@command("infinity_status", description="Write whether the Infinity pistol and its Grinder recipe are set up to infinity_log.txt.")
def infinity_status(_args) -> None:
    bal = _find(BALANCE)
    log(f"balance {'present' if bal is not None else 'MISSING'}, Grinder recipe "
        f"{'added' if _state['recipe'] else 'not added'}, {_state['listed']} part(s) listed for saving, "
        f"{_state['errors']} setting(s) skipped")
    if not _state["done"]:
        _state["tries"] = 0
        build()


infinity_hooks = [infinity_status]
