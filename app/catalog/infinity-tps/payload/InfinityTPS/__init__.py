"""Infinity for TPS: Borderlands 2's Infinity pistol in the Pre-Sequel, made in the Grinder.

A legendary pistol, any legendary weapon and any purple pistol in the Grinder make an Infinity. Every one rolls its own element,
accessory, grip and sight. See infinity.py for how it is built. Works with every character.
"""

import time
from pathlib import Path

from mods_base import Game, ModType, build_mod, hook
from unrealsdk.hooks import Type

__version__ = "1.0.5"

_LOG = Path(__file__).with_name("infinity_log.txt")
_log_lines = [0]


def log(msg: str) -> None:
    if _log_lines[0] >= 300:
        return
    _log_lines[0] += 1
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass


try:
    _LOG.write_text(f"{time.strftime('%H:%M:%S')} Infinity mod {__version__}\n", encoding="utf-8")
except OSError:
    pass

from . import infinity  # noqa: E402

infinity_status = infinity.infinity_status     # console command, found by build_mod
from . import diag  # noqa: E402

for _i, _h in enumerate(diag.diag_hooks):      # build_mod finds hooks and commands in this module
    globals()[f"_diag_{_i}"] = _h
_next = [0.0]


_first = [True]


def _tick() -> None:
    if _first[0]:
        _first[0] = False
        log("running")
    now = time.monotonic()
    if now < _next[0]:
        return
    _next[0] = now + 1.0
    try:
        infinity.upkeep()
        diag.self_test()
    except Exception as ex:  # noqa: BLE001
        log(f"upkeep failed: {type(ex).__name__}: {ex}")


# The Pre-Sequel doesn't always run GameViewportClient.Tick through the SDK, so the player's tick
# and the HUD's draw call run it too (it does its work at most once a second).
@hook("Engine.GameViewportClient:Tick", Type.PRE, hook_identifier="InfinityTPSTick")
def on_tick(*_) -> None:
    _tick()


@hook("Engine.PlayerController:PlayerTick", Type.PRE, hook_identifier="InfinityTPSPlayerTick")
def on_player_tick(*_) -> None:
    _tick()


@hook("Engine.HUD:PostRender", Type.PRE, hook_identifier="InfinityTPSHUD")
def on_hud(*_) -> None:
    _tick()


_mod = build_mod(
    name="Infinity",
    description="Borderlands 2's Infinity pistol, made in the Grinder from a legendary pistol, a legendary weapon and any purple pistol.",
    mod_type=ModType.Standard,
    supported_games=Game.TPS,
    auto_enable=True,
)

if not _mod.is_enabled:
    _mod.enable()
