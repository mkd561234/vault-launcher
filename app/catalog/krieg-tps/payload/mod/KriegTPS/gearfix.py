"""Krieg's shield, grenade mod and Oz kit not working after a co-op level load.

Seen in a co-op log: right after the host loaded the level with a second player, both Kriegs
had their shield, grenade mod and Oz kit equipped but none of them did anything - shield 0/0,
oxygen at the no-Oz-kit amount, ground slam switched off. Playing alone the same gear works.

On the host (or alone) every Krieg is checked a few seconds after he appears. If he has a shield
equipped and his shield capacity is 0, or an Oz kit equipped and his ground slam is off, his
equipped gear is taken off and put back on, which makes the game apply it again. Everything
is written to the Krieg log (what was equipped and what the pools read before and after).
"""

import time

from mods_base import command, get_pc

CHECK_AFTER = 8.0
_state = {"next": 0.0, "seen": {}, "logs": 0}


def log(msg: str) -> None:
    if _state["logs"] >= 150:
        return
    _state["logs"] += 1
    from . import log as _log
    _log("gear: " + msg)


def _get(obj, attr, default=None):
    try:
        return getattr(obj, attr)
    except Exception:  # noqa: BLE001
        return default


def _max(pool_struct) -> float:
    data = _get(pool_struct, "Data")
    try:
        return float(data.GetMaxValue())
    except Exception:  # noqa: BLE001
        return -1.0


def _pawns():
    out = []
    pc = get_pc()
    try:
        pawn = pc.WorldInfo.PawnList
        for _ in range(512):
            if pawn is None:
                break
            if _get(pawn, "SlamForceBaseValue") is not None and "Lilac" in str(_get(pawn, "ObjectArchetype")):
                out.append(pawn)
            pawn = pawn.NextPawn
    except Exception:  # noqa: BLE001
        pass
    return out


def _equipped(pawn) -> list:
    mgr = _get(pawn, "InvManager")
    items = []
    inv = _get(mgr, "ItemChain") if mgr is not None else None
    seen = set()
    for _ in range(32):
        if inv is None or inv._get_address() in seen:
            break
        seen.add(inv._get_address())
        items.append(inv)
        inv = _get(inv, "Inventory")
    return items


def _kind(inv) -> str:
    name = str(inv.Class.Name).lower()
    if "shield" in name:
        return "shield"
    if "grenade" in name:
        return "grenade mod"
    if "classmod" in name:
        return "class mod"
    if "artifact" in name or "oz" in name or "relic" in name:
        return "Oz kit"
    return inv.Class.Name


def _describe(pawn) -> str:
    parts = []
    for inv in _equipped(pawn):
        defn = _get(inv, "DefinitionData")
        bal = _get(defn, "BalanceDefinition") if defn is not None else None
        name = str(bal._path_name()).rsplit(".", 1)[-1] if bal is not None else str(inv.Name)
        readied = None
        try:
            readied = bool(inv.IsReadied())
        except Exception:  # noqa: BLE001
            readied = _get(inv, "bReadied")
        parts.append(f"{_kind(inv)} {name} ({inv.Class.Name}, readied {readied})")
    return ", ".join(parts) or "nothing"


def _pools(pawn) -> str:
    return (f"shield max {_max(_get(pawn, 'ShieldArmor')):.0f}, oxygen max {_max(_get(pawn, 'OxygenPool')):.0f}, "
            f"slam {'on' if _get(pawn, 'SlamEnabled') else 'off'}")


def _broken(pawn) -> list:
    kinds = {_kind(i) for i in _equipped(pawn)}
    bad = []
    if "shield" in kinds and _max(_get(pawn, "ShieldArmor")) == 0:
        bad.append("shield does nothing")
    if "Oz kit" in kinds and not _get(pawn, "SlamEnabled"):
        bad.append("Oz kit does nothing")
    return bad


def _reequip(pawn) -> None:
    mgr = _get(pawn, "InvManager")
    if mgr is None:
        return
    for inv in _equipped(pawn):
        if _kind(inv) == "class mod":
            continue
        try:
            mgr.InventoryUnreadied(inv, True)
        except Exception as ex:  # noqa: BLE001
            log(f"could not take off {inv.Class.Name}: {type(ex).__name__}: {ex}")
            continue
        try:
            mgr.ReadyBackpackInventory(inv)
        except Exception as ex:  # noqa: BLE001
            log(f"could not put {inv.Class.Name} back on: {type(ex).__name__}: {ex}")


def _who(pawn) -> str:
    return str(_get(_get(pawn, "PlayerReplicationInfo"), "PlayerName", "?"))


def _is_authority(pawn) -> bool:
    role = _get(pawn, "Role")
    return "Authority" in str(getattr(role, "name", role))


def upkeep() -> None:
    now = time.monotonic()
    if now < _state["next"]:
        return
    _state["next"] = now + 1.0
    alive = set()
    for pawn in _pawns():
        key = pawn._get_address()
        alive.add(key)
        info = _state["seen"].setdefault(key, {"since": now, "step": 0})
        if now - info["since"] < CHECK_AFTER:
            continue
        if _get(_get(pawn, "HealthPool"), "Data") is None:
            continue
        if info["step"] == 0:
            info["step"] = 1
            bad = _broken(pawn) if _is_authority(pawn) else []
            log(f"{_who(pawn)}'s Krieg wears {_describe(pawn)}; {_pools(pawn)}"
                + (f" - {', '.join(bad)}: putting his gear back on" if bad else ""))
            if bad:
                _reequip(pawn)
                info["step"] = 2
                info["fixed_at"] = now
        elif info["step"] == 2 and now - info.get("fixed_at", now) >= 3.0:
            info["step"] = 3
            bad = _broken(pawn)
            log(f"{_who(pawn)}'s Krieg after putting his gear back on: {_pools(pawn)}"
                + (f" - still: {', '.join(bad)}" if bad else " - working"))
    for key in list(_state["seen"]):
        if key not in alive:
            del _state["seen"][key]


@command("krieg_gear", description="Write every Krieg's equipped gear to the Krieg log, and put it back on if it does nothing.")
def krieg_gear(_args) -> None:
    for pawn in _pawns():
        bad = _broken(pawn) if _is_authority(pawn) else []
        log(f"{_who(pawn)}'s Krieg wears {_describe(pawn)}; {_pools(pawn)}"
            + (f" - {', '.join(bad)}: putting his gear back on" if bad else ""))
        if bad:
            _reequip(pawn)


gear_hooks = [krieg_gear]
