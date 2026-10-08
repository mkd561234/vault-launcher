"""Butt slam damage and effects for Krieg.

In the Pre-Sequel the slam's damage, particles and sound all come from each character's "player
events" list (a "Slam" sequence started when the slam lands). Krieg's list comes from Borderlands 2
and has no such sequence, so his slams hit the ground and did nothing.

Copying Aurelia's sequence crashed the game earlier (her package gets reloaded when she is picked),
so the same pieces are rebuilt here as stand-alone objects in the transient package, using the
values from her sequence:

* the main hit: the Oz kit's slam element (fire, shock, corrosive, cryo - checked in that order like
  the game does - or explosive when the kit has none), 500 radius, full damage across the radius,
  the Pre-Sequel's slam damage formula (Oz kit level, slam damage grade and how far you fell).
  Elemental slams do that damage plus an elemental damage-over-time of 30% of it; the plain slam
  does 120%. How far you fell also sets the knock-back and the chance to set enemies on fire /
  freeze / electrocute / melt them (x4 below 375 units, x8 up to 700, x16 above);
* the oxygen-mask shatter hit (50 damage, 500 radius) every character's slam does;
* the matching slam particle effect and sound.

In co-op the slam is the host's business: damage, knock-back and status effects only count when the
host's game applies them, and only the host knows the Oz kit's element and grade for every player
(a client reads 0 for them, which turned a cryo kit into a plain explosive slam). So a joining
Krieg's game reports each slam (and how far he fell) to the host with an unused server command, and
the host's game applies it; single player, or a Krieg who hosts, applies his own. The particle
and sound are sent to everyone.

They are fired from the slam landing (WillowPlayerPawn.DoSlamEffects), with the landing itself as a
fallback in case that is not called for Krieg.
"""

import time

import unrealsdk
from mods_base import ObjectFlags, get_pc, hook
from unrealsdk.hooks import Type
from unrealsdk.unreal import WrappedStruct

RADIUS = 500.0
SHATTER_DAMAGE = 50.0
DAMAGE_GRADE_SCALE = 0.035  # from Aurelia's sequence: Slam_DamageGrade * 0.035
# Constants from the Pre-Sequel's slam formula (Init_PlayerSlamDamage and the D_Attributes.Slam
# constants that are cooked into each character package, not into Krieg's).
INIT_MULTIPLIER = 5e-05
DAMAGE_CAP_DISTANCE = 1200.0
DAMAGE_BONUS_DISTANCE = 200.0
DAMAGE_EXPONENT = 2.1
BALANCE_SCALER = "GD_Balance_HealthAndDamage.HealthAndDamage.Att_UniversalBalanceScaler"
KIT_LEVEL = "D_Attributes.Inventory.MoonItemItemLevel"
JUGGERNAUT_BONUS = "GD_MoonItems.Misc.JuggernautSlamBonusDamage"
GRADE_ATTR = "D_Attributes.Slam.Slam_DamageGrade"
DMG_SOURCE = "OzWillowDmgSource_Slam"

# Oz kit element attribute -> (damage type, impact, particle, particle scale, sound)
ELEMENTS = {
    "fire": ("D_Attributes.Slam.Slam_FireDamage", "GD_Incendiary.DamageType.DmgType_Incendiary_Impact",
             "GD_Impacts.ExplosiveImpacts.ExplosiveImpactIncendiary512",
             "FX_CO_Shared.Particles.PS_Slam_Fire_500r", 1.0,
             "Ake_Cork_FX_Global.Slam.Ak_Play_Cork_FX_Slam_Incendiary"),
    "cryo": ("D_Attributes.Slam.Slam_CryoDamage", "GD_Ice.DamageType.DmgType_Ice_Impact",
             "GD_Impacts.ExplosiveImpacts.ExplosiveImpactIncendiary512",
             "FX_CO_Shared.Particles.PS_Slam_Ice_500r", 1.5,
             "Ake_Cork_FX_Global.Slam.Ak_Play_Cork_FX_Slam_Ice"),
    "shock": ("D_Attributes.Slam.Slam_ShockDamage", "GD_Shock.DamageType.DmgType_Shock_Impact",
              "GD_Impacts.ExplosiveImpacts.ExplosiveImpactIncendiary512",
              "FX_CO_Shared.Particles.PS_Slam_Shock_500r", 2.0,
              "Ake_Cork_FX_Global.Slam.Ak_Play_Cork_FX_Slam_Shock"),
    "corrosive": ("D_Attributes.Slam.Slam_CorrosiveDamage", "GD_Corrosive.DamageType.DmgType_Corrosive_Impact",
                  "GD_Impacts.ExplosiveImpacts.ExplosiveImpactIncendiary512",
                  "FX_CO_Shared.Particles.PS_Slam_Corrosive_500r", 1.0,
                  "Ake_Cork_FX_Global.Slam.Ak_Play_Cork_FX_Slam_Corrosive"),
}
NORMAL = (None, "GD_Explosive.DamageType.DmgType_Explosive_Impact_ForceFlinch",
          "GD_Impacts.ExplosiveImpacts.ExplosiveImpactNormal512",
          "FX_CO_Shared.Particles.Part_PlayerSlam_500r", 1.0,
          "Ake_Cork_FX_Global.Slam.Ak_Play_Cork_FX_Slam")
SHATTER_TYPE = "GD_Impact.DamageType.DmgType_AirMaskShatter"
CHECK_ORDER = ("fire", "shock", "corrosive", "cryo")   # the game's Conditional order
ELEMENT_DOT_SCALE = 0.3      # StatusEffectDamage = SlamDamage * 0.3 in every elemental branch
NORMAL_DAMAGE_SCALE = 1.2    # the plain slam's DamageFormula = SlamDamage * 1.2
# (fall distance up to, status-effect chance, knock-back multiplier) - the soft/mid/loud branches
TIERS = ((375.0, 4.0, 1.0), (700.0, 8.0, 1.5), (float("inf"), 16.0, 2.0))
MOMENTUM_ATTR = "GD_Balance_HealthAndDamage.HealthAndDamage.Att_SlamMomentum"
# The elemental slam effects (and the knock-back attribute) are cooked into each Pre-Sequel
# character's own package, never into Krieg's. Athena's is the smallest one that has them.
FX_PACKAGE = "GD_Gladiator_Streaming_SF"
FX_KEEP = [ELEMENTS[k][3] for k in ELEMENTS]

_state = {"pending": {}, "last": {}, "logs": 0, "warned": set(), "dist": (0.0, -1.0), "fx": None}
_objs: dict[str, object] = {}


def log(msg: str) -> None:
    from . import log as _log
    _log(msg)


def _warn(key: str, msg: str) -> None:
    if key not in _state["warned"]:
        _state["warned"].add(key)
        log(msg)


def _find(cls: str, path: str):
    try:
        return unrealsdk.find_object(cls, path)
    except ValueError:
        return None


def _transient():
    return _find("Package", "Transient")


def _new(cls_name: str, name: str):
    """A behaviour object of our own, outside every character package, kept loaded."""
    obj = _objs.get(name)
    if obj is not None:
        return obj
    obj = unrealsdk.construct_object(unrealsdk.find_class(cls_name), _transient(), name)
    obj.ObjectFlags |= ObjectFlags.KEEP_ALIVE
    _objs[name] = obj
    return obj


def _formula(template, value: float):
    return unrealsdk.make_struct(template._type.Name, BaseValueConstant=value, BaseValueAttribute=None,
                                 InitializationDefinition=None, BaseValueScaleConstant=1.0)


def upkeep() -> None:
    """Load the effects early (while Krieg is in the game) so the first slam doesn't hitch."""
    if _state["fx"] is not None:
        return
    pc = get_pc()
    if pc is None:
        return
    if _is_local_krieg_pawn(pc.Pawn):
        ensure_fx()
        return
    # hosting a Krieg: load them too, so his first slam doesn't hitch the host
    try:
        pawn = pc.WorldInfo.PawnList
        for _ in range(64):
            if pawn is None:
                break
            if _runs_slam(pawn):
                ensure_fx()
                return
            pawn = pawn.NextPawn
    except Exception:  # noqa: BLE001
        pass


def ensure_fx() -> None:
    """Load the elemental slam effects once per game session and keep them loaded."""
    if _state["fx"] is not None:
        return
    if all(_find("ParticleSystem", path) is not None for path in FX_KEEP):
        _state["fx"] = True
    else:
        try:
            unrealsdk.load_package(FX_PACKAGE)
        except Exception as ex:  # noqa: BLE001
            log(f"slam: could not load {FX_PACKAGE}: {type(ex).__name__}: {ex}")
        _state["fx"] = all(_find("ParticleSystem", path) is not None for path in FX_KEEP)
    kept = 0
    for path, cls in [(x, "ParticleSystem") for x in FX_KEEP] + [(MOMENTUM_ATTR, "Object")]:
        obj = _find(cls, path)
        if obj is not None:
            obj.ObjectFlags |= ObjectFlags.KEEP_ALIVE
            kept += 1
    log(f"slam: elemental slam effects {'ready' if _state['fx'] else 'still missing'} "
        f"({kept}/{len(FX_KEEP) + 1} effects/attributes kept loaded)")


def _set_formula(b, prop: str, value: float, attr=None, scale: float = 1.0) -> None:
    try:
        template = getattr(b, prop)
    except AttributeError:
        _warn(f"prop {prop}", f"slam: Behavior_CauseDamage has no {prop}")
        return
    setattr(b, prop, unrealsdk.make_struct(template._type.Name, BaseValueConstant=value,
                                           BaseValueAttribute=attr, InitializationDefinition=None,
                                           BaseValueScaleConstant=scale))


def _damage_behavior(name: str, dmg_type: str, impact: str | None, damage: float, status_chance: float,
                     skip_trace: bool, dot: float = 0.0, momentum: float = 0.0):
    b = _new("Behavior_CauseDamage", name)
    b.DamageFormula = _formula(b.DamageFormula, damage)
    b.RadiusFormula = _formula(b.RadiusFormula, RADIUS)
    b.StatusEffectChance = _formula(b.StatusEffectChance, status_chance)
    _set_formula(b, "StatusEffectDamage", dot)
    momentum_attr = _find("Object", MOMENTUM_ATTR) if momentum else None
    if momentum_attr is not None:   # knock-back: Att_SlamMomentum x the fall-height multiplier
        _set_formula(b, "MomentumFormula", 0.0, momentum_attr, momentum)
    b.DamageSource = unrealsdk.find_class(DMG_SOURCE)
    b.DamageTypeDefinition = _find("Object", dmg_type)
    b.ImpactDefinition = _find("Object", impact) if impact else None
    b.bInflictRadiusDamage = True
    b.bDisableRadiusDamageFalloff = True
    b.bSkipTraceTest = skip_trace
    b.BarrelSourceTime = -1.0
    return b


def _particle_behavior(name: str, particle: str, scale: float):
    effect = _find("ParticleSystem", particle)
    if effect is None:
        _warn(particle, f"slam: particle {particle} is not loaded")
        return None
    b = _new("Behavior_SpawnParticleSystem", name)
    b.ParticleEffect = effect
    b.DrawScale = scale
    b.bReplicateEmitter = True
    return b


def _attr(path: str, pawn) -> float:
    attr = _find("Object", path)
    if attr is None:
        _warn(path, f"slam: attribute {path} is not loaded")
        return 0.0
    try:
        result = attr.GetValue(pawn)
        return float(result[0] if isinstance(result, tuple) else result)
    except Exception as ex:  # noqa: BLE001
        _warn(path, f"slam: could not read {path}: {type(ex).__name__}: {ex}")
        return 0.0


def _level(pawn) -> int:
    try:
        return max(1, int(pawn.Controller.PlayerReplicationInfo.ExpLevel))
    except Exception:  # noqa: BLE001
        return 1


def slam_damage(pawn, grade: float, distance: float) -> tuple[float, str]:
    """The Pre-Sequel's slam damage, as worked out in every character's "Slam" sequence:
    Init_PlayerSlamDamage * (1 + 0.035 * Slam_DamageGrade) * (min(distance, 1200) + 200) ^ 2.1,
    times (1 + the Juggernaut bonus). Init_PlayerSlamDamage is 0.00005 * UniversalBalanceScaler ^
    (Oz kit level), so the fall distance is what makes the number big."""
    scaler = _attr(BALANCE_SCALER, pawn)
    if not 1.01 <= scaler <= 1.5:
        scaler = 1.13  # the game's usual per-level growth
    kit_level = _attr(KIT_LEVEL, pawn)
    if not 1 <= kit_level <= 80:
        kit_level = 0.0
    level = kit_level if kit_level >= 1 else _level(pawn)
    init = INIT_MULTIPLIER * scaler ** level
    dist = max(0.0, min(distance, DAMAGE_CAP_DISTANCE)) + DAMAGE_BONUS_DISTANCE
    jugg = _attr(JUGGERNAUT_BONUS, pawn)
    damage = init * (1.0 + DAMAGE_GRADE_SCALE * grade) * dist ** DAMAGE_EXPONENT * (1.0 + jugg)
    info = (f"level {level:g}{' (Oz kit)' if kit_level >= 1 else ' (player)'}, scaler {scaler:g}, "
            f"fall {distance:.0f}, juggernaut {jugg:g}")
    return damage, info


def _empty_struct(behavior, param: str):
    try:
        func = behavior.Class._find("ApplyBehaviorToContext")
        return WrappedStruct(func._find(param).Struct)
    except Exception:  # noqa: BLE001
        return ()


def _apply(behavior, pawn) -> bool:
    try:
        behavior.ApplyBehaviorToContext(pawn, _empty_struct(behavior, "KernelInfo"), pawn, pawn, None,
                                        _empty_struct(behavior, "EventData"))
        return True
    except Exception as ex:  # noqa: BLE001
        _warn(f"apply {behavior.Name}", f"slam: {behavior.Name} failed: {type(ex).__name__}: {ex}")
        return False


def _post(pawn, path: str) -> None:
    event = _find("AkEvent", path)
    if event is None:
        _warn(path, f"slam: sound {path} is not loaded")
        return
    try:
        pawn.PlayAkEvent(event)          # plays here and is sent to the other players
    except Exception:  # noqa: BLE001
        try:
            pawn.PostAkEvent(event)
        except Exception as ex:  # noqa: BLE001
            _warn("sound", f"slam: could not play the slam sound: {type(ex).__name__}: {ex}")


def _is_local_krieg_pawn(pawn) -> bool:
    pc = get_pc()
    if pc is None or pawn is None or pc.Pawn is None:
        return False
    if pc.Pawn._get_address() != pawn._get_address():
        return False
    try:
        cls = pc.PlayerClass
        return cls is not None and "Lilac" in cls._path_name()
    except Exception:  # noqa: BLE001
        return False


def _is_krieg_pawn(pawn) -> bool:
    if pawn is None:
        return False
    try:
        arch = pawn.ObjectArchetype
        if arch is not None and "LilacPlayerClass" in arch._path_name():
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        cls = pawn.Controller.PlayerClass
        return cls is not None and "Lilac" in cls._path_name()
    except Exception:  # noqa: BLE001
        return False


def _has_authority(pawn) -> bool:
    try:
        role = pawn.Role
    except Exception:  # noqa: BLE001
        return True
    name = getattr(role, "name", str(role))
    return name.endswith("ROLE_Authority") or role == 3


def _runs_slam(pawn) -> bool:
    """This game applies the slam for that pawn: my own Krieg, when this game is in charge of it
    (single player, or I'm the host). A joining Krieg's slam is reported by his game instead
    (see report_slam), because the host's game doesn't see his slams."""
    return _is_local_krieg_pawn(pawn) and _has_authority(pawn)


def _is_joining_krieg(pawn) -> bool:
    return _is_local_krieg_pawn(pawn) and not _has_authority(pawn)


SLAM_MSG = "KTPS|SLAM|"


def report_slam(pawn, why: str) -> None:
    """Joining player: tell the host my Krieg slammed, and how far he fell."""
    now = time.monotonic()
    key = _key(pawn)
    if now - _state["last"].get(key, 0.0) < 0.5:
        return
    _state["last"][key] = now
    _state["pending"].pop(key, None)
    dist = _slam_distance(pawn, now)
    try:
        get_pc().ServerMutate(f"{SLAM_MSG}{dist:.0f}")
        if _state["logs"] < 8:
            _state["logs"] += 1
            log(f"slam ({why}): fell {dist:.0f}, sent to the host to apply")
    except Exception as ex:  # noqa: BLE001
        _warn("report", f"slam: could not tell the host: {type(ex).__name__}: {ex}")


@hook("Engine.PlayerController:ServerMutate", Type.PRE, hook_identifier="KriegTPSSlamFromClient")
def on_slam_message(obj, args, *_):
    msg = str(args.MutateString)
    if not msg.startswith(SLAM_MSG):
        return None
    try:
        dist = max(0.0, min(5000.0, float(msg[len(SLAM_MSG):] or 0)))
    except ValueError:
        dist = 0.0
    pawn = getattr(obj, "Pawn", None)
    if pawn is not None and _is_krieg_pawn(pawn) and _has_authority(pawn):
        _state["dist"] = (dist, time.monotonic())
        do_slam_hit(pawn, "joining player's slam")
    from unrealsdk.hooks import Block
    return Block


def _key(pawn) -> int:
    return pawn._get_address()


def _slam_distance(pawn, now: float) -> float:
    dist, when = _state["dist"]
    if 0 <= now - when < 2.0:
        return dist
    try:
        return max(0.0, float(pawn.SlamStartHeight) - float(pawn.Location.Z))
    except Exception:  # noqa: BLE001
        return 0.0


def do_slam_hit(pawn, why: str) -> None:
    now = time.monotonic()
    key = _key(pawn)
    if now - _state["last"].get(key, 0.0) < 0.5:
        return  # landing and DoSlamEffects both fire for one slam
    _state["last"][key] = now
    _state["pending"].pop(key, None)

    ensure_fx()
    grade = _attr(GRADE_ATTR, pawn)
    values = {key: _attr(ELEMENTS[key][0], pawn) for key in CHECK_ORDER}
    element = next((k for k in CHECK_ORDER if values[k] >= 1.0), None)
    spec = ELEMENTS[element] if element else NORMAL
    kind = element or "explosive"
    distance = _slam_distance(pawn, now)
    slam, info = slam_damage(pawn, grade, distance)
    _, chance, push = next(t for t in TIERS if distance <= t[0])

    if element:
        damage, dot = slam, slam * ELEMENT_DOT_SCALE
        main = _damage_behavior(f"KriegTPS_Slam_{kind}", spec[1], spec[2], damage, chance, False,
                                dot=dot, momentum=push)
    else:
        damage, dot = slam * NORMAL_DAMAGE_SCALE, 0.0
        main = _damage_behavior(f"KriegTPS_Slam_{kind}", spec[1], spec[2], damage, 0.0, False,
                                momentum=push)
    shatter = _damage_behavior("KriegTPS_Slam_Shatter", SHATTER_TYPE, None, SHATTER_DAMAGE, 0.0, True)
    particle = _particle_behavior(f"KriegTPS_SlamFX_{kind}", spec[3], spec[4])
    if particle is None and element:
        particle = _particle_behavior("KriegTPS_SlamFX_explosive", NORMAL[3], NORMAL[4])

    logging = _state["logs"] < 8
    if logging:
        _state["logs"] += 1
        who = "" if _is_local_krieg_pawn(pawn) else "co-op partner's "
        log(f"{who}slam hit ({why}): {kind} {damage:.0f} damage"
            f"{f' + {dot:.0f} {kind} damage over time, status chance x{chance:g}' if element else ''}"
            f" in {RADIUS:.0f} radius, knock-back x{push:g} ({info}, grade {grade:g}, "
            f"elements {', '.join(f'{k} {v:g}' for k, v in values.items())}, "
            f"effect {'ok' if particle is not None else 'missing'})")
    ok = _apply(main, pawn)
    _apply(shatter, pawn)
    if particle is not None:
        _apply(particle, pawn)
    _post(pawn, spec[5])
    if ok and logging:
        log("slam hit applied")


@hook("WillowGame.WillowPlayerPawn:DoSlam", Type.POST, hook_identifier="KriegTPSSlamStart")
def on_slam_start(obj, *_):
    if _runs_slam(obj) or _is_joining_krieg(obj):
        _state["pending"][_key(obj)] = time.monotonic()


@hook("WillowGame.PlayerEventProviderDefinition:DoSlamEffects", Type.PRE,
      hook_identifier="KriegTPSSlamDistance")
def on_slam_distance(obj, args, *_):
    try:
        _state["dist"] = (float(args.SlamDistance), time.monotonic())
    except Exception:  # noqa: BLE001
        pass


@hook("WillowGame.WillowPlayerPawn:DoSlamEffects", Type.POST, hook_identifier="KriegTPSSlamEffects")
def on_slam_effects(obj, *_):
    if _runs_slam(obj):
        do_slam_hit(obj, "slam effects")
    elif _is_joining_krieg(obj):
        report_slam(obj, "slam effects")


@hook("WillowGame.WillowPlayerPawn:Landed", Type.POST, hook_identifier="KriegTPSSlamLanded")
def on_landed(obj, *_):
    started = _state["pending"].get(_key(obj), 0.0)
    if not started or time.monotonic() - started > 10.0:
        return
    if _runs_slam(obj):
        do_slam_hit(obj, "landing")
    elif _is_joining_krieg(obj):
        report_slam(obj, "landing")


slam_hooks = [on_slam_start, on_slam_distance, on_slam_effects, on_landed, on_slam_message]
