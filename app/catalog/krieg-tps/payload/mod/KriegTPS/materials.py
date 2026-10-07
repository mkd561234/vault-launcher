"""Make Krieg's skins and heads render in the Pre-Sequel.

Krieg's materials are instances of Common_Materials.Player.Master_Player, the same master
material every Pre-Sequel character uses, with the same parameter names (p_Diffuse, p_Normal,
p_Masks, p_AColor*/p_BColor*/p_CColor*). But each of his instances carries its own compiled
"static permutation", and those shaders only exist in Borderlands 2's shader cache. Without them
the Pre-Sequel draws the default grey material.

Fix: turn each of Krieg's instances into a plain child of Aurelia's body (or hands) instance,
whose permutation *is* compiled in the Pre-Sequel. His own textures and colour parameters stay,
so every head and skin keeps its look.
"""

import unrealsdk
from mods_base import ObjectFlags

from .krieg_objects import EXTRA_MATERIAL_INSTANCES, MATERIAL_INSTANCES

ALL_MATERIAL_INSTANCES = MATERIAL_INSTANCES + EXTRA_MATERIAL_INSTANCES

MASTER_PLAYER = "Common_Materials.Player.Master_Player"
KRIEG_MATERIAL_PACKAGES = ("CD_Skins_Psycho_Lilac", "CD_Heads_Psycho_Lilac", "Lilac_Char_Psycho")
TEMPLATE_PACKAGE = "Crocus_Baroness_Streaming_SF"
TEMPLATE_BODY = "Char_Baroness.Mati_Baroness_Body"
TEMPLATE_HANDS = "Char_Baroness.Mati_Baroness_Hands"

_templates: dict[str, object] = {}


def log(msg: str) -> None:
    from . import log as _log
    _log(msg)


def _find_mic(path: str):
    try:
        return unrealsdk.find_object("MaterialInstanceConstant", path)
    except ValueError:
        return None


_load_attempted = False


def _get_template(path: str):
    global _load_attempted
    obj = _templates.get(path)
    if obj is not None:
        return obj
    obj = _find_mic(path)
    if obj is None:
        if _load_attempted:
            return None
        _load_attempted = True
        try:
            unrealsdk.load_package(TEMPLATE_PACKAGE)
        except Exception as ex:  # noqa: BLE001
            log(f"could not load {TEMPLATE_PACKAGE} for Krieg's materials: {ex}")
            return None
        obj = _find_mic(path)
    if obj is None:
        log(f"template material {path} not found")
        return None
    obj.ObjectFlags |= ObjectFlags.KEEP_ALIVE
    _templates[path] = obj
    return obj


def _fix_one(mic) -> bool:
    """Point one of Krieg's instances at a Pre-Sequel shader. Safe to call every frame.

    The packages ship with the BL2-only static permutations already switched off, so the game
    never tries to draw them; all that is left is giving each top-level instance a parent whose
    shaders the Pre-Sequel has. Changing the parent goes through the engine's own render-safe path.
    """
    parent = mic.Parent
    ppath = parent._path_name() if parent is not None else ""
    static = mic.bHasStaticPermutationResource
    if parent is None and not static:
        ppath = MASTER_PLAYER  # a few DLC instances ship with no parent at all: same treatment
    if ppath != MASTER_PLAYER and not static:
        return False  # already re-parented, or a child of another Krieg instance
    if ppath == MASTER_PLAYER:
        path = mic._path_name()
        want = TEMPLATE_HANDS if "Arms" in path or "Hands" in path else TEMPLATE_BODY
        new_parent = _get_template(want)
        if new_parent is None:
            return False
    if static:
        # Old (unpatched) package: fall back to switching the permutation off at runtime.
        mic.bHasStaticPermutationResource = False
    if ppath == MASTER_PLAYER:
        try:
            mic.SetParent(new_parent)
        except Exception:  # noqa: BLE001
            mic.Parent = new_parent
    return True


def fix_krieg_materials() -> int:
    """Re-parent every loaded Krieg material instance that still uses its BL2-only shaders."""
    count = 0
    for path in ALL_MATERIAL_INSTANCES:
        mic = _find_mic(path)
        if mic is not None and _fix_one(mic):
            count += 1
    if count:
        log(f"re-parented {count} of Krieg's materials onto Pre-Sequel shaders")
    return count


# Buzz Axe and dynamite: instances of the shared gun / world master materials, again with BL2-only
# static permutations. Borrow a compiled permutation from any loaded Pre-Sequel instance of the
# same master, preferring the one whose texture parameter names match best.
CLASSMOD_MASTER = "Common_Materials.Items.Master_ClassMod_02"
CLASSMOD_MATERIALS = tuple(
    f"Lilac_Item_ClassMods.Materials.Mati_ClassMod_Psycho_{n}"
    for n in ("Blister", "Crunch", "Legendary", "Meat", "Reaper", "Sickle", "Slab", "Toast", "Torch", "Wound")
) + (
    "Lobelia_Char_Psycho.Materials.Mati_ClassMod_Psycho_Meat",
    "Aster_Char_Psycho.Materials.Mati_ClassMod_Psycho_Meat",
)
GEAR_MATERIALS = (
    "Lilac_Weap_BuzzAxe.Materials.BuzzAxe_BaseMat",
    "Lilac_Weap_BuzzAxe.Materials.Mati_DynamiteStick",
) + CLASSMOD_MATERIALS
_gear_templates: dict[str, object] = {}
GEAR_MASTER_FALLBACK = {
    "Lilac_Weap_BuzzAxe.Materials.BuzzAxe_BaseMat": "Common_Materials.Weapons.Master_Gun",
    **{path: CLASSMOD_MASTER for path in CLASSMOD_MATERIALS},
}


def _param_names(mic) -> set[str]:
    names = set()
    for arr in ("TextureParameterValues", "VectorParameterValues", "ScalarParameterValues"):
        try:
            names.update(str(p.ParameterName) for p in getattr(mic, arr))
        except Exception:  # noqa: BLE001
            pass
    return names


_gear_retry_at: dict[str, float] = {}
FANCY_GEAR_WORDS = ("legendary", "unique", "pearl", "glitch", "etech", "e-tech", "laser", "cryo", "fire",
                    "incendiary", "shock", "corrosive", "slag", "explosive", "glow", "effervescent",
                    "seraph", "rainbow", "excalibastard", "boss", "custom", "gold")


def _find_gear_template(master_path: str, want: set[str]):
    import time

    if master_path in _gear_templates:
        return _gear_templates[master_path]
    if time.monotonic() < _gear_retry_at.get(master_path, 0.0):
        return None
    _gear_retry_at[master_path] = time.monotonic() + 30.0
    best, best_score = None, -1
    family = master_path.rsplit(".", 1)[0]  # e.g. Common_Materials.Weapons
    # The Pre-Sequel keeps its gun materials under Common_Co_GunMaterials instead.
    families = (family, "Common_Co_GunMaterials") if "Weapons" in family else (family,)
    seen_parents: dict[str, int] = {}
    for cand in unrealsdk.find_all("MaterialInstanceConstant", exact=True):
        try:
            par = cand.Parent
            if par is None or not cand.bHasStaticPermutationResource:
                continue
            ppath = par._path_name()
            seen_parents[ppath] = seen_parents.get(ppath, 0) + 1
            # Exact master first; otherwise any master from the same family (the Pre-Sequel's
            # guns may use a renamed copy of BL2's Master_Gun).
            bonus = 1000 if ppath == master_path else (0 if ppath.startswith(families) else None)
            if bonus is None:
                continue
            cpath = cand._path_name()
            if cpath.split(".", 1)[0].startswith("Lilac"):
                continue
            have = _param_names(cand)
            # A plain gun shader: every parameter the template sets that Krieg's material doesn't
            # keeps the template's own value, so a legendary or elemental gun would paint its glow,
            # sheen or animated effect onto the Buzz Axe (the Excalibastard made it blue).
            fancy = any(k in cpath.lower() for k in FANCY_GEAR_WORDS)
            score = bonus + 10 * len(want & have) - len(have - want) - (500 if fancy else 0)
        except Exception:  # noqa: BLE001
            continue
        if score > best_score:
            best, best_score = cand, score
    if best is None:
        weapons = sorted((n, c) for n, c in seen_parents.items() if "Weapon" in n or "Gun" in n)
        log(f"no template for {master_path} yet; weapon masters loaded: {weapons[:12]}")
    if best is not None:
        best.ObjectFlags |= ObjectFlags.KEEP_ALIVE
        _gear_templates[master_path] = best
        log(f"using {best._path_name()} as the shader template for {master_path} (score {best_score})")
    return best


_gear_seen: set = set()
_gear_templates_used: set[str] = set()


def fix_krieg_gear_materials() -> int:
    count = 0
    for path in GEAR_MATERIALS:
        mic = _find_mic(path)
        state = "missing" if mic is None else f"static={mic.bHasStaticPermutationResource} parent={mic.Parent}"
        if (path, state) not in _gear_seen:
            _gear_seen.add((path, state))
            log(f"gear material {path}: {state}")
        if mic is None:
            continue
        if mic.Parent is not None and mic.Parent._get_address() in {
                t._get_address() for t in _gear_templates.values()}:
            continue  # already on a Pre-Sequel template
        # BL2's Master_Gun does not exist in the Pre-Sequel, so the Buzz Axe's parent loads as None.
        master = mic.Parent._path_name() if mic.Parent is not None else GEAR_MASTER_FALLBACK.get(path)
        if master is None:
            continue
        tmpl = _find_gear_template(master, _param_names(mic))
        if tmpl is None:
            continue
        if mic.bHasStaticPermutationResource:
            mic.bHasStaticPermutationResource = False  # unpatched package only
        try:
            mic.SetParent(tmpl)
        except Exception:  # noqa: BLE001
            mic.Parent = tmpl
        _gear_templates_used.add(path)
        count += 1
    if count:
        log(f"re-parented {count} Buzz Axe/dynamite materials")
    return count


# Respawn: Krieg's Borderlands 2 "re-rez" particle effect has a full-screen desaturation layer whose
# material (Mat_Desat_ScreenDepthBiased) has no Pre-Sequel shaders, so it drew as a solid pale
# rectangle around him. Turn off just the emitters that use it; the rest of the effect stays.
BROKEN_FX_MATERIALS = ("FX_CharacterAbilities.Materials.Mat_Desat_ScreenDepthBiased",)
FX_SYSTEMS = ("FX_CharacterAbilities.Particles.Part_Re_Rez",)
_fx_done: set[int] = set()


# Thrown Buzz Axe: when it sticks in something it plays BuzzAxe_Dissolve for 2 seconds before it
# is removed. In Borderlands 2 that swapped in FX_Lilac_PsychoBandit.Mat_BuzzAxeFX (a burn-away
# shader driven by "DissolveValue") - a Borderlands 2 material with no Pre-Sequel shaders, so the
# axe turned plain white. The axe's own material now sits on a Pre-Sequel gun shader, which has the
# Pre-Sequel's weapon "digistruct" fade (p_DigiStruct, 0 = solid, 1.25 = gone - the same parameter
# GD_CoordinatedEffects.Weapons.Digistruct_Out_Weapon animates). So the effect keeps the axe's own
# material and animates that instead: the axe digistructs away over the same 2 seconds.
DISSOLVE_EFFECTS = ("GD_Lilac_CE.CordinatedFX.BuzzAxe_Dissolve",)
DISSOLVE_PARAM = "p_DigiStruct"
DISSOLVE_END = 1.25
_dissolve_done: set[int] = set()


def fix_axe_dissolve() -> int:
    count = 0
    for path in DISSOLVE_EFFECTS:
        try:
            ce = unrealsdk.find_object("Object", path)
        except ValueError:
            continue
        if ce._get_address() in _dissolve_done:
            continue
        _dissolve_done.add(ce._get_address())
        try:
            ce.OverrideMaterial = None
            params = ce.MaterialScalarParameters
            if len(params):
                param = params[0]
                param.ParamName = DISSOLVE_PARAM
                points = param.ParamValueOverTime.Points
                if len(points) >= 2:
                    points[0].OutVal = 0.0
                    points[len(points) - 1].OutVal = DISSOLVE_END
                check = ce.MaterialScalarParameters[0]
                vals = [round(float(pt.OutVal), 2) for pt in check.ParamValueOverTime.Points]
                log(f"axe dissolve now animates {check.ParamName} {vals} over {ce.EffectDuration:g}s")
                count += 1
        except Exception as ex:  # noqa: BLE001
            log(f"axe dissolve: {type(ex).__name__}: {ex}")
    if count:
        log("thrown Buzz Axe dissolve effect uses the Pre-Sequel digistruct fade (was turning white)")
    return count


# Buzz Axe effects drawn with Borderlands 2 particle materials the Pre-Sequel can't render (white
# blobs on the vanish, a black square on the dynamite fuse). Their pictures are still in Krieg's
# package, and the originals are all additive, unlit flip-book sprites - which is exactly what the
# Pre-Sequel's own Mat_FX_Unlit_Add_SubUV_MS master is (it takes the picture as SubUV_Texture; its
# instance Mati_Spark_Generic_2 is used as the parent here). So each broken material gets a new
# material instance showing its ORIGINAL picture, and the effect looks like it did in Borderlands 2.
FX_MIC_PARENT = "FX_Shared_Sparks.Materials.Mati_Spark_Generic_2"
FX_MIC_PARAM = "SubUV_Texture"
FX_REBUILD = {
    # broken BL2 material -> its original picture (frame grid matches the emitters: 4x2 / 2x2 / 2x2)
    "FX_ENV_Level_Specific.Materials.Mat_Lava_BubbleExplosion": "FX_ENV_Level_Specific.Textures.Lava_Explosion_Flip_4X4_Dif",
    "FX_ENV_Level_Specific.Materials.Mat_Lava_Globs": "FX_ENV_Level_Specific.Textures.Lava_Globs_Dif",
    "FX_Lilac_PsychoBandit.Materials.Mat_Sparks": "FX_Lilac_PsychoBandit.Textures.Sparks_2X2",
}
# Fallbacks if a picture or the parent isn't loaded, plus the one material whose picture isn't in
# Krieg's package at all (it lives in a Borderlands 2 package): the Pre-Sequel's single spark streak.
FX_MATERIAL_SWAPS = {
    "FX_ENV_Level_Specific.Materials.Mat_Lava_BubbleExplosion": "FX_ENV_Fire.Materials.Mat_SubUV_4X4_Explosion",
    "FX_ENV_Level_Specific.Materials.Mat_Lava_Globs": "FX_ENV_Fire.Materials.Mat_Fire_SubUV_2X2",
    "FX_Lilac_PsychoBandit.Materials.Mat_Sparks": "FX_CHAR_Assassin.Materials.Mat_Assassin_SubUV_2X2_BurstSpark",
    "FX_Shared_Materials.Materials.Math_Based_Spark_Mat": "FX_Shared_Sparks.Materials.Mati_Spark_Single",
}
SWAP_SYSTEMS = ("FX_Lilac_PsychoBandit.Particles.Part_BuzzAxeVanish",
                "FX_Lilac_PsychoBandit.Particles.Part_DynamiteFuse")
_swap_done: set[int] = set()
_swap_warned: set[int] = set()
_fx_mics: dict[int, object] = {}


def _fx_mic(texture_path: str):
    """A Pre-Sequel additive flip-book material showing one of Krieg's original effect pictures."""
    try:
        tex = unrealsdk.find_object("Texture2D", texture_path)
        parent = unrealsdk.find_object("MaterialInstanceConstant", FX_MIC_PARENT)
    except ValueError:
        return None
    key = tex._get_address()
    mic = _fx_mics.get(key)
    if mic is not None:
        return mic
    try:
        name = "KriegTPS_FX_" + texture_path.split(".")[-1]
        mic = unrealsdk.construct_object(unrealsdk.find_class("MaterialInstanceConstant"), unrealsdk.find_object("Package", "Transient"),
                                         name + f"_{len(_fx_mics)}")
        mic.ObjectFlags |= ObjectFlags.KEEP_ALIVE
        mic.SetParent(parent)
        mic.SetTextureParameterValue(FX_MIC_PARAM, tex)
    except Exception as ex:  # noqa: BLE001
        log(f"Buzz Axe effects: could not build a material for {texture_path}: {type(ex).__name__}: {ex}")
        return None
    _fx_mics[key] = mic
    return mic


def swap_axe_vanish_materials() -> int:
    rebuilt = swapped = 0
    missing = set()
    for path in SWAP_SYSTEMS:
        try:
            ps = unrealsdk.find_object("ParticleSystem", path)
        except ValueError:
            continue
        if ps._get_address() in _swap_done:
            continue
        for emitter in ps.Emitters:
            if emitter is None:
                continue
            for lod in emitter.LODLevels:
                req = lod.RequiredModule if lod is not None else None
                mat = req.Material if req is not None else None
                if mat is None:
                    continue
                name = mat._path_name()
                tex_path = FX_REBUILD.get(name)
                new = _fx_mic(tex_path) if tex_path else None
                if new is not None:
                    req.Material = new
                    rebuilt += 1
                    continue
                new_path = FX_MATERIAL_SWAPS.get(name)
                if new_path is None:
                    continue
                try:
                    req.Material = unrealsdk.find_object("Object", new_path)
                    swapped += 1
                except ValueError:
                    missing.add(new_path)
        if not missing:
            _swap_done.add(ps._get_address())
    if rebuilt or swapped:
        log(f"Buzz Axe effects: {rebuilt} layers show their original Borderlands 2 pictures on a "
            f"Pre-Sequel material, {swapped} use Pre-Sequel stand-ins")
    if missing and not _swap_warned:
        _swap_warned.add(1)
        log(f"Buzz Axe effects: replacement materials not loaded: {sorted(missing)}")
    return rebuilt + swapped


def disable_broken_fx() -> int:
    fix_axe_dissolve()
    swap_axe_vanish_materials()
    count = 0
    for path in FX_SYSTEMS:
        try:
            ps = unrealsdk.find_object("ParticleSystem", path)
        except ValueError:
            continue
        if ps._get_address() in _fx_done:
            continue
        _fx_done.add(ps._get_address())
        for emitter in ps.Emitters:
            if emitter is None:
                continue
            for lod in emitter.LODLevels:
                req = lod.RequiredModule if lod is not None else None
                mat = req.Material if req is not None else None
                if mat is not None and mat._path_name() in BROKEN_FX_MATERIALS and lod.bEnabled:
                    lod.bEnabled = False
                    count += 1
    if count:
        log(f"turned off {count} respawn effect layers that drew as a pale rectangle")
    return count
