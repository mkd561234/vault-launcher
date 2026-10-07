"""
KriegTPS - makes Borderlands 2's Krieg (DLC "Lilac") work as a 7th playable class in
Borderlands: The Pre-Sequel.

TPS's DLC installer rejects Krieg's folder, so this mod loads his packages directly from
DLC\\Lilac\\Compat\\Content and registers him with the DLC manager. It also fills in the Pre-Sequel-only fields that Krieg's BL2 class definition never had, by copying
them from Aurelia's (Crocus) class definition, which is built the same way:

  - OxygenPoolDefinition / OxygenDepletionRtpc   -> Oz kit oxygen
  - AirBoostSettings / MaxFallSpeed              -> double jump boost, low gravity, butt slam
  - OffHandAccuracyPoolDefinition               -> off-hand accuracy pool every TPS class has
  - Ammo_Combat_Laser_Pool in ResourcePools     -> laser ammo
  - CharacterSelectUI* stand-in offsets          -> a position on the character select screen

Console commands:
  krieg_diag    print what the game has loaded for Krieg and what is still missing
  krieg_apply   re-apply the fixes by hand
  krieg_load    load Krieg's packages and register him by hand
"""

import argparse

import unrealsdk
from mods_base import Game, ModType, ObjectFlags, build_mod, command, get_pc, hook
from unrealsdk.hooks import Block, Type

__version__ = "1.0.12"
__author__ = "KriegTPS"

KRIEG_CLASS = "GD_Lilac_PlayerClass.Character.CharClass_LilacPlayerClass"
KRIEG_PACKAGE_DEF = "GD_LilacPackageDef.PackageDef_Lilac"
KRIEG_CHARACTER_DEF = "GD_LilacPackageDef.CharacterDef_Lilac"
TEMPLATE_CLASS = "Crocus_Baroness.Character.CharClass_Baroness"  # Aurelia
LASER_POOL = "D_Resourcepools.AmmoPools.Ammo_Combat_Laser_Pool"

# Properties that exist only on TPS classes; copied from Aurelia when Krieg's is empty.
COPY_IF_EMPTY = (
    "OxygenPoolDefinition",
    "OxygenDepletionRtpc",
    "AirBoostSettings",
    "OffHandAccuracyPoolDefinition",
)
COPY_ALWAYS = ("MaxFallSpeed",)

# Krieg starts from Aurelia's character-select spot, shifted left so both of his (much wider)\n# arms stay in frame. +Y moved him right/off-screen, so -Y moves him left.
SELECT_SCREEN_NUDGE = (0.0, -35.0, 0.0)

_LOG_PATH = __import__("pathlib").Path(__file__).with_name("krieg_log.txt")
try:
    # Keep the previous session's log (krieg_log_prev.txt) so a crash's log survives a relaunch.
    if _LOG_PATH.exists():
        _LOG_PATH.replace(_LOG_PATH.with_name("krieg_log_prev.txt"))
except OSError:
    pass
try:
    _log_file = open(_LOG_PATH, "w", encoding="utf-8")  # noqa: SIM115 - kept open for the session
except OSError:
    _log_file = None


def log(msg: str) -> None:
    print(f"[KriegTPS] {msg}")
    if _log_file is not None:
        import time

        _log_file.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        _log_file.flush()


def find(cls: str, path: str):
    try:
        return unrealsdk.find_object(cls, path)
    except ValueError:
        return None


def apply_fixes(quiet: bool = False) -> bool:
    krieg = find("PlayerClassDefinition", KRIEG_CLASS)
    template = find("PlayerClassDefinition", TEMPLATE_CLASS)
    if krieg is None:
        if not quiet:
            log("Krieg's class is not loaded - the DLC folder was not picked up. Run krieg_diag.")
        return False
    if template is None:
        if not quiet:
            log("Aurelia's class is not loaded, so there is nothing to copy TPS settings from.")
        return False

    for prop in COPY_IF_EMPTY:
        try:
            if getattr(krieg, prop) is None and getattr(template, prop) is not None:
                setattr(krieg, prop, getattr(template, prop))
                log(f"set {prop} = {getattr(krieg, prop)}")
        except AttributeError:
            log(f"property {prop} does not exist on this game version, skipped")

    for prop in COPY_ALWAYS:
        try:
            setattr(krieg, prop, getattr(template, prop))
        except AttributeError:
            pass

    # The HUD names its health bar clip after CharacterNameId.GFxHealthBarPath, a Pre-Sequel-only
    # field that is empty for Krieg (no health bar until something refreshed it).
    try:
        mine, theirs = krieg.CharacterNameId, template.CharacterNameId
        if mine is not None and theirs is not None and not mine.GFxHealthBarPath:
            mine.GFxHealthBarPath = theirs.GFxHealthBarPath
            log(f"set health bar path = {mine.GFxHealthBarPath!r}")
    except AttributeError:
        pass

    laser = find("ResourcePoolDefinition", LASER_POOL)
    if laser is not None and all(p != laser for p in krieg.ResourcePools):
        krieg.ResourcePools.append(laser)
        log("added laser ammo pool")

    for prefix in ("CharacterSelectUIPrimaryStandIn", "CharacterSelectUISplitStandIn"):
        try:
            src_off = getattr(template, prefix + "Offset")
            dst_off = getattr(krieg, prefix + "Offset")
            if dst_off.X == dst_off.Y == dst_off.Z == 0:
                dst_off.X = src_off.X + SELECT_SCREEN_NUDGE[0]
                dst_off.Y = src_off.Y + SELECT_SCREEN_NUDGE[1]
                dst_off.Z = src_off.Z + SELECT_SCREEN_NUDGE[2]
                rot_src = getattr(template, prefix + "Rotation")
                rot_dst = getattr(krieg, prefix + "Rotation")
                rot_dst.Pitch, rot_dst.Yaw, rot_dst.Roll = rot_src.Pitch, rot_src.Yaw, rot_src.Roll
        except AttributeError:
            pass
    return True


# Krieg's Borderlands 2 pawn has no Pre-Sequel settings: Aurelia's pawn sets oxygen regeneration
# (OxygenOnIdleRegenerationRate, so O2 refills in breathable areas) and butt-slam force. Without
# them his Oz kit only refilled on level-up. Copied onto his pawn template and his live pawn.
KRIEG_PAWN = "GD_Lilac_Psycho_Streaming.Pawn_LilacPlayerClass"
TEMPLATE_PAWN = "Crocus_Baroness_Streaming.Pawn_Baroness"
PAWN_COPY_IF_ZERO = ("SlamForceBaseValue",)
SLAM_FORCE = 2000.0  # Aurelia's pawn: SlamForceBaseValue
_pawn_arch_done = [False]
_pawn_seen: dict = {}


def fix_krieg_pawn() -> None:
    krieg = find("WillowPlayerPawn", KRIEG_PAWN)
    # Aurelia's pawn is only loaded in the menu (it is unloaded with the level), so everything
    # below that needs it is optional; the in-game part works without it.
    tmpl = find("WillowPlayerPawn", TEMPLATE_PAWN)
    if krieg is not None and tmpl is not None and not _pawn_arch_done[0]:
        have = {str(e.Attribute) for e in krieg.AttributeStartingValues}
        added = []
        for e in tmpl.AttributeStartingValues:
            if e.Attribute is not None and str(e.Attribute) not in have:
                krieg.AttributeStartingValues.append(e)
                added.append(e.Attribute.Name)
        for prop in PAWN_COPY_IF_ZERO:
            try:
                if not getattr(krieg, prop):
                    setattr(krieg, prop, getattr(tmpl, prop))
                    added.append(prop)
            except AttributeError:
                pass
        _pawn_arch_done[0] = True
        if added:
            log(f"pawn: copied {added} from Aurelia")
    # The pawn already in the world was spawned before the fix: patch it directly.
    pc = get_pc()
    pawn = pc.Pawn if pc is not None else None
    if pawn is None:
        return
    # While driving, the controller's pawn is the vehicle (or a gunner seat), not Krieg.
    try:
        pawn.SlamForceBaseValue
    except AttributeError:
        return
    cls = None
    for holder in (pc, getattr(pc, "PlayerReplicationInfo", None)):
        for attr in ("PlayerClass", "CharacterClass"):
            try:
                val = getattr(holder, attr) if holder is not None else None
            except AttributeError:
                val = None
            if val is not None:
                cls = val
                break
        if cls is not None:
            break
    cls_path = cls._path_name() if cls is not None else ""
    if "Lilac" not in cls_path:
        if _pawn_seen.get("skip") != pawn._get_address():
            _pawn_seen["skip"] = pawn._get_address()
            log(f"pawn: not Krieg ({cls_path or 'class unknown'}), oxygen left alone")
        return
    try:
        pool = pawn.OxygenPool.Data
    except AttributeError:
        pool = None
    if pool is not None and _pawn_seen.get("pawn") != pawn._get_address():
        _pawn_seen["pawn"] = pawn._get_address()
        info = {}
        for prop in ("OnIdleRegenerationRate", "OnIdleRegenerationRateBaseValue", "OnIdleRegenerationDelay",
                     "ActiveRegenerationRate", "ActiveRegenerationRateBaseValue", "CurrentValue"):
            try:
                info[prop] = getattr(pool, prop)
            except AttributeError:
                pass
        for prop in ("bCanBreathe", "bIsInVacuum"):
            try:
                info[prop] = getattr(pawn, prop)
            except AttributeError:
                pass
        try:
            info["archetype"] = pawn.ObjectArchetype._path_name()
        except Exception:  # noqa: BLE001
            pass
        log(f"pawn oxygen: {info}")
    if pool is not None and not pool.OnIdleRegenerationRateBaseValue:
        rate = OXYGEN_REFILL_PER_SECOND
        pool.OnIdleRegenerationRateBaseValue = rate
        if not pool.OnIdleRegenerationRate:
            pool.OnIdleRegenerationRate = rate
        log(f"pawn: oxygen now refills at {rate}/s in breathable areas")
    if pool is not None:
        _oxygen_fallback(pawn, pool)
    # Butt slam: the game stops your fall and then pushes you down with SlamForce. Krieg's was 0,
    # so he just hung in the air. Aurelia's value (2000) is used; her pawn isn't loaded in-game.
    try:
        if not pawn.SlamForceBaseValue:
            pawn.SlamForceBaseValue = SLAM_FORCE
        if not pawn.SlamForce:
            pawn.SlamForce = SLAM_FORCE
        if _pawn_seen.get("slam") != pawn._get_address():
            _pawn_seen["slam"] = pawn._get_address()
            log(f"pawn slam: force {pawn.SlamForce} (base {pawn.SlamForceBaseValue}), "
                f"enabled {pawn.SlamEnabled} (base {pawn.SlamEnabledBaseValue})")
    except AttributeError as ex:
        if _pawn_seen.get("slamerr") is None:
            _pawn_seen["slamerr"] = True
            log(f"pawn slam: {ex}")


# Safety net: if the game still isn't refilling Krieg's oxygen while he can breathe, refill it
# here at Aurelia's rate (runs once a second from upkeep).
OXYGEN_REFILL_PER_SECOND = 50.0
_oxy = {"last": None, "last_drop": 0.0, "logged": None}


def _oxygen_fallback(pawn, pool) -> None:
    import time
    now = time.monotonic()
    try:
        in_vacuum = bool(pawn.bIsInVacuum)
        cur, mx = float(pool.CurrentValue), float(pool.GetMaxValue())
        game_rate = float(pool.GetTotalRegenRate())
    except Exception as ex:  # noqa: BLE001
        if _oxy["logged"] != "err":
            _oxy["logged"] = "err"
            log(f"oxygen check failed: {type(ex).__name__}: {ex}")
        return
    last = _oxy["last"]
    if last is not None and cur < last[0] - 0.01:
        _oxy["last_drop"] = now  # being used: wait like the game's idle delay does
    _oxy["last"] = (cur, now)
    key = (round(game_rate, 2), in_vacuum)
    if _oxy["logged"] != key:
        _oxy["logged"] = key
        log(f"oxygen: {cur:.0f}/{mx:.0f}, game refill rate {game_rate}, in vacuum {in_vacuum}")
    if in_vacuum or cur >= mx or now - _oxy["last_drop"] < 2.0:
        return
    if last is not None and cur > last[0] + 0.5:
        return  # the game is refilling it itself
    if last is None:
        return
    new = min(mx, cur + OXYGEN_REFILL_PER_SECOND * (now - last[1]))
    try:
        pool.SetCurrentValue(new)
    except Exception:  # noqa: BLE001
        pool.CurrentValue = new
    _oxy["last"] = (new, now)


_slam_logged = {"n": 0}


@hook("WillowGame.WillowPlayerPawn:DoSlam", Type.POST, hook_identifier="KriegTPSSlamDiag")
def on_do_slam(obj, *_):
    if _slam_logged["n"] >= 3:
        return
    _slam_logged["n"] += 1
    try:
        v = obj.Velocity
        log(f"slam: velocity after DoSlam = ({v.X:.0f}, {v.Y:.0f}, {v.Z:.0f}), force {obj.SlamForce}, "
            f"physics {obj.Physics}")
    except Exception as ex:  # noqa: BLE001
        log(f"slam diag failed: {ex}")


# An earlier version turned depth of field off; the player asked for it back as normal.
# Turn it back on once so the game's own blur/fade effects behave as before.
_dof_done = [False]


def restore_depth_of_field() -> None:
    if _dof_done[0]:
        return
    pc = get_pc()
    if pc is None:
        return
    _dof_done[0] = True
    try:
        pc.ConsoleCommand("scale set DepthOfField True", False)
        log("depth of field back on (game default)")
    except Exception as ex:  # noqa: BLE001
        log(f"could not restore depth of field: {ex}")


@command("krieg_apply", description="Re-apply the KriegTPS class fixes.")
def krieg_apply(args: argparse.Namespace) -> None:
    log("fixes applied" if apply_fixes() else "fixes NOT applied")


@command("krieg_diag", description="Report what TPS has loaded for Krieg.")
def krieg_diag(args: argparse.Namespace) -> None:
    pkg = find("DownloadablePackageDefinition", KRIEG_PACKAGE_DEF)
    log(f"PackageDef_Lilac: {'loaded, PackageId=' + str(pkg.PackageId) if pkg else 'NOT LOADED'}")
    log(f"CharacterDef_Lilac: {'loaded' if find('DownloadableCharacterDefinition', KRIEG_CHARACTER_DEF) else 'NOT LOADED'}")
    for pd in unrealsdk.find_all("DownloadablePackageDefinition"):
        if "Default__" not in pd._path_name():
            log(f"  DLC package {pd._path_name()}  id={pd.PackageId}  name={pd.PackageDisplayName}")
    for cd in unrealsdk.find_all("PlayerClassDefinition"):
        if "Default__" not in cd._path_name():
            log(f"  class {cd._path_name()}")
    krieg = find("PlayerClassDefinition", KRIEG_CLASS)
    if krieg is not None:
        for prop in COPY_IF_EMPTY + COPY_ALWAYS:
            try:
                log(f"  Krieg.{prop} = {getattr(krieg, prop)}")
            except AttributeError:
                log(f"  Krieg.{prop} (no such property)")
        log(f"  Krieg.ResourcePools = {[p._path_name() for p in krieg.ResourcePools if p]}")
    dump_dlc_manager()


def _safe(fn):
    try:
        return fn()
    except Exception as ex:  # noqa: BLE001 - diagnostics only
        return f"<{type(ex).__name__}: {ex}>"


def dump_dlc_manager() -> None:
    """Show what the game's DLC system found on disk, installed, and rejected."""
    for cls_name, props in (
        ("WillowDownloadableContentManager",
         ("InstalledContent", "InstalledContentInfo", "RejectedContent", "RejectedContentInfo",
          "ContentPackages", "Characters")),
        ("DownloadableContentEnumerator", ("DLCRootDir", "DLCBundles", "CurrentEnumerationState")),
    ):
        for obj in unrealsdk.find_all(cls_name, exact=False):
            if "Default__" in obj._path_name():
                continue
            log(f"--- {obj.Class.Name} {obj._path_name()}")
            for prop in props:
                val = _safe(lambda: getattr(obj, prop))
                if hasattr(val, "__iter__") and not isinstance(val, str):
                    items = _safe(lambda: [str(v) for v in val])
                    log(f"  {prop} ({len(items) if isinstance(items, list) else '?'}):")
                    for item in items if isinstance(items, list) else [items]:
                        log(f"    {item[:300]}")
                else:
                    log(f"  {prop} = {str(val)[:300]}")



# ---------------------------------------------------------------------------
# Direct loading (option 2): load Krieg's packages ourselves instead of through
# the DLC folder install, then register his character with the DLC manager.
# ---------------------------------------------------------------------------
LILAC_DIR = "..\\..\\DLC\\Lilac\\Compat\\Content\\"
STARTUP_PACKAGES = ("Lilac_Startup_SF",)
CHARACTER_PACKAGES = (
    "GD_Lilac_Psycho_Streaming_SF",
    "CD_Psycho_Head_Default_SF",
    "CD_Psycho_Skin_Default_SF",
)
KEEP_ALIVE_PATHS = (
    ("DownloadablePackageDefinition", KRIEG_PACKAGE_DEF),
    ("DownloadableCharacterDefinition", KRIEG_CHARACTER_DEF),
    ("PlayerClassDefinition", KRIEG_CLASS),
    ("PlayerClassIdentifierDefinition", "GD_LilacPackageDef.PlayerClassId.Psycho"),
)


def _load(name: str) -> bool:
    for target in (name, LILAC_DIR + name + ".upk"):
        try:
            unrealsdk.load_package(target)
            log(f"loaded {name} (as '{target}')")
            return True
        except Exception as ex:  # noqa: BLE001
            last = ex
    log(f"could not load {name}: {last}")
    return False


def load_krieg(include_character: bool = True) -> None:
    names = STARTUP_PACKAGES + (CHARACTER_PACKAGES if include_character else ())
    for name in names:
        _load(name)
    for cls, path in KEEP_ALIVE_PATHS:
        obj = find(cls, path)
        if obj is not None:
            obj.ObjectFlags |= ObjectFlags.KEEP_ALIVE
    register_krieg()
    apply_fixes()


def register_krieg() -> None:
    pkg = find("DownloadablePackageDefinition", KRIEG_PACKAGE_DEF)
    char = find("DownloadableCharacterDefinition", KRIEG_CHARACTER_DEF)
    if pkg is None or char is None:
        log("Krieg's DLC definitions are not loaded, so he can't be registered")
        return
    for mgr in unrealsdk.find_all("WillowDownloadableContentManager"):
        if "Default__" in mgr._path_name():
            continue
        if all(p != pkg for p in mgr.ContentPackages):
            mgr.ContentPackages.append(pkg)
            log("added Krieg's package to the DLC manager")
        if all(c != char for c in mgr.Characters):
            mgr.Characters.append(char)
            log("added Krieg to the DLC character list")


@command("krieg_load", description="Load Krieg's packages directly and register him.")
def krieg_load(args: argparse.Namespace) -> None:
    load_krieg()



# ---------------------------------------------------------------------------
# DLC file-hash check bypass (in memory only; requested by the user)
# ---------------------------------------------------------------------------
# TPS SHA-1 hashes every file in a DLC folder and compares it with hashes baked
# into the exe. Krieg's files are not in that table, so his folder is rejected as
# INSTALLDLC_RES_CorruptContent. This makes that check (RVA 0x13C710 in
# BorderlandsPreSequel.exe build 2863302) report "valid" for this session only.
HASH_CHECK_RVA = 0x13C710
HASH_CHECK_PROLOGUE = b"\x55\x8b\xec\x6a\xff\x68"
RETURN_TRUE_STDCALL_8 = b"\xb8\x01\x00\x00\x00\xc2\x08\x00"  # mov eax,1 ; ret 8


def patch_dlc_hash_check() -> None:
    import ctypes

    k32 = ctypes.windll.kernel32
    k32.GetModuleHandleW.restype = ctypes.c_void_p
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    addr = k32.GetModuleHandleW(None) + HASH_CHECK_RVA
    current = ctypes.string_at(addr, 8)
    if current == RETURN_TRUE_STDCALL_8:
        return
    if current[:6] != HASH_CHECK_PROLOGUE:
        log(f"DLC hash check NOT patched - unexpected bytes {current.hex()} (different game build?)")
        return
    old = ctypes.c_ulong()
    k32.VirtualProtect(ctypes.c_void_p(addr), 8, 0x40, ctypes.byref(old))
    ctypes.memmove(addr, RETURN_TRUE_STDCALL_8, 8)
    k32.VirtualProtect(ctypes.c_void_p(addr), 8, old.value, ctypes.byref(old))
    k32.FlushInstructionCache(ctypes.c_void_p(k32.GetCurrentProcess()), ctypes.c_void_p(addr), 8)
    log("DLC hash check bypassed for this session")


try:
    patch_dlc_hash_check()
except Exception as ex:  # noqa: BLE001
    log(f"DLC hash check patch failed: {ex}")

# Must run before the game installs the DLC folder (it scans the folder's files about 10 s later).
try:
    from . import tfc_builder

    tfc_builder.build(log)
except Exception as ex:  # noqa: BLE001
    log(f"texture cache build failed: {type(ex).__name__}: {ex}")


@hook("Engine.GameInfo:InitGame", Type.PRE)
def on_init_game(*_) -> None:
    apply_fixes()
    try:
        materials.fix_krieg_materials()
    except Exception as ex:  # noqa: BLE001
        log(f"material fix failed: {ex}")


def on_enable() -> None:
    apply_fixes()
    try:
        materials.fix_krieg_materials()
    except Exception as ex:  # noqa: BLE001
        log(f"material fix failed: {ex}")


# Skins and heads: move Krieg's materials onto shaders that exist in the Pre-Sequel.
from . import buzzaxe, classmods, hud_fix, loadout, materials, ozevents, slam, vehicles  # noqa: E402
for _i, _h in enumerate(ozevents.boost_hooks):
    globals()[f"_boost_hook_{_i}"] = _h
for _i, _h in enumerate(slam.slam_hooks):
    globals()[f"_slam_hook_{_i}"] = _h
for _i, _h in enumerate(loadout.loadout_hooks):
    globals()[f"_loadout_hook_{_i}"] = _h
for _i, _h in enumerate(vehicles.diag_hooks):
    globals()[f"_vehicle_hook_{_i}"] = _h
for _i, _h in enumerate(vehicles.seat_hooks):
    globals()[f"_seat_hook_{_i}"] = _h
for _i, _h in enumerate(buzzaxe.axe_hooks):
    globals()[f"_axe_hook_{_i}"] = _h

@command("krieg_fixmats", description="Re-apply Krieg's skin/head material fix by hand.")
def krieg_fixmats(args: argparse.Namespace) -> None:
    log(f"fixed {materials.fix_krieg_materials()} materials")


# ---------------------------------------------------------------------------
# Heads and skins: all of Krieg's customizations unlocked from the start
# ---------------------------------------------------------------------------
# Unlocks are stored per player profile. Ask the game's own customization manager to unlock
# each of Krieg's heads and skins for the local player (the same call a head/skin drop makes),
# once per session. Already-unlocked ones are skipped.
from .krieg_objects import CUSTOMIZATIONS, SCREEN_PARTICLE_BEHAVIORS  # noqa: E402
from .krieg_objects import EXTRA_CUSTOMIZATIONS as _ALL_EXTRA_CUSTOMIZATIONS  # noqa: E402

# Heads/skins from Borderlands 2's other DLCs are only offered when the installer could build their
# package (the player owns and has installed that Borderlands 2 DLC).
_LILAC_CONTENT = __import__("pathlib").Path(__file__).resolve().parents[2] / "DLC" / "Lilac" / "Compat" / "Content"
EXTRA_CUSTOMIZATIONS = tuple(e for e in _ALL_EXTRA_CUSTOMIZATIONS
                             if (_LILAC_CONTENT / f"{e[3]}_SF.upk").is_file())

# Heads and skins from Borderlands 2's other DLCs. Their definitions lived in those DLCs' own
# packages, so they are created here, next to Krieg's other definitions, from one of his
# existing ones as a template. The head/skin packages themselves are in Krieg's DLC folder.
DEF_OUTER = "GD_AllCustoms_Lilac.Psycho"
DEF_TEMPLATES = {"Head": "GD_AllCustoms_Lilac.Psycho.Head_Psycho001",
                 "Skin": "GD_AllCustoms_Lilac.Psycho.Skin_BanditA"}
EXTRA_PATHS = tuple(f"{DEF_OUTER}.{e[0]}" for e in EXTRA_CUSTOMIZATIONS)
ALL_CUSTOMIZATIONS = CUSTOMIZATIONS + EXTRA_PATHS
_extra_defs_done = False


def create_extra_customizations() -> int:
    global _extra_defs_done
    if _extra_defs_done:
        return 0
    templates = {k: find("CustomizationDefinition", v) for k, v in DEF_TEMPLATES.items()}
    if None in templates.values():
        return 0  # Krieg's DLC definitions are not loaded yet
    outer = templates["Head"].Outer
    made = 0
    for name, kind, display, package, data, primary, secondary in EXTRA_CUSTOMIZATIONS:
        path = f"{DEF_OUTER}.{name}"
        cd = find("CustomizationDefinition", path)
        if cd is None:
            try:
                cd = unrealsdk.construct_object("CustomizationDefinition", outer, name,
                                                template_obj=templates[kind])
            except Exception as ex:  # noqa: BLE001
                log(f"could not create {name}: {type(ex).__name__}: {ex}")
                continue
            made += 1
        cd.ObjectFlags |= ObjectFlags.KEEP_ALIVE
        for attr, val in (("CustomizationName", display), ("PackageName", package),
                          ("CustomizationDataName", data), ("PrimarySort", primary),
                          ("SecondarySort", secondary)):
            try:
                setattr(cd, attr, val)
            except Exception as ex:  # noqa: BLE001
                log(f"{name}.{attr}: {type(ex).__name__}: {ex}")
    _extra_defs_done = True
    log(f"added {made} heads/skins from Borderlands 2's other DLCs "
        f"({sum(e[1] == 'Head' for e in EXTRA_CUSTOMIZATIONS)} heads, "
        f"{sum(e[1] == 'Skin' for e in EXTRA_CUSTOMIZATIONS)} skins)")
    return made


_unlocked: set[str] = set()


def _customization_manager():
    for mgr in unrealsdk.find_all("WillowCustomizationManager", exact=False):
        if "Default__" not in mgr._path_name():
            return mgr
    return None


def unlock_customizations() -> int:
    if len(_unlocked) >= len(CUSTOMIZATIONS):
        return 0
    pc = get_pc()
    mgr = _customization_manager()
    if pc is None or mgr is None:
        return 0
    count = 0
    for path in CUSTOMIZATIONS:
        if path in _unlocked:
            continue
        cd = find("CustomizationDefinition", path)
        if cd is None:
            continue
        try:
            res = mgr.IsCustomizationUnlocked(Definition=cd, Controller=pc)
            already = res[0] if isinstance(res, tuple) else bool(res)
        except Exception:  # noqa: BLE001
            already = False
        if not already:
            try:
                mgr.SetCustomizationLocked(Definition=cd, Controller=pc, bLocked=False)
                count += 1
            except Exception as ex:  # noqa: BLE001
                log(f"could not unlock {path}: {type(ex).__name__}: {ex}")
        _unlocked.add(path)
    if count:
        log(f"unlocked {count} of Krieg's heads and skins ({len(_unlocked)}/{len(CUSTOMIZATIONS)} checked)")
    return count


# The unlock alone is not enough: the head/skin menus also hide anything they consider "not
# authorized" (DLC ownership checks that Krieg's BL2 content can't pass in the Pre-Sequel).
# After each menu builds its lists, add every one of Krieg's heads/skins that is missing.
def _krieg_customization_defs(kind: str) -> list:
    create_extra_customizations()
    out = []
    for path in ALL_CUSTOMIZATIONS:
        cd = find("CustomizationDefinition", path)
        if cd is None or cd.CustomizationType is None:
            continue
        if cd.CustomizationType.Name.endswith(kind):
            out.append(cd)
    return out


def _is_krieg_def(cd) -> bool:
    return cd is not None and "_Lilac." in cd._path_name()


def _fill_list(arr, kind: str, also=None, remove_from=(), equipped=None) -> int:
    # The lists can be completely empty for Krieg (everything filtered as unauthorized), so
    # recognise his menu by what he has equipped as well as by the list contents.
    if not (_is_krieg_def(equipped) or any(_is_krieg_def(x) for x in arr)):
        return 0  # this list is for another character
    present = {x._path_name() for x in arr if x is not None}
    added = 0
    for cd in _krieg_customization_defs(kind):
        if cd._path_name() in present:
            continue
        arr.append(cd)
        if also is not None:
            also.append(cd)
        added += 1
    for other in remove_from:
        for i in range(len(other) - 1, -1, -1):
            if _is_krieg_def(other[i]):
                other.pop(i)
    return added


def _lists_are_krieg(heads, skins) -> bool:
    """Every Pre-Sequel character always has at least its default head and skin listed, so lists
    with none of another character's items are Krieg's (empty: all of his were filtered out)."""
    items = [x for x in list(heads) + list(skins) if x is not None]
    return not any(not _is_krieg_def(x) for x in items)


_cs_logs = {"n": 0, "fields": False}


def _char_select_fill(obj, why: str) -> int:
    """Make sure the character select lists hold all of Krieg's heads and skins while Krieg is the
    character on screen. Runs after the game rebuilds the lists and again right before it uses
    them (a click or a preview), because moving the mouse over the other characters rebuilds the
    lists for them and a click on Krieg could otherwise land on an empty list."""
    n = 0
    lists = ((obj.PrimaryPlayerHeadCustomizations, obj.PrimaryPlayerSkinCustomizations),
             (obj.SplitPlayerHeadCustomizations, obj.SplitPlayerSkinCustomizations))
    for idx, (heads, skins) in enumerate(lists):
        if idx == 1 and len(heads) == 0 and len(skins) == 0 and not _lists_are_krieg(*lists[0]):
            continue      # no split-screen player, and the main player isn't on Krieg
        if not _lists_are_krieg(heads, skins):
            continue
        marker = _krieg_customization_defs("Head")[0]
        n += _fill_list(heads, "Head", equipped=marker) + _fill_list(skins, "Skin", equipped=marker)
    if n and _cs_logs["n"] < 20:
        _cs_logs["n"] += 1
        log(f"character select ({why}): added {n} of Krieg's heads/skins to the lists")
    return n


@hook("WillowGame.CharacterSelectionReduxGFxMovie:CacheCustomizations", Type.POST)
def on_char_select_cache(obj, args, *_):
    try:
        if not _cs_logs["fields"]:
            _cs_logs["fields"] = True
            try:
                log(f"character select cache args: {args}")
            except Exception:  # noqa: BLE001
                pass
        _char_select_fill(obj, "lists rebuilt")
    except Exception as ex:  # noqa: BLE001
        log(f"character select list fill failed: {type(ex).__name__}: {ex}")


def _cs_refill_hook(func: str):
    def _cb(obj, *_):
        try:
            _char_select_fill(obj, func.split(":")[-1])
        except Exception as ex:  # noqa: BLE001
            if _cs_logs["n"] < 20:
                _cs_logs["n"] += 1
                log(f"character select refill ({func}) failed: {type(ex).__name__}: {ex}")
    return hook(func, Type.PRE, hook_identifier=f"KriegTPSRefill_{func}")(_cb)


_cs_refill_hooks = [
    _cs_refill_hook(f"WillowGame.CharacterSelectionReduxGFxMovie:{f}")
    for f in ("HandleCustomizationSelected", "PreviewSkinCustomization", "PreviewHeadCustomization",
              "UpdateSkinPreview", "UpdateHeadPreview")
]
for _i, _h in enumerate(_cs_refill_hooks):
    globals()[f"_cs_refill_hook_{_i}"] = _h


def _krieg_class_selected(movie) -> bool:
    """True if the local player's current/selected class is Krieg."""
    try:
        pc = get_pc()
        pri = pc.PlayerReplicationInfo if pc is not None else None
        for attr in ("CharacterClass", "PlayerClassDefinition"):
            val = getattr(pri, attr, None) if pri is not None else None
            if val is not None and "Lilac" in val._path_name():
                return True
    except Exception:  # noqa: BLE001
        pass
    try:
        return "Psycho" in str(movie.EquippedHeadCustomization) or "Lilac" in str(movie.EquippedHeadCustomization)
    except Exception:  # noqa: BLE001
        return False


def _quick_change_fill(obj, kind: str) -> None:
    try:
        avail = getattr(obj, f"{kind}Customizations")
        seen = getattr(obj, f"Seen{kind}Customizations")
        unauth = getattr(obj, f"Unauthorized{kind}Customizations")
        equipped = getattr(obj, f"Equipped{kind}Customization", None)
        if isinstance(equipped, tuple):
            equipped = equipped[0]
        if equipped is None and (_krieg_class_selected(obj) or len(avail) == 0):
            equipped = _krieg_customization_defs(kind)[0]
        n = _fill_list(avail, kind, also=seen, remove_from=(unauth,), equipped=equipped)
        if n:
            log(f"quick-change: added {n} of Krieg's {kind.lower()}s")
        if any(_is_krieg_def(x) for x in avail):
            _qc_reenable(kind)
            _qc_unlocked_count(obj, kind, avail)
    except Exception as ex:  # noqa: BLE001
        log(f"quick-change {kind} list fill failed: {type(ex).__name__}: {ex}")


@hook("WillowGame.CustomizationGFxMovie:CacheHeadCustomizations", Type.POST)
def on_qc_heads(obj, *_):
    _quick_change_fill(obj, "Head")


@hook("WillowGame.CustomizationGFxMovie:CacheSkinCustomizations", Type.POST)
def on_qc_skins(obj, *_):
    _quick_change_fill(obj, "Skin")


_qc_logs = {"n": 0}


def _qc_state(obj, kind: str) -> str:
    try:
        avail = getattr(obj, f"{kind}Customizations")
        mine = sum(1 for x in avail if _is_krieg_def(x))
        eq = getattr(obj, f"Equipped{kind}Customization", None)
        if isinstance(eq, tuple):
            eq = eq[0]
        return (f"{kind}: {len(avail)} listed ({mine} Krieg's), "
                f"{len(getattr(obj, f'Unauthorized{kind}Customizations'))} unauthorized, "
                f"{len(getattr(obj, f'Seen{kind}Customizations'))} seen, equipped {eq.Name if eq is not None else None}, "
                f"preview type {obj.PreviewType!r}")
    except Exception as ex:  # noqa: BLE001
        return f"{kind}: ? ({type(ex).__name__}: {ex})"


def _qc_card(kind: str, when: str):
    def cb(obj, *_):
        if when == "before":
            _quick_change_fill(obj, kind)   # the lists can be rebuilt before the card opens
        if _qc_logs["n"] < 24:
            _qc_logs["n"] += 1
            log(f"quick-change {kind.lower()} card {when}: {_qc_state(obj, kind)}")
    return cb


_qc_hooks = [
    hook("WillowGame.CustomizationGFxMovie:extInitHeadInfoCard", Type.PRE, hook_identifier="KriegTPSQCHeadPre")(_qc_card("Head", "before")),
    hook("WillowGame.CustomizationGFxMovie:extInitHeadInfoCard", Type.POST, hook_identifier="KriegTPSQCHeadPost")(_qc_card("Head", "after")),
    hook("WillowGame.CustomizationGFxMovie:extInitSkinInfoCard", Type.PRE, hook_identifier="KriegTPSQCSkinPre")(_qc_card("Skin", "before")),
    hook("WillowGame.CustomizationGFxMovie:extInitSkinInfoCard", Type.POST, hook_identifier="KriegTPSQCSkinPost")(_qc_card("Skin", "after")),
]
for _i, _h in enumerate(_qc_hooks):
    globals()[f"_qc_hook_{_i}"] = _h


# The quick-change menu greys out its Head / Skin entries when the game's own list for the player
# was empty - which it is for Krieg (his Borderlands 2 heads and skins fail the Pre-Sequel's DLC
# checks), and the lists are only filled in by the mod right after that. A greyed-out entry can't
# be clicked, so the head/skin lists never open. Keep those two entries enabled for Krieg.
_qc_entry_logs = {"n": 0}
_qc_entries: dict = {}


def _qc_unlocked_count(obj, kind: str, avail) -> None:
    """The "x/y unlocked" counter is worked out by the game before the mod adds Krieg's heads and
    skins, so it read 0/0. Set it from the filled list: all of them are unlocked."""
    try:
        n = sum(1 for x in avail if x is not None)
        text = f"{n}/{n}"
        attr = "UnlockedHeadsNumbersText" if kind == "Head" else "UnlockedSkinsNumbersText"
        if str(getattr(obj, attr)) != text:
            setattr(obj, attr, text)
            log(f"quick-change: {kind.lower()}s unlocked counter set to {text}")
        try:
            getattr(obj, f"SetUnlockedText_{kind}s")()
        except Exception:  # noqa: BLE001
            pass  # it is shown when the list card opens anyway
    except Exception as ex:  # noqa: BLE001
        log(f"quick-change: could not set the {kind.lower()} counter: {type(ex).__name__}: {ex}")


def _qc_reenable(kind: str) -> None:
    """Set the Head (0) / Skin (1) entry up again, enabled, now that Krieg's list is filled. (The
    game sets it up disabled while its own list is still empty.)"""
    idx = 0 if kind == "Head" else 1
    e = _qc_entries.get(idx)
    if not e:
        return
    try:
        e["menu"].InitMenuEntry(Index=idx, bVisible=True, bDisabled=False, Label=e["Label"],
                                Caption=e["Caption"], IconFrame=e["IconFrame"],
                                bIsInputEntry=e["bIsInputEntry"], MaxInputLength=e["MaxInputLength"])
        log(f"quick-change: {kind} entry enabled for Krieg")
    except Exception as ex:  # noqa: BLE001
        log(f"quick-change: could not enable the {kind} entry: {type(ex).__name__}: {ex}")


@hook("WillowGame.CharacterCustomizationMenuGFxObject:InitMenuEntry", Type.PRE, hook_identifier="KriegTPSQCEntry")
def on_qc_menu_entry(obj, args, *_):
    try:
        pc = get_pc()
        krieg = pc is not None and pc.PlayerClass is not None and "Lilac" in pc.PlayerClass._path_name()
        if _qc_entry_logs["n"] < 8:
            _qc_entry_logs["n"] += 1
            log(f"quick-change menu entry {args.Index}: label {args.Label!r}, caption {args.Caption!r}, "
                f"visible {args.bVisible}, disabled {args.bDisabled}{' (Krieg)' if krieg else ''}")
        if krieg and args.Index in (0, 1):
            _qc_entries[int(args.Index)] = dict(
                Label=str(args.Label), Caption=str(args.Caption), IconFrame=str(getattr(args, "IconFrame", "")),
                bIsInputEntry=bool(getattr(args, "bIsInputEntry", False)),
                MaxInputLength=int(getattr(args, "MaxInputLength", 0)), menu=obj)
            if args.bDisabled:
                args.bDisabled = False
    except Exception as ex:  # noqa: BLE001
        log(f"quick-change menu entry hook failed: {type(ex).__name__}: {ex}")


_diag_done = False
_health_calls = 0
_health_logs = 0


def nudge_hud_health() -> None:
    """The HUD keeps a drawn value (CurrentHealth) separate from the real one (CachedHealth). For
    Krieg the drawn value stays at 0, so the bar is zero-width. Copy the real value across."""
    global _health_logs
    pc = get_pc()
    if pc is None or pc.Pawn is None:
        return
    for movie in unrealsdk.find_all("WillowHUDGFxMovie", exact=False):
        if "Default__" in movie._path_name():
            continue
        if _health_logs < 6:
            _health_logs += 1
            log(f"HUD health: Current={movie.CurrentHealth} Cached={movie.CachedHealth}/{movie.CachedMaxHealth} "
                f"lerp={movie.HealthLerpCurrValue} ({movie.HealthLerpStartValue}->{movie.HealthLerpDesiredTime}) "
                f"last={movie.LastHealthUpdated}")
        if movie.CurrentHealth <= 0 < movie.CachedHealth:
            movie.CurrentHealth = movie.CachedHealth
            movie.HealthLerpCurrValue = movie.CachedHealth
        hud_fix.fix_health_bar(movie, pc, log)


@hook("WillowGame.WillowHUDGFxMovie:UpdateHealth", Type.POST)
def on_update_health(obj, *_):
    global _health_calls
    _health_calls += 1
    if _health_calls in (1, 50, 500):
        log(f"HUD UpdateHealth call #{_health_calls}: CurrentHealth={obj.CurrentHealth} "
            f"CachedHealth={obj.CachedHealth}/{obj.CachedMaxHealth} lerp={obj.HealthLerpCurrValue} "
            f"last={obj.LastHealthUpdated}")


@hook("WillowGame.BuzzaxeActionSkill:DisableActionSkillHUD", Type.PRE)
def on_disable_skill_hud(obj, *_):
    log("BuzzaxeActionSkill.DisableActionSkillHUD")


@hook("WillowGame.BuzzaxeActionSkill:EnableActionSkillHUD", Type.PRE)
def on_enable_skill_hud(obj, *_):
    log("BuzzaxeActionSkill.EnableActionSkillHUD")


def diagnose_once() -> None:
    """One-time log of what the game thinks about Krieg's customizations and health."""
    global _diag_done
    pc = get_pc()
    if _diag_done or pc is None or pc.Pawn is None:
        return
    pawn = pc.Pawn
    _diag_done = True
    for attr in ("Health", "HealthMax"):
        log(f"diag pawn.{attr} = {getattr(pawn, attr, '?')}")
    for attr in ("HealthPool", "ShieldArmor", "OxygenPool"):
        try:
            log(f"diag pawn.{attr} = {str(getattr(pawn, attr))[:300]}")
        except AttributeError:
            pass
    for movie in unrealsdk.find_all("WillowHUDGFxMovie", exact=False):
        if "Default__" in movie._path_name():
            continue
        log(f"diag HUD {movie._path_name()} CachedHealth={movie.CachedHealth} "
            f"CachedMaxHealth={movie.CachedMaxHealth} CurrentHealth={movie.CurrentHealth} "
            f"bar={movie.CachedGFxHealthBarPath!r}")


# ---------------------------------------------------------------------------
# Buzz Axe Rampage blacked out the screen
# ---------------------------------------------------------------------------
# Rampage (and Silence the Voices) put full-screen particle overlays on the camera. Their
# materials are compiled only in Borderlands 2, so the Pre-Sequel draws them as an opaque
# default material over the whole screen. Turn those overlays off; the skills still work.
_screen_off: set[str] = set()


def disable_screen_overlays() -> int:
    count = 0
    for path in SCREEN_PARTICLE_BEHAVIORS:
        if path in _screen_off:
            continue
        beh = find("Behavior_ScreenParticle", path)
        if beh is None:
            continue
        for attr in ("ParticleSystem", "MaterialInterface"):
            try:
                setattr(beh, attr, None)
            except AttributeError:
                pass
        try:
            params = beh.Parameters
            params.Template = None
            beh.Parameters = params
        except AttributeError:
            pass
        _screen_off.add(path)
        count += 1
    if count:
        log(f"turned off {count} full-screen effects that render black in the Pre-Sequel")
    return count


_SCREEN_PARTICLE_SET = frozenset(SCREEN_PARTICLE_BEHAVIORS)


@hook("WillowGame.Behavior_ScreenParticle:ApplyBehaviorToContext", Type.PRE)
def block_krieg_screen_overlays(obj, *_):
    """Belt and braces: never let Krieg's screen overlays run at all."""
    if obj._path_name() in _SCREEN_PARTICLE_SET:
        return Block
    return None


# Screen effects are shown through the player controller. Log every one that is requested while
# playing Krieg, and refuse the ones that come from his BL2 files (their materials render black).
KRIEG_FX_PREFIXES = ("FX_Lilac", "FX_CharacterAbilities", "Lilac", "GD_Lilac")


def _describe(args) -> str:
    try:
        return str(args)[:400]
    except Exception:  # noqa: BLE001
        return "?"


# (Blocking the respawn/load screen particle did not remove the blur, which is depth of field.)
NO_BLUR_TEMPLATES: tuple = ()  # blocking the fast-travel screen made the screen go black instead


def _refs_krieg(args) -> bool:
    text = _describe(args)
    if any(t in text for t in NO_BLUR_TEMPLATES):
        return True
    return any(f"'{p}" in text or f".{p}" in text or f" {p}" in text for p in KRIEG_FX_PREFIXES)


def _screen_fx_hook(func: str):
    def _cb(obj, args, *_):
        krieg = _refs_krieg(args)
        log(f"{func.split(':')[1]}{' [BLOCKED]' if krieg else ''}: {_describe(args)}")
        return Block if krieg else None
    return hook(func, Type.PRE, hook_identifier=f"KriegTPSScreenFx_{func}")(_cb)


_screen_fx_hooks = [
    _screen_fx_hook(f)
    for f in (
        "WillowGame.WillowPlayerController:ShowScreenParticle",
        "WillowGame.WillowPlayerController:AddPostProcessOverlay",
        "WillowGame.WillowPlayerController:SetupPostProcessOverlay",
        "WillowGame.WillowPlayerController:PushPostProcessChain",
    )
]
for _i, _h in enumerate(_screen_fx_hooks):
    globals()[f"_screen_fx_hook_{_i}"] = _h


@hook("WillowGame.BuzzaxeActionSkill:OnActionSkillStarted", Type.POST)
def on_rampage_started(obj, *_):
    log("Buzz Axe Rampage started")
    _dump_view_state("rampage start")


@hook("WillowGame.BuzzaxeActionSkill:OnActionSkillEnded", Type.POST)
def on_rampage_ended(obj, *_):
    log("Buzz Axe Rampage ended")
    _dump_view_state("rampage end")


def _dump_view_state(when: str) -> None:
    pc = get_pc()
    if pc is None:
        return
    for attr in ("PostProcessOverlays", "PostProcessChainRecords", "ScreenParticleRecords", "ActiveScreenParticles"):
        try:
            log(f"  {when} {attr}: {str(getattr(pc, attr))[:600]}")
        except AttributeError:
            pass
    try:
        pawn = pc.Pawn
        weap = pawn.Weapon if pawn is not None else None
        log(f"  {when} weapon: {weap._path_name() if weap else None}")
        if weap is not None:
            for comp in ("Mesh", "Mesh1P", "Mesh3P"):
                m = getattr(weap, comp, None)
                if m is not None:
                    log(f"    {comp}: {m._path_name()} hidden={getattr(m, 'HiddenGame', '?')} "
                        f"bounds={getattr(m, 'Bounds', '?')}")
    except Exception as ex:  # noqa: BLE001
        log(f"  {when} weapon dump failed: {ex}")


# ---------------------------------------------------------------------------
# Periodic upkeep: Krieg's packages load at different times (menu, character select,
# level load, customization changes), so re-check about once a second on the game thread.
# ---------------------------------------------------------------------------
import time as _time  # noqa: E402

_next_upkeep = 0.0


# Character select: the Pre-Sequel keeps its own characters loaded, but Krieg's model, animations
# and textures were thrown away whenever another character was picked and read back from disk
# when he was picked again (3-4 seconds of empty screen). Once he has been loaded, his pawn
# template - and through it his mesh, animations and default head and skin - stays in memory.
_krieg_kept = [False]


def keep_krieg_loaded() -> None:
    if _krieg_kept[0]:
        return
    try:
        pawn = unrealsdk.find_object("WillowPlayerPawn", KRIEG_PAWN)
    except ValueError:
        return
    pawn.ObjectFlags |= ObjectFlags.KEEP_ALIVE
    for name in ("Mesh", "Mesh3p"):
        comp = getattr(pawn, name, None)
        try:
            if comp is not None and comp.SkeletalMesh is not None:
                comp.SkeletalMesh.ObjectFlags |= ObjectFlags.KEEP_ALIVE
        except Exception:  # noqa: BLE001
            pass
    _krieg_kept[0] = True
    log("Krieg's model stays loaded, so he appears straight away when picked again at character select")


def upkeep() -> None:
    global _next_upkeep
    now = _time.monotonic()
    if now < _next_upkeep:
        return
    _next_upkeep = now + 1.0
    # unlock_customizations is not run: the game's unlock check crashed on Krieg's BL2 profile
    # indices. The head/skin menus are filled directly instead (see on_char_select_cache).
    for step in (keep_krieg_loaded, lambda: apply_fixes(quiet=True), create_extra_customizations, classmods.upkeep, ozevents.upkeep, loadout.upkeep, vehicles.upkeep_all, slam.upkeep, buzzaxe.upkeep, fix_krieg_pawn, restore_depth_of_field,
                 disable_screen_overlays,
                 materials.fix_krieg_materials, materials.fix_krieg_gear_materials, materials.disable_broken_fx, diagnose_once,
                 nudge_hud_health):
        try:
            step()
        except Exception as ex:  # noqa: BLE001 - never break the game loop
            log(f"upkeep step failed: {type(ex).__name__}: {ex}")


# While heads/skins are being browsed, newly streamed-in materials are fixed on the very frame
# they appear (before the frame is drawn) instead of up to a second later. That is what caused
# the brief white flash while scrolling.
_hot_until = 0.0
HOT_SECONDS = 5.0


def mark_hot(*_) -> None:
    global _hot_until
    _hot_until = _time.monotonic() + HOT_SECONDS


def fast_material_pass() -> None:
    if _time.monotonic() >= _hot_until:
        return
    try:
        materials.fix_krieg_materials()
    except Exception as ex:  # noqa: BLE001
        log(f"fast material pass failed: {type(ex).__name__}: {ex}")


def _hot_hook(func: str):
    def _cb(*_) -> None:
        mark_hot()
    return hook(func, Type.PRE, hook_identifier=f"KriegTPSHot_{func}")(_cb)


_hot_hooks = [
    _hot_hook(f)
    for f in (
        "WillowGame.CharacterSelectionReduxGFxMovie:PreviewSkinCustomization",
        "WillowGame.CharacterSelectionReduxGFxMovie:PreviewHeadCustomization",
        "WillowGame.CharacterSelectionReduxGFxMovie:HandleCustomizationSelected",
        "WillowGame.CharacterSelectionReduxGFxMovie:UpdateSkinPreview",
        "WillowGame.CharacterSelectionReduxGFxMovie:UpdateHeadPreview",
        "WillowGame.CharacterSelectionReduxGFxMovie:SetSelectedCharacterIndex",
        "WillowGame.CharacterSelectionReduxGFxMovie:CacheCustomizations",
        "WillowGame.CharacterSelectionReduxGFxMovie:UpdatePlayerStandIn",
        "WillowGame.CustomizationGFxMovie:PreviewSkinCustomization",
        "WillowGame.CustomizationGFxMovie:PreviewHeadCustomization",
        "WillowGame.CustomizationGFxMovie:UpdateSkinPreview",
        "WillowGame.CustomizationGFxMovie:UpdateHeadPreview",
        "WillowGame.CustomizationGFxMovie:CacheCustomizations",
        "Engine.GameInfo:InitGame",
    )
]
for _i, _h in enumerate(_hot_hooks):
    globals()[f"_hot_hook_{_i}"] = _h


_frame_errors: set = set()


def _frame() -> None:
    """Per-frame work. A failing step is written to the log once, never every frame (an error
    every frame floods the SDK log and makes the game hitch)."""
    for step in (fast_material_pass, upkeep, vehicles.tick, buzzaxe.tick):
        try:
            step()
        except Exception as ex:  # noqa: BLE001
            key = f"{getattr(step, '__module__', '')}.{getattr(step, '__name__', step)}"
            if key not in _frame_errors:
                _frame_errors.add(key)
                log(f"{key} failed: {type(ex).__name__}: {ex}")


@hook("Engine.GameViewportClient:Tick", Type.PRE, hook_identifier="KriegTPSFastMaterials")
def on_viewport_tick(*_) -> None:
    # Runs after async loading and before the frame is drawn.
    _frame()


@hook("Engine.PlayerController:PlayerTick", Type.PRE)
def on_player_tick(*_) -> None:
    _frame()


@hook("Engine.HUD:PostRender", Type.PRE)
def on_post_render(*_) -> None:
    upkeep()


@command("krieg_offset", description="Move Krieg on the character select screen: krieg_offset X Y Z")
def krieg_offset(args: argparse.Namespace) -> None:
    krieg = find("PlayerClassDefinition", KRIEG_CLASS)
    if krieg is None:
        log("Krieg's class is not loaded")
        return
    off = krieg.CharacterSelectUIPrimaryStandInOffset
    if args.xyz:
        off.X, off.Y, off.Z = args.xyz
    log(f"character select offset is now {off.X:.2f} {off.Y:.2f} {off.Z:.2f} (takes effect when the screen reloads)")


krieg_offset.add_argument("xyz", nargs="*", type=float)


# Freeze diagnostics: writes freeze_log.txt in this folder if the game thread stops ticking.
try:
    from . import watchdog  # noqa: F401
except Exception as ex:  # noqa: BLE001
    log(f"watchdog not started: {type(ex).__name__}: {ex}")


# Automatic updates: the installer keeps its own copy (and a private Python) in
# %LOCALAPPDATA%\VaultLauncher. Once per game launch it is started in the background to ask Nexus Mods
# for a newer release; it installs the update after the game is closed.
def _start_update_check() -> None:
    import os
    import subprocess
    from pathlib import Path

    base = Path(os.environ.get("LOCALAPPDATA", "")) / "VaultLauncher"
    py = base / "python" / "pythonw.exe"
    run = base / "app" / "run.py"
    if not (py.is_file() and run.is_file()):
        return
    subprocess.Popen(  # noqa: S603 - our own updater
        [str(py), str(run), "update", "--auto", "--game-pid", str(os.getpid())],
        cwd=str(base), close_fds=True,
        creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    )
    log("update check started in the background")


try:
    _start_update_check()
except Exception as ex:  # noqa: BLE001
    log(f"update check not started: {type(ex).__name__}: {ex}")


# Melee check: Pre-Sequel "smash" obstructions (like the wrecked loader in Lost Legion Invasion)
# only break on damage tagged as melee. Logs what Krieg's hits on interactive objects carry, so a
# failure can be traced (first 25 hits per session).
_io_hits = [0]


def _is_local_krieg(pawn) -> bool:
    try:
        pc = get_pc()
        return pawn is not None and pc is not None and pawn == pc.Pawn and \
            pawn.PlayerClass is not None and "Lilac" in pawn.PlayerClass._path_name()
    except Exception:  # noqa: BLE001
        return False


@hook("WillowGame.WillowInteractiveObject:TakeDamage", Type.PRE, hook_identifier="KriegTPSIOHit")
def on_io_take_damage(obj, args, *_):
    if _io_hits[0] >= 25:
        return
    try:
        inst = getattr(args, "EventInstigator", None) or getattr(args, "InstigatedBy", None)
        pawn = inst.Pawn if inst is not None else None
        if not _is_local_krieg(pawn):
            return
        _io_hits[0] += 1
        fields = []
        fields.append(f"RawDamage={args.RawDamage:.1f}")
        fields.append(f"DamageType={args.DamageType._path_name() if args.DamageType else None}")
        pipe = args.Pipeline
        for name in ("DamageSource", "DamageTypeDefinition", "bIsMelee"):
            if pipe is not None and hasattr(pipe, name):
                v = getattr(pipe, name)
                fields.append(f"{name}={v._path_name() if hasattr(v, '_path_name') else v}")
        io_def = getattr(obj, "InteractiveObjectDefinition", None)
        log(f"melee check: Krieg hit {io_def._path_name() if io_def else obj._path_name()}: {', '.join(fields)}")
    except Exception as ex:  # noqa: BLE001
        log(f"melee check failed: {type(ex).__name__}: {ex}")


# Co-op check: when joining fails, both games say why somewhere - the host refuses in PreLogin or
# Login, the joining side gets a connection error or a kick message. Logged so it can be fixed.
def _arg(args, name):
    try:
        v = getattr(args, name)
        return v._path_name() if hasattr(v, "_path_name") else v
    except Exception:  # noqa: BLE001
        return "?"


@hook("Engine.GameInfo:PreLogin", Type.POST, hook_identifier="KriegTPSCoopPreLogin")
def on_pre_login(obj, args, *_):
    log(f"co-op: player joining from {_arg(args, 'Address')} - options {_arg(args, 'Options')!r}, "
        f"refusal {_arg(args, 'ErrorMessage')!r}")


@hook("WillowGame.WillowGameInfo:Login", Type.POST, hook_identifier="KriegTPSCoopLogin")
def on_login(obj, args, ret, *_):
    log(f"co-op: login {'accepted' if ret is not None else 'REFUSED'} - refusal {_arg(args, 'ErrorMessage')!r}")


@hook("WillowGame.WillowGameViewportClient:NotifyConnectionError", Type.PRE, hook_identifier="KriegTPSCoopError")
def on_connection_error(obj, args, *_):
    log(f"co-op: connection error {_arg(args, 'Title')!r}: {_arg(args, 'Message')!r}")


@hook("WillowGame.WillowPlayerController:ClientWasKicked", Type.PRE, hook_identifier="KriegTPSCoopKicked")
def on_kicked(obj, *_):
    log("co-op: the host disconnected this player (ClientWasKicked)")


_mod = build_mod(
    name="Krieg for TPS",
    description="Adds Borderlands 2's Krieg the Psycho as a seventh Vault Hunter.",
    mod_type=ModType.Standard,
    supported_games=Game.TPS,
    auto_enable=True,
)

# Krieg is not optional once his DLC folder is installed: without these hooks his heads, skins,
# materials, Oz kit, HUD and vehicle seats break. Newer mod managers only switch a mod on at launch
# if it was on last time, so a fresh mod manager (or lost settings) would leave him switched off.
if not _mod.is_enabled:
    _mod.enable()
    log("mod switched on")
