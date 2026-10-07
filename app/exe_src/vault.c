/* Vault Launcher.exe - starts Vault Launcher from the folder it sits in.
 *
 * Python already set up (%LOCALAPPDATA%\VaultLauncher\python\pythonw.exe): starts
 *   pythonw "<this folder>\app\run.py" launcher       (no console window)
 * First run: opens a console running app\launch.cmd, which downloads Python from python.org
 * (checked against its official SHA-256) and then starts the launcher.
 *
 * Built without the C runtime or Windows SDK headers, so the few Win32 calls are declared here.
 */
typedef unsigned short WCHAR;
typedef unsigned long DWORD;
typedef int BOOL;
typedef void *HANDLE;

typedef struct {
    DWORD cb; WCHAR *lpReserved; WCHAR *lpDesktop; WCHAR *lpTitle;
    DWORD dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
    unsigned short wShowWindow, cbReserved2; unsigned char *lpReserved2;
    HANDLE hStdInput, hStdOutput, hStdError;
} STARTUPINFOW;
typedef struct { HANDLE hProcess, hThread; DWORD dwProcessId, dwThreadId; } PROCESS_INFORMATION;

__declspec(dllimport) DWORD __stdcall GetModuleFileNameW(HANDLE, WCHAR *, DWORD);
__declspec(dllimport) DWORD __stdcall GetEnvironmentVariableW(const WCHAR *, WCHAR *, DWORD);
__declspec(dllimport) DWORD __stdcall GetFileAttributesW(const WCHAR *);
__declspec(dllimport) BOOL __stdcall CreateDirectoryW(const WCHAR *, void *);
__declspec(dllimport) BOOL __stdcall CreateProcessW(const WCHAR *, WCHAR *, void *, void *, BOOL, DWORD, void *,
                                                    const WCHAR *, STARTUPINFOW *, PROCESS_INFORMATION *);
__declspec(dllimport) BOOL __stdcall CloseHandle(HANDLE);
__declspec(dllimport) void __stdcall ExitProcess(unsigned);
__declspec(dllimport) int __stdcall MessageBoxW(HANDLE, const WCHAR *, const WCHAR *, unsigned);

#define INVALID_ATTR 0xFFFFFFFFu
#define ATTR_DIRECTORY 0x10u
#define CREATE_NEW_CONSOLE 0x10u
#define CREATE_UNICODE_ENVIRONMENT 0x400u
#define MB_ICONWARNING 0x30u
#define N 2048

void *memset(void *d, int c, unsigned long long n) {
    unsigned char *p = (unsigned char *)d;
    while (n--) *p++ = (unsigned char)c;
    return d;
}

static WCHAR dir[N], data[N], pyw[N], run[N], cmdline[4 * N], cmdexe[N], sysroot[N];

static unsigned len(const WCHAR *s) { unsigned n = 0; while (s[n]) n++; return n; }

static void cat(WCHAR *d, const WCHAR *s) {
    unsigned n = len(d), i = 0;
    while (s[i] && n + 1 < 4 * N) d[n++] = s[i++];
    d[n] = 0;
}

static void cpy(WCHAR *d, const WCHAR *s) { d[0] = 0; cat(d, s); }

static int is_file(const WCHAR *p) {
    DWORD a = GetFileAttributesW(p);
    return a != INVALID_ATTR && !(a & ATTR_DIRECTORY);
}

static int start(const WCHAR *exe, WCHAR *line, const WCHAR *cwd, DWORD flags) {
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    memset(&si, 0, sizeof si);
    memset(&pi, 0, sizeof pi);
    si.cb = sizeof si;
    if (!CreateProcessW(exe, line, 0, 0, 0, flags | CREATE_UNICODE_ENVIRONMENT, 0, cwd, &si, &pi)) return 0;
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 1;
}

void start_main(void) {
    unsigned n = GetModuleFileNameW(0, dir, N);
    while (n && dir[n - 1] != '\\') n--;          /* keep the trailing backslash */
    dir[n] = 0;

    cpy(run, dir); cat(run, L"app\\run.py");
    if (!is_file(run)) {
        MessageBoxW(0, L"Vault Launcher.exe needs the app folder that came with it.\n\n"
                       L"Extract the whole zip (right-click it > Extract All) and open Vault Launcher.exe "
                       L"from the extracted folder.", L"Vault Launcher", MB_ICONWARNING);
        ExitProcess(1);
    }

    data[0] = 0;
    if (!GetEnvironmentVariableW(L"LOCALAPPDATA", data, N)) ExitProcess(1);
    cat(data, L"\\VaultLauncher");
    CreateDirectoryW(data, 0);
    cpy(pyw, data); cat(pyw, L"\\python\\pythonw.exe");

    if (is_file(pyw)) {
        cpy(cmdline, L"\""); cat(cmdline, pyw); cat(cmdline, L"\" \""); cat(cmdline, run); cat(cmdline, L"\" launcher");
        if (start(pyw, cmdline, data, 0)) ExitProcess(0);
    }

    /* First run: the console shows the one-time Python download. */
    sysroot[0] = 0;
    if (!GetEnvironmentVariableW(L"SystemRoot", sysroot, N)) cpy(sysroot, L"C:\\Windows");
    cpy(cmdexe, sysroot); cat(cmdexe, L"\\System32\\cmd.exe");
    cpy(cmdline, L"cmd.exe /d /s /c \"title Vault Launcher & \"");
    cat(cmdline, dir); cat(cmdline, L"app\\launch.cmd\" launcher || pause\"");
    if (!start(cmdexe, cmdline, data, CREATE_NEW_CONSOLE)) {
        MessageBoxW(0, L"Windows would not start the setup (cmd.exe). Try running app\\launch.cmd from the "
                       L"extracted folder.", L"Vault Launcher", MB_ICONWARNING);
        ExitProcess(1);
    }
    ExitProcess(0);
}
