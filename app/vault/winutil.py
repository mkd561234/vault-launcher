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


# ---- Folder picker: Windows' own "Browse for Folder" dialog, forced in front of the launcher ------
PICKER = {'hwnd': None}      # the open picker, so a second click can bring it back to the front


def _force_front(hwnd) -> None:
    """Puts a window on top and gives it the keyboard. Windows normally refuses this to a program
    that isn't in front, so the dialog briefly borrows the input of the window that is."""
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_uint]
    for f in (user32.SetForegroundWindow, user32.BringWindowToTop, user32.ShowWindow):
        f.argtypes = [wintypes.HWND] + ([ctypes.c_int] if f is user32.ShowWindow else [])
    HWND_TOPMOST, SWP_NOMOVE, SWP_NOSIZE, SWP_SHOWWINDOW, SW_RESTORE = -1, 0x2, 0x1, 0x40, 9
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetWindowPos(hwnd, wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    fg = user32.GetForegroundWindow()
    mine = kernel32.GetCurrentThreadId()
    theirs = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(theirs and theirs != mine and user32.AttachThreadInput(mine, theirs, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(mine, theirs, False)


def bring_picker_to_front() -> bool:
    if IS_WINDOWS and PICKER['hwnd']:
        _force_front(PICKER['hwnd'])
        return True
    return False


def browse_folder(title: str, start: str | None = None) -> str | None:
    """The folder the player picked, or None if they cancelled."""
    if not IS_WINDOWS:
        return None
    from ctypes import wintypes

    BFFCALLBACK = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, ctypes.c_uint, wintypes.LPARAM, wintypes.LPARAM)

    class BROWSEINFOW(ctypes.Structure):
        _fields_ = [('hwndOwner', wintypes.HWND), ('pidlRoot', ctypes.c_void_p),
                    ('pszDisplayName', wintypes.LPWSTR), ('lpszTitle', wintypes.LPCWSTR),
                    ('ulFlags', ctypes.c_uint), ('lpfn', BFFCALLBACK), ('lParam', wintypes.LPARAM),
                    ('iImage', ctypes.c_int)]

    BIF_RETURNONLYFSDIRS, BIF_EDITBOX, BIF_NEWDIALOGSTYLE, BIF_NONEWFOLDERBUTTON = 0x1, 0x10, 0x40, 0x200
    BFFM_INITIALIZED, BFFM_SETSELECTIONW = 1, 0x400 + 103
    user32, shell32, ole32 = ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.ole32
    user32.SendMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
    user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

    start_buf = ctypes.create_unicode_buffer(start or '')

    def on_event(hwnd, msg, lparam, data):
        if msg == BFFM_INITIALIZED:
            PICKER['hwnd'] = hwnd
            user32.SetWindowTextW(hwnd, f'{TITLE}: choose a folder')
            if start:
                user32.SendMessageW(hwnd, BFFM_SETSELECTIONW, 1, ctypes.cast(start_buf, ctypes.c_void_p).value)
            try:
                _force_front(hwnd)
            except Exception:  # noqa: BLE001 - a dialog behind the launcher still works
                pass
        return 0

    callback = BFFCALLBACK(on_event)
    name = ctypes.create_unicode_buffer(260)
    # No owner window: the dialog gets its own taskbar button, so it can always be found.
    info = BROWSEINFOW(hwndOwner=None, pszDisplayName=ctypes.cast(name, wintypes.LPWSTR), lpszTitle=title,
                       ulFlags=BIF_RETURNONLYFSDIRS | BIF_EDITBOX | BIF_NEWDIALOGSTYLE | BIF_NONEWFOLDERBUTTON,
                       lpfn=callback)
    ole32.OleInitialize(None)          # the resizable dialog style needs OLE on this thread
    try:
        pidl = shell32.SHBrowseForFolderW(ctypes.byref(info))
        if not pidl:
            return None
        path = ctypes.create_unicode_buffer(32768)
        ok = shell32.SHGetPathFromIDListW(pidl, path)
        ole32.CoTaskMemFree(pidl)
        return path.value if ok and path.value else None
    finally:
        PICKER['hwnd'] = None
        ole32.OleUninitialize()
