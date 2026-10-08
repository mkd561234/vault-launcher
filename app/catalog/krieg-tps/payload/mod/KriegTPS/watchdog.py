"""Freeze diagnostics for KriegTPS.

If the game thread stops ticking for a few seconds (the freeze when loading in as Krieg),
a background thread samples where the game thread is stuck: instruction pointer plus the
return addresses found on its stack, written as offsets into the module they belong to.
Everything goes to freeze_log.txt next to this file, flushed line by line, so it survives the freeze.
Read-only: it never writes game memory.
"""

import ctypes
import threading
import time
from ctypes import wintypes
from pathlib import Path

from mods_base import hook
from unrealsdk.hooks import Type

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

THREAD_ALL = 0x001F03FF
CONTEXT_CONTROL = 0x00010001
CONTEXT_INTEGER = 0x00010002
STALL_SECONDS = 8.0
SAMPLE_EVERY = 5.0
MAX_SAMPLES = 80
STACK_BYTES = 0x6000


class CONTEXT(ctypes.Structure):  # x86 CONTEXT, 716 bytes
    _fields_ = [("ContextFlags", wintypes.DWORD),
                ("_dr", wintypes.DWORD * 6),
                ("_float", ctypes.c_byte * 112),
                ("SegGs", wintypes.DWORD), ("SegFs", wintypes.DWORD),
                ("SegEs", wintypes.DWORD), ("SegDs", wintypes.DWORD),
                ("Edi", wintypes.DWORD), ("Esi", wintypes.DWORD),
                ("Ebx", wintypes.DWORD), ("Edx", wintypes.DWORD),
                ("Ecx", wintypes.DWORD), ("Eax", wintypes.DWORD),
                ("Ebp", wintypes.DWORD), ("Eip", wintypes.DWORD),
                ("SegCs", wintypes.DWORD), ("EFlags", wintypes.DWORD),
                ("Esp", wintypes.DWORD), ("SegSs", wintypes.DWORD),
                ("_ext", ctypes.c_byte * 512)]


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD), ("RegionSize", ctypes.c_size_t),
                ("State", wintypes.DWORD), ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD)]


k32.OpenThread.restype = wintypes.HANDLE
k32.GetModuleHandleW.restype = ctypes.c_void_p
k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
k32.SuspendThread.argtypes = [wintypes.HANDLE]
k32.ResumeThread.argtypes = [wintypes.HANDLE]
k32.GetThreadContext.argtypes = [wintypes.HANDLE, ctypes.POINTER(CONTEXT)]
k32.VirtualQuery.argtypes = [ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
k32.GetModuleHandleExW.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.HMODULE)]
k32.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]

_state = {"tid": None, "beat": time.monotonic(), "started": False, "samples": 0, "last_fn": ""}
_ctx = CONTEXT()
_stack = ctypes.create_string_buffer(STACK_BYTES)
_mods: dict[int, str] = {}


LOG_PATH = Path(__file__).with_name("freeze_log.txt")
_log_lock = threading.Lock()
try:
    if LOG_PATH.exists():
        LOG_PATH.replace(LOG_PATH.with_name("freeze_log_prev.txt"))
except OSError:
    pass
_log_file = open(LOG_PATH, "w", encoding="utf-8")  # noqa: SIM115 - kept open for the session


def log(msg: str) -> None:
    # Own file, written and flushed from any thread, never through the game's console.
    with _log_lock:
        _log_file.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        _log_file.flush()


def _module_of(addr: int):
    h = wintypes.HMODULE()
    # FROM_ADDRESS | UNCHANGED_REFCOUNT
    if not k32.GetModuleHandleExW(0x4 | 0x2, ctypes.c_void_p(addr), ctypes.byref(h)) or not h.value:
        return None
    base = h.value
    if base not in _mods:
        buf = ctypes.create_unicode_buffer(260)
        k32.GetModuleFileNameW(h, buf, 260)
        _mods[base] = buf.value.rsplit("\\", 1)[-1]
    return _mods[base], base


def _fmt(addr: int) -> str:
    m = _module_of(addr)
    return f"{m[0]}+0x{addr - m[1]:X}" if m else f"0x{addr:X}"


def _is_executable(addr: int) -> bool:
    mbi = MBI()
    if not k32.VirtualQuery(ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
        return False
    return mbi.State == 0x1000 and (mbi.Protect & 0xF0) != 0  # committed, any EXECUTE_*


ASYNC_ARCHIVE_VTABLE_RVA = 0x114E160  # FArchiveAsync vtable in this build of BorderlandsPreSequel.exe
_exe_base = k32.GetModuleHandleW(None)


def _readable(addr: int, size: int) -> bool:
    mbi = MBI()
    if addr < 0x10000 or not k32.VirtualQuery(ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
        return False
    return (mbi.State == 0x1000 and (mbi.Protect & 0x66) != 0 and not (mbi.Protect & 0x100)
            and addr + size <= mbi.BaseAddress + mbi.RegionSize)


def _u32(addr: int) -> int:
    return int.from_bytes(ctypes.string_at(addr, 4), "little")


def _describe_async_archives(words) -> None:
    """Find FArchiveAsync objects referenced from the stalled stack: which file, where it reads."""
    seen = set()
    vt = _exe_base + ASYNC_ARCHIVE_VTABLE_RVA
    for w in words:
        if w in seen or not _readable(w, 0xD0):
            continue
        seen.add(w)
        if _u32(w) != vt:
            continue
        name_ptr, name_num = _u32(w + 0x88), _u32(w + 0x8C)
        name = "?"
        if 0 < name_num < 1024 and _readable(name_ptr, name_num * 2):
            name = ctypes.wstring_at(name_ptr, name_num - 1)
        log(f"  async archive {w:X}: file={name} FileSize={_u32(w + 0x94)} Uncompressed={_u32(w + 0x98)} "
            f"Pos={_u32(w + 0x9C)} Precache=[{_u32(w + 0xA0)}..{_u32(w + 0xA8)}) "
            f"pending={_u32(w + 0xB8)},{_u32(w + 0xBC)} chunks={_u32(w + 0xC0):X}")


def sample(handle) -> None:
    _ctx.ContextFlags = CONTEXT_CONTROL | CONTEXT_INTEGER
    if k32.SuspendThread(handle) == 0xFFFFFFFF:
        log("SuspendThread failed")
        return
    try:
        ok = k32.GetThreadContext(handle, ctypes.byref(_ctx))
        esp = _ctx.Esp
        n = 0
        if ok:
            mbi = MBI()
            if k32.VirtualQuery(ctypes.c_void_p(esp), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                n = min(STACK_BYTES, mbi.BaseAddress + mbi.RegionSize - esp)
                ctypes.memmove(_stack, esp, n)
    finally:
        k32.ResumeThread(handle)
    if not ok:
        log(f"GetThreadContext failed ({ctypes.get_last_error()})")
        return
    words = memoryview(_stack.raw[:n & ~3]).cast("I")
    frames = [_fmt(w) for w in words if w > 0x10000 and _is_executable(w)][:48]
    log(f"stall sample #{_state['samples']}: EIP={_fmt(_ctx.Eip)} EAX={_ctx.Eax:X} ECX={_ctx.Ecx:X} "
        f"EDX={_ctx.Edx:X} ESI={_ctx.Esi:X} EDI={_ctx.Edi:X} last script call={_state['last_fn']}")
    log("  stack: " + " ".join(frames))
    regs = [_ctx.Eax, _ctx.Ebx, _ctx.Ecx, _ctx.Edx, _ctx.Esi, _ctx.Edi, _ctx.Ebp]
    _describe_async_archives(regs + list(words))


def _watch() -> None:
    handle = None
    while True:
        time.sleep(SAMPLE_EVERY)
        tid = _state["tid"]
        if tid is None:
            continue
        if handle is None:
            handle = k32.OpenThread(THREAD_ALL, False, tid)
            if not handle:
                log(f"OpenThread failed ({ctypes.get_last_error()})")
                return
        stalled = time.monotonic() - _state["beat"]
        if stalled < STALL_SECONDS or _state["samples"] >= MAX_SAMPLES:
            continue
        _state["samples"] += 1
        _state["stalled"] = True
        log(f"game thread has not ticked for {stalled:.0f}s")
        try:
            sample(handle)
        except Exception as ex:  # noqa: BLE001 - diagnostics only
            log(f"sample failed: {type(ex).__name__}: {ex}")


def _beat(name: str) -> None:
    now = time.monotonic()
    if _state.get("stalled"):
        _state["stalled"] = False
        log(f"game thread running again after {now - _state['beat']:.1f}s (in {name})")
    _state["beat"] = now
    if _state["tid"] is None:
        _state["tid"] = threading.get_native_id()
        log(f"watching game thread {_state['tid']}")
    if not _state["started"]:
        _state["started"] = True
        threading.Thread(target=_watch, name="KriegTPSWatch", daemon=True).start()


def _make_beat(func: str):
    def _cb(*_):
        _beat(func)
    return hook(func, Type.PRE, immediately_enable=True, hook_identifier=f"KriegTPSBeat_{func}")(_cb)


# Called every frame while in game; any of them firing means the game thread is alive.
beat_hooks = [_make_beat(f) for f in (
    "Engine.PlayerController:PlayerTick",
    "Engine.HUD:PostRender",
    "Engine.GameViewportClient:Tick",
)]


# Milestones of a level load / player spawn, logged so the last one before a freeze shows up.
MILESTONES = (
    "Engine.GameInfo:InitGame",
    "Engine.GameInfo:PreLogin",
    "Engine.GameInfo:Login",
    "Engine.GameInfo:PostLogin",
    "Engine.GameInfo:StartMatch",
    "Engine.GameInfo:RestartPlayer",
    "Engine.GameInfo:SpawnDefaultPawnFor",
    "Engine.PlayerController:Possess",
    "Engine.PlayerController:ClientRestart",
    "Engine.Pawn:PostBeginPlay",
    "WillowGame.WillowPlayerController:ClientFinishedLoading",
    "WillowGame.WillowPlayerController:ServerPlayerLoaded",
    "WillowGame.WillowPlayerPawn:PostBeginPlay",
    "WillowGame.WillowPlayerPawn:PossessedBy",
    "WillowGame.WillowGameInfo:PostLogin",
    "WillowGame.WillowGameInfo:InitGame",
)


def _make_milestone(func: str):
    def _cb(obj, *_):
        _state["last_fn"] = func
        _beat(func)
        try:
            who = obj._path_name()
        except Exception:  # noqa: BLE001
            who = "?"
        log(f"{func} on {who}")
    return hook(func, Type.PRE, immediately_enable=True, hook_identifier=f"KriegTPSWatch_{func}")(_cb)


milestone_hooks = [_make_milestone(f) for f in MILESTONES]
