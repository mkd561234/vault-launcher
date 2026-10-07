"""Small Windows helpers (message boxes, Downloads folder, protected storage). All degrade to
plain console behaviour off Windows so the logic can be tested elsewhere."""

import base64
import ctypes
import os
import webbrowser
from pathlib import Path

IS_WINDOWS = os.name == 'nt'

MB_OK = 0x0
MB_YESNO = 0x4
MB_ICONINFORMATION = 0x40
MB_ICONWARNING = 0x30
MB_TOPMOST = 0x40000
MB_SETFOREGROUND = 0x10000
IDYES = 6

TITLE = 'Vault Launcher'


def message(text: str, warning: bool = False) -> None:
    if IS_WINDOWS:
        flags = MB_OK | MB_TOPMOST | MB_SETFOREGROUND | (MB_ICONWARNING if warning else MB_ICONINFORMATION)
        ctypes.windll.user32.MessageBoxW(None, text, TITLE, flags)
    else:
        print(f'[{TITLE}] {text}')


def ask(text: str) -> bool:
    if IS_WINDOWS:
        flags = MB_YESNO | MB_TOPMOST | MB_SETFOREGROUND | MB_ICONINFORMATION
        return ctypes.windll.user32.MessageBoxW(None, text, TITLE, flags) == IDYES
    print(f'[{TITLE}] {text} [y/N] (non-Windows: assuming no)')
    return False


def open_url(url: str) -> None:
    try:
        if IS_WINDOWS:
            os.startfile(url)  # noqa: S606 - opens the player's browser
        else:
            webbrowser.open(url)
    except OSError:
        webbrowser.open(url)


def data_dir() -> Path:
    base = os.environ.get('LOCALAPPDATA') or str(Path.home() / '.local' / 'share')
    d = Path(base) / 'VaultLauncher'
    d.mkdir(parents=True, exist_ok=True)
    return d


def downloads_dir() -> Path:
    if IS_WINDOWS:
        try:
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD), ('Data3', wintypes.WORD),
                            ('Data4', ctypes.c_ubyte * 8)]

            # FOLDERID_Downloads {374DE290-123F-4565-9164-39C4925E467B}
            g = GUID(0x374DE290, 0x123F, 0x4565, (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
            p = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) == 0:
                path = Path(p.value)
                ctypes.windll.ole32.CoTaskMemFree(p)
                return path
        except Exception:  # noqa: BLE001
            pass
    return Path.home() / 'Downloads'


# ---- Windows DPAPI: the Nexus API key is stored encrypted for the current Windows user ----------
class _Blob(ctypes.Structure):
    _fields_ = [('cbData', ctypes.c_uint32), ('pbData', ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    b = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    b._buf = buf  # keep alive
    return b


def protect(text: str) -> str:
    data = text.encode('utf-8')
    if not IS_WINDOWS:
        return 'plain:' + base64.b64encode(data).decode()
    out = _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(_blob(data)), None, None, None, None, 0,
                                                   ctypes.byref(out)):
        raise OSError('could not encrypt the Nexus key')
    try:
        return 'dpapi:' + base64.b64encode(ctypes.string_at(out.pbData, out.cbData)).decode()
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def unprotect(stored: str) -> str:
    kind, _, payload = stored.partition(':')
    raw = base64.b64decode(payload)
    if kind == 'plain':
        return raw.decode('utf-8')
    if not IS_WINDOWS:
        raise OSError('stored key can only be read on Windows')
    out = _Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(_blob(raw)), None, None, None, None, 0,
                                                     ctypes.byref(out)):
        raise OSError('could not decrypt the Nexus key')
    try:
        return ctypes.string_at(out.pbData, out.cbData).decode('utf-8')
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)
