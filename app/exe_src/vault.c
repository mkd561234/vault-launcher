/* Vault Launcher.exe - Vault Launcher's own window.
 *
 * 1. Finds app\run.py next to this exe and the private Python in %LOCALAPPDATA%\VaultLauncher.
 *    First run (no Python yet): a console runs app\launch.cmd setup, which downloads Python from
 *    python.org and checks it against the official SHA-256.
 * 2. Starts the launcher's background process (pythonw run.py launcher --no-window --url-file F),
 *    which writes the address of its page to F (or the address of a launcher that is already open).
 * 3. Opens a normal Windows window and shows that page in it with the Edge WebView2 engine that
 *    ships with Windows. If WebView2 can't be used, the background process opens the page in a
 *    browser app window instead (the old way).
 *
 * Built without the C runtime or Windows SDK headers, so the Win32 and WebView2 (COM) pieces it
 * uses are declared here. WebView2 is started through EmbeddedBrowserWebView.dll from the installed
 * runtime, the same entry point Microsoft's WebView2Loader.dll uses.
 */
typedef unsigned short WCHAR;
typedef unsigned long DWORD;
typedef unsigned int UINT;
typedef int BOOL;
typedef long HRESULT;
typedef long LONG;
typedef unsigned long ULONG;
typedef void *HANDLE;
typedef void *HWND;
typedef void *HINSTANCE;
typedef unsigned long long WPARAM;
typedef long long LPARAM;
typedef long long LRESULT;
typedef unsigned long long SIZE_T;

typedef struct { LONG left, top, right, bottom; } RECT;
typedef struct { HWND hwnd; UINT message; WPARAM wParam; LPARAM lParam; DWORD time; LONG x, y; DWORD priv; } MSG;
typedef LRESULT (*WNDPROC)(HWND, UINT, WPARAM, LPARAM);
typedef struct {
    UINT cbSize, style; WNDPROC lpfnWndProc; int cbClsExtra, cbWndExtra; HINSTANCE hInstance;
    HANDLE hIcon, hCursor, hbrBackground; const WCHAR *lpszMenuName, *lpszClassName; HANDLE hIconSm;
} WNDCLASSEXW;
typedef struct {
    DWORD cb; WCHAR *lpReserved; WCHAR *lpDesktop; WCHAR *lpTitle;
    DWORD dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
    unsigned short wShowWindow, cbReserved2; unsigned char *lpReserved2;
    HANDLE hStdInput, hStdOutput, hStdError;
} STARTUPINFOW;
typedef struct { HANDLE hProcess, hThread; DWORD dwProcessId, dwThreadId; } PROCESS_INFORMATION;
typedef struct { DWORD dwFileAttributes; DWORD c1, c2, a1, a2, w1, w2, sizeHigh, sizeLow, r0, r1;
                 WCHAR cFileName[260]; WCHAR cAlternateFileName[14]; DWORD x1, x2; unsigned short x3; } WIN32_FIND_DATAW;

#define IMPORT __declspec(dllimport)
IMPORT DWORD GetModuleFileNameW(HANDLE, WCHAR *, DWORD);
IMPORT HINSTANCE GetModuleHandleW(const WCHAR *);
IMPORT DWORD GetEnvironmentVariableW(const WCHAR *, WCHAR *, DWORD);
IMPORT DWORD GetFileAttributesW(const WCHAR *);
IMPORT BOOL CreateDirectoryW(const WCHAR *, void *);
IMPORT BOOL DeleteFileW(const WCHAR *);
IMPORT BOOL CreateProcessW(const WCHAR *, WCHAR *, void *, void *, BOOL, DWORD, void *, const WCHAR *,
                           STARTUPINFOW *, PROCESS_INFORMATION *);
IMPORT DWORD WaitForSingleObject(HANDLE, DWORD);
IMPORT BOOL GetExitCodeProcess(HANDLE, DWORD *);
IMPORT BOOL CloseHandle(HANDLE);
IMPORT void ExitProcess(UINT);
IMPORT void Sleep(DWORD);
IMPORT HANDLE CreateFileW(const WCHAR *, DWORD, DWORD, void *, DWORD, DWORD, HANDLE);
IMPORT BOOL ReadFile(HANDLE, void *, DWORD, DWORD *, void *);
IMPORT HANDLE LoadLibraryW(const WCHAR *);
IMPORT void *GetProcAddress(HANDLE, const char *);
IMPORT HANDLE FindFirstFileW(const WCHAR *, WIN32_FIND_DATAW *);
IMPORT BOOL FindNextFileW(HANDLE, WIN32_FIND_DATAW *);
IMPORT BOOL FindClose(HANDLE);
IMPORT DWORD GetTickCount(void);

IMPORT int MessageBoxW(HWND, const WCHAR *, const WCHAR *, UINT);
IMPORT unsigned short RegisterClassExW(const WNDCLASSEXW *);
IMPORT HWND CreateWindowExW(DWORD, const WCHAR *, const WCHAR *, DWORD, int, int, int, int, HWND, HANDLE,
                            HINSTANCE, void *);
IMPORT LRESULT DefWindowProcW(HWND, UINT, WPARAM, LPARAM);
IMPORT BOOL ShowWindow(HWND, int);
IMPORT BOOL UpdateWindow(HWND);
IMPORT BOOL GetMessageW(MSG *, HWND, UINT, UINT);
IMPORT BOOL TranslateMessage(const MSG *);
IMPORT LRESULT DispatchMessageW(const MSG *);
IMPORT void PostQuitMessage(int);
IMPORT BOOL GetClientRect(HWND, RECT *);
IMPORT HANDLE LoadImageW(HINSTANCE, const WCHAR *, UINT, int, int, UINT);
IMPORT HANDLE LoadCursorW(HINSTANCE, const WCHAR *);
IMPORT UINT GetDpiForSystem(void);
IMPORT unsigned long long SetTimer(HWND, unsigned long long, UINT, void *);
IMPORT BOOL KillTimer(HWND, unsigned long long);
IMPORT HWND GetForegroundWindow(void);
IMPORT BOOL AllowSetForegroundWindow(DWORD);
IMPORT BOOL DestroyWindow(HWND);
IMPORT BOOL SetForegroundWindow(HWND);
IMPORT int GetSystemMetrics(int);
IMPORT BOOL PostMessageW(HWND, UINT, WPARAM, LPARAM);

IMPORT HANDLE CreateSolidBrush(DWORD);
IMPORT HRESULT CoInitializeEx(void *, DWORD);
IMPORT HRESULT DwmSetWindowAttribute(HWND, DWORD, const void *, DWORD);
IMPORT LONG RegGetValueW(HANDLE, const WCHAR *, const WCHAR *, DWORD, DWORD *, void *, DWORD *);

#define INVALID_ATTR 0xFFFFFFFFu
#define CREATE_NEW_CONSOLE 0x10u
#define CREATE_UNICODE_ENVIRONMENT 0x400u
#define MB_ICONWARNING 0x30u
#define WS_OVERLAPPEDWINDOW 0x00CF0000u
#define WM_DESTROY 0x0002
#define WM_SIZE 0x0005
#define WM_TIMER 0x0113
#define WM_CLOSE 0x0010
#define WM_APP_FALLBACK (0x8000 + 1)
#define N 2048

void *memset(void *d, int c, SIZE_T n) {
    unsigned char *p = (unsigned char *)d;
    while (n--) *p++ = (unsigned char)c;
    return d;
}
void *memcpy(void *d, const void *s, SIZE_T n) {
    unsigned char *a = (unsigned char *)d; const unsigned char *b = (const unsigned char *)s;
    while (n--) *a++ = *b++;
    return d;
}

static WCHAR dir[N], data[N], pyw[N], run[N], cmdline[4 * N], cmdexe[N], sysroot[N], urlfile[N], url[N],
             udf[N], dll[N], tmp[N];
static HWND g_hwnd;
static void *g_controller;       /* ICoreWebView2Controller* */
static int g_shown;              /* the page is up in our window */
static HINSTANCE g_inst;

static unsigned len(const WCHAR *s) { unsigned n = 0; while (s[n]) n++; return n; }
static void cat(WCHAR *d, const WCHAR *s) {
    unsigned n = len(d), i = 0;
    while (s[i] && n + 1 < N) d[n++] = s[i++];
    d[n] = 0;
}
static void cpy(WCHAR *d, const WCHAR *s) { d[0] = 0; cat(d, s); }
static int exists(const WCHAR *p) { return GetFileAttributesW(p) != INVALID_ATTR; }
static int is_dir(const WCHAR *p) { DWORD a = GetFileAttributesW(p); return a != INVALID_ATTR && (a & 0x10); }

static HANDLE start(const WCHAR *exe, WCHAR *line, const WCHAR *cwd, DWORD flags) {
    STARTUPINFOW si; PROCESS_INFORMATION pi;
    memset(&si, 0, sizeof si); memset(&pi, 0, sizeof pi);
    si.cb = sizeof si;
    if (!CreateProcessW(exe, line, 0, 0, 0, flags | CREATE_UNICODE_ENVIRONMENT, 0, cwd, &si, &pi)) return 0;
    CloseHandle(pi.hThread);
    return pi.hProcess;
}

static void warn(const WCHAR *text) { MessageBoxW(0, text, L"Vault Launcher", MB_ICONWARNING); }

/* pythonw "<run.py>" launcher [extra] */
static HANDLE start_launcher(const WCHAR *extra) {
    cpy(cmdline, L"\""); cat(cmdline, pyw); cat(cmdline, L"\" \""); cat(cmdline, run); cat(cmdline, L"\" launcher");
    if (extra) { cat(cmdline, L" "); cat(cmdline, extra); }
    return start(pyw, cmdline, data, 0);
}

/* The old way: the launcher opens its page in a browser app window. */
static void fallback_to_browser(void) {
    HANDLE h = start_launcher(0);
    if (h) CloseHandle(h);
}

/* Reads the page address the launcher wrote (ASCII). */
static int read_url(void) {
    HANDLE f = CreateFileW(urlfile, 0x80000000u /*GENERIC_READ*/, 7, 0, 3 /*OPEN_EXISTING*/, 0, 0);
    char buf[1024]; DWORD got = 0; unsigned i, n = 0;
    if (f == (HANDLE)-1) return 0;
    ReadFile(f, buf, sizeof buf - 1, &got, 0);
    CloseHandle(f);
    for (i = 0; i < got && n + 1 < N; i++) {
        if (buf[i] == '\r' || buf[i] == '\n') break;
        url[n++] = (WCHAR)(unsigned char)buf[i];
    }
    url[n] = 0;
    return n > 10 && url[0] == 'h';
}

/* ---------------------------------------------------------------------------------------------
 * WebView2 runtime
 * ------------------------------------------------------------------------------------------- */
static int newest_version_dir(const WCHAR *app_dir, WCHAR *out) {
    /* app_dir\<newest version>\EBWebView\x64\EmbeddedBrowserWebView.dll */
    WIN32_FIND_DATAW fd; HANDLE h; int found = 0;
    cpy(tmp, app_dir); cat(tmp, L"\\*");
    h = FindFirstFileW(tmp, &fd);
    if (h == (HANDLE)-1) return 0;
    do {
        if ((fd.dwFileAttributes & 0x10) && fd.cFileName[0] >= '0' && fd.cFileName[0] <= '9') {
            static WCHAR cand[N];
            cpy(cand, app_dir); cat(cand, L"\\"); cat(cand, fd.cFileName); cat(cand, L"\\EBWebView\\x64\\EmbeddedBrowserWebView.dll");
            if (exists(cand)) {
                /* keep the highest version: compare numerically, part by part */
                int better = !found;
                if (found) {
                    const WCHAR *a = fd.cFileName, *b = out + len(app_dir) + 1;
                    while (*a || *b) {
                        unsigned x = 0, y = 0;
                        while (*a >= '0' && *a <= '9') x = x * 10 + (*a++ - '0');
                        while (*b >= '0' && *b <= '9') y = y * 10 + (*b++ - '0');
                        if (x != y) { better = x > y; break; }
                        if (*a == '.') a++;
                        if (*b == '.') b++;
                        if (*a == '\\' || *b == '\\') break;
                    }
                }
                if (better) { cpy(out, cand); found = 1; }
            }
        }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    return found;
}

static int find_webview_dll(void) {
    static const WCHAR *roots[] = { L"ProgramFiles(x86)", L"ProgramW6432", L"ProgramFiles", L"LOCALAPPDATA" };
    unsigned i;
    /* Registry: the runtime records its EBWebView folder for loaders. */
    static const WCHAR *key = L"SOFTWARE\\Microsoft\\EdgeUpdate\\ClientState\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}";
    HANDLE hives[2] = { (HANDLE)(long long)(int)0x80000002 /*HKLM*/, (HANDLE)(long long)(int)0x80000001 /*HKCU*/ };
    for (i = 0; i < 2; i++) {
        DWORD size = sizeof tmp;
        /* RRF_RT_REG_SZ | RRF_SUBKEY_WOW6432KEY */
        if (RegGetValueW(hives[i], key, L"EBWebView", 0x2 | 0x20000, 0, tmp, &size) == 0) {
            cpy(dll, tmp); cat(dll, L"\\x64\\EmbeddedBrowserWebView.dll");
            if (exists(dll)) return 1;
        }
    }
    for (i = 0; i < 4; i++) {
        static WCHAR base[N];
        base[0] = 0;
        if (!GetEnvironmentVariableW(roots[i], base, N)) continue;
        cat(base, L"\\Microsoft\\EdgeWebView\\Application");
        if (is_dir(base) && newest_version_dir(base, dll)) return 1;
    }
    return 0;
}

/* Minimal COM objects for the two "completed" callbacks. */
typedef struct Handler { void **vtbl; ULONG refs; } Handler;
static HRESULT h_qi(Handler *self, const void *iid, void **out) { (void)iid; *out = self; self->refs++; return 0; }
static ULONG h_addref(Handler *self) { return ++self->refs; }
static ULONG h_release(Handler *self) { return --self->refs; }

typedef HRESULT (*PutBounds)(void *, RECT);
typedef HRESULT (*GetPtr)(void *, void **);
typedef HRESULT (*Navigate)(void *, const WCHAR *);
typedef HRESULT (*CreateController)(void *, HWND, void *);
typedef ULONG (*AddRef)(void *);

static void fit(void) {
    RECT r;
    if (!g_controller) return;
    GetClientRect(g_hwnd, &r);
    ((PutBounds)(*(void ***)g_controller)[6])(g_controller, r);          /* put_Bounds */
}

static HRESULT controller_done(Handler *self, HRESULT hr, void *controller) {
    void *webview = 0;
    (void)self;
    if (hr < 0 || !controller) {
        PostMessageW(g_hwnd, WM_APP_FALLBACK, 0, 0);
        return 0;
    }
    ((AddRef)(*(void ***)controller)[1])(controller);
    g_controller = controller;
    fit();
    if (((GetPtr)(*(void ***)controller)[25])(controller, &webview) < 0 || !webview ||   /* get_CoreWebView2 */
        ((Navigate)(*(void ***)webview)[5])(webview, url) < 0) {                       /* Navigate */
        g_controller = 0;
        PostMessageW(g_hwnd, WM_APP_FALLBACK, 0, 0);
        return 0;
    }
    g_shown = 1;
    return 0;
}

static void *controller_vtbl[] = { h_qi, h_addref, h_release, controller_done };
static Handler controller_handler = { controller_vtbl, 1 };

static HRESULT environment_done(Handler *self, HRESULT hr, void *env) {
    (void)self;
    if (hr < 0 || !env ||
        ((CreateController)(*(void ***)env)[3])(env, g_hwnd, &controller_handler) < 0)  /* CreateCoreWebView2Controller */
        PostMessageW(g_hwnd, WM_APP_FALLBACK, 0, 0);
    return 0;
}

static void *environment_vtbl[] = { h_qi, h_addref, h_release, environment_done };
static Handler environment_handler = { environment_vtbl, 1 };

typedef HRESULT (*CreateEnv)(BOOL, int, const WCHAR *, void *, void *);

static int start_webview(void) {
    HANDLE lib; CreateEnv create;
    if (!find_webview_dll()) return 0;
    lib = LoadLibraryW(dll);
    if (!lib) return 0;
    create = (CreateEnv)GetProcAddress(lib, "CreateWebViewEnvironmentWithOptionsInternal");
    if (!create) return 0;
    return create(1, 0, udf, 0, &environment_handler) >= 0;
}

/* ---------------------------------------------------------------------------------------------
 * Window
 * ------------------------------------------------------------------------------------------- */
static LRESULT wndproc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_SIZE: fit(); return 0;
    case WM_TIMER:
        if (w == 1) {
            /* let the launcher's folder picker come to the front while this window is active */
            if (GetForegroundWindow() == h) AllowSetForegroundWindow((DWORD)-1);
        } else if (w == 2) {
            KillTimer(h, 2);
            if (!g_shown) { fallback_to_browser(); DestroyWindow(h); }   /* WebView2 never answered */
        }
        return 0;
    case WM_APP_FALLBACK:
        if (!g_shown) { g_shown = 1; fallback_to_browser(); DestroyWindow(h); }
        return 0;
    case WM_DESTROY: PostQuitMessage(0); return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

void start_main(void) {
    unsigned n;
    HANDLE proc;
    DWORD t0;
    MSG msg;

    n = GetModuleFileNameW(0, dir, N);
    while (n && dir[n - 1] != '\\') n--;
    dir[n] = 0;
    g_inst = GetModuleHandleW(0);

    cpy(run, dir); cat(run, L"app\\run.py");
    if (!exists(run)) {
        warn(L"Vault Launcher.exe needs the app folder that came with it.\n\n"
             L"Extract the whole zip (right-click it > Extract All) and open Vault Launcher.exe from the "
             L"extracted folder.");
        ExitProcess(1);
    }
    data[0] = 0;
    if (!GetEnvironmentVariableW(L"LOCALAPPDATA", data, N)) ExitProcess(1);
    cat(data, L"\\VaultLauncher");
    CreateDirectoryW(data, 0);
    cpy(pyw, data); cat(pyw, L"\\python\\pythonw.exe");
    cpy(tmp, dir); cat(tmp, L"Vault Launcher.exe.old");
    DeleteFileW(tmp);                                   /* left over from an update */

    if (!exists(pyw)) {
        /* First run: a console shows the one-time Python download. */
        sysroot[0] = 0;
        if (!GetEnvironmentVariableW(L"SystemRoot", sysroot, N)) cpy(sysroot, L"C:\\Windows");
        cpy(cmdexe, sysroot); cat(cmdexe, L"\\System32\\cmd.exe");
        cpy(cmdline, L"cmd.exe /d /s /c \"title Vault Launcher & \"");
        cat(cmdline, dir); cat(cmdline, L"app\\launch.cmd\" setup || pause\"");
        proc = start(cmdexe, cmdline, data, CREATE_NEW_CONSOLE);
        if (!proc) { warn(L"Windows would not start the setup (cmd.exe)."); ExitProcess(1); }
        WaitForSingleObject(proc, 0xFFFFFFFFu);
        CloseHandle(proc);
        if (!exists(pyw)) ExitProcess(1);
    }

    /* Start (or find) the launcher and get its page address. */
    cpy(urlfile, data); cat(urlfile, L"\\window-url.txt");
    DeleteFileW(urlfile);
    cpy(tmp, L"--no-window --url-file \""); cat(tmp, urlfile); cat(tmp, L"\"");
    proc = start_launcher(tmp);
    if (!proc) { warn(L"Vault Launcher could not start its Python."); ExitProcess(1); }
    t0 = GetTickCount();
    /* (the first process may hand over to a newer copy of itself, which writes the address later) */
    while (!read_url()) {
        if (GetTickCount() - t0 > 90000) {
            warn(L"Vault Launcher did not start. See %LOCALAPPDATA%\\VaultLauncher\\launcher.log.");
            ExitProcess(1);
        }
        Sleep(150);
    }
    CloseHandle(proc);

    /* Our window */
    {
        WNDCLASSEXW wc; UINT dpi = 96; int w, hgt;
        DWORD dark = 1;
        memset(&wc, 0, sizeof wc);
        wc.cbSize = sizeof wc;
        wc.lpfnWndProc = wndproc;
        wc.hInstance = g_inst;
        wc.hIcon = LoadImageW(g_inst, (const WCHAR *)1, 1 /*IMAGE_ICON*/, 0, 0, 0x40 /*LR_DEFAULTSIZE*/);
        wc.hIconSm = LoadImageW(g_inst, (const WCHAR *)1, 1, 16, 16, 0);
        wc.hCursor = LoadCursorW(0, (const WCHAR *)32512);
        wc.hbrBackground = CreateSolidBrush(0x00332720);    /* #202733-ish, matches the launcher */
        wc.lpszClassName = L"VaultLauncherWindow";
        RegisterClassExW(&wc);
        dpi = GetDpiForSystem();
        w = 1180 * (int)dpi / 96; hgt = 760 * (int)dpi / 96;
        if (w > GetSystemMetrics(0)) w = GetSystemMetrics(0);
        if (hgt > GetSystemMetrics(1) - 40) hgt = GetSystemMetrics(1) - 40;
        g_hwnd = CreateWindowExW(0, L"VaultLauncherWindow", L"Vault Launcher", WS_OVERLAPPEDWINDOW,
                                 (int)0x80000000, (int)0x80000000, w, hgt, 0, 0, g_inst, 0);
        if (!g_hwnd) { fallback_to_browser(); ExitProcess(0); }
        DwmSetWindowAttribute(g_hwnd, 20 /*DWMWA_USE_IMMERSIVE_DARK_MODE*/, &dark, sizeof dark);
        ShowWindow(g_hwnd, 1);
        UpdateWindow(g_hwnd);
        SetForegroundWindow(g_hwnd);
        SetTimer(g_hwnd, 1, 1000, 0);
    }

    cpy(udf, data); cat(udf, L"\\window");
    CoInitializeEx(0, 0x2 /*COINIT_APARTMENTTHREADED*/);
    if (!start_webview()) {
        fallback_to_browser();
        DestroyWindow(g_hwnd);
    } else {
        SetTimer(g_hwnd, 2, 20000, 0);      /* give WebView2 20 s to show up */
    }

    while (GetMessageW(&msg, 0, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    ExitProcess(0);
}
