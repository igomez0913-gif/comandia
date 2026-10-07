/* Comandia.exe: abre Comandia con doble clic y SIN ventana negra.

   - Si el sistema ya está configurado (Python listo, database.url y .secret), inicia el servidor oculto,
     espera a que responda y abre el navegador. Lo que el servidor escribe queda en comandia.log.
   - Si es la primera vez (hay que preparar Python, preguntar los datos de MySQL, etc.) o algo falla,
     abre iniciar.bat en una ventana normal para que se vea lo que pasa.
   - Si Comandia ya está corriendo, solo abre el navegador.
   - Comandia.exe /detener  apaga el servidor oculto.      Comandia.exe /ventana  fuerza la ventana con detalles.

   Compilar desde Linux:  windows/build.sh   ·   desde Windows con MinGW: ver el README (sección «Comandia.exe sin ventana») */
#include <winsock2.h>
#include <windows.h>
#include <iphlpapi.h>
#include <shellapi.h>
#include <wchar.h>
#include <stdio.h>

#define PORT 8100
#define URL L"http://127.0.0.1:8100"
#define WAIT_MS 45000

static void error_box(const wchar_t *msg) {
    MessageBoxW(NULL, msg, L"Comandia", MB_OK | MB_ICONERROR);
}

static int exists(const wchar_t *path) {
    return GetFileAttributesW(path) != INVALID_FILE_ATTRIBUTES;
}

/* Primera línea de un archivo de texto (sin BOM ni saltos de línea). */
static int first_line(const wchar_t *path, wchar_t *out, int cap) {
    char buf[4096];
    DWORD n = 0;
    HANDLE h = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) return 0;
    BOOL ok = ReadFile(h, buf, sizeof buf - 1, &n, NULL);
    CloseHandle(h);
    if (!ok || n == 0) return 0;
    buf[n] = '\0';
    char *p = buf;
    if (n >= 3 && (unsigned char)p[0] == 0xEF && (unsigned char)p[1] == 0xBB && (unsigned char)p[2] == 0xBF) p += 3;
    for (char *c = p; *c; c++) if (*c == '\r' || *c == '\n') { *c = '\0'; break; }
    size_t len = strlen(p);
    while (len && (p[len - 1] == ' ' || p[len - 1] == '\t')) p[--len] = '\0';
    if (!len) return 0;
    if (!MultiByteToWideChar(CP_UTF8, 0, p, -1, out, cap) && !MultiByteToWideChar(CP_ACP, 0, p, -1, out, cap)) return 0;
    return 1;
}

static int same_file(const wchar_t *a, const wchar_t *b) {
    HANDLE ha = CreateFileW(a, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING, 0, NULL);
    HANDLE hb = CreateFileW(b, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING, 0, NULL);
    int same = 0;
    if (ha != INVALID_HANDLE_VALUE && hb != INVALID_HANDLE_VALUE) {
        DWORD sa = GetFileSize(ha, NULL), sb = GetFileSize(hb, NULL);
        if (sa == sb && sa < 65536) {
            char ba[65536], bb[65536];
            DWORD na = 0, nb = 0;
            if (ReadFile(ha, ba, sa, &na, NULL) && ReadFile(hb, bb, sb, &nb, NULL) && na == nb && memcmp(ba, bb, na) == 0) same = 1;
        }
    }
    if (ha != INVALID_HANDLE_VALUE) CloseHandle(ha);
    if (hb != INVALID_HANDLE_VALUE) CloseHandle(hb);
    return same;
}

/* ¿Hay algo escuchando en el puerto de Comandia? */
static int port_open(void) {
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) return 0;
    int open = 0;
    SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s != INVALID_SOCKET) {
        u_long nb = 1;
        ioctlsocket(s, FIONBIO, &nb);
        struct sockaddr_in addr;
        ZeroMemory(&addr, sizeof addr);
        addr.sin_family = AF_INET;
        addr.sin_port = htons(PORT);
        addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        connect(s, (struct sockaddr *)&addr, sizeof addr);
        fd_set w, e;
        FD_ZERO(&w); FD_ZERO(&e);
        FD_SET(s, &w); FD_SET(s, &e);
        struct timeval tv = {0, 400000};
        if (select(0, NULL, &w, &e, &tv) > 0 && FD_ISSET(s, &w) && !FD_ISSET(s, &e)) open = 1;
        closesocket(s);
    }
    WSACleanup();
    return open;
}

static void open_browser(void) {
    ShellExecuteW(NULL, L"open", URL, NULL, NULL, SW_SHOWNORMAL);
}

/* Espera a que el servidor responda (o a que el proceso muera). 1 = listo. */
static int wait_for_server(HANDLE process) {
    DWORD start = GetTickCount();
    while (GetTickCount() - start < WAIT_MS) {
        if (port_open()) return 1;
        if (process && WaitForSingleObject(process, 0) == WAIT_OBJECT_0) return 0;
        Sleep(400);
    }
    return 0;
}

/* iniciar.bat en una ventana normal: primera vez, errores o /ventana. */
static int run_visible(const wchar_t *folder) {
    wchar_t bat[MAX_PATH + 32], cmdline[MAX_PATH * 2];
    _snwprintf(bat, sizeof bat / sizeof bat[0], L"%ls\\iniciar.bat", folder);
    if (!exists(bat)) {
        error_box(L"No encontré iniciar.bat junto a Comandia.exe.\n\n"
                  L"Comandia.exe debe estar dentro de la carpeta de Comandia (por ejemplo C:\\Comandia), "
                  L"junto a iniciar.bat y las carpetas app y static.\n\n"
                  L"Para tenerlo en el escritorio, crea un acceso directo en lugar de mover el archivo.");
        return 1;
    }
    /* cmd /c ""ruta con espacios\iniciar.bat"" */
    _snwprintf(cmdline, sizeof cmdline / sizeof cmdline[0], L"cmd.exe /c \"\"%ls\"\"", bat);
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof si);
    si.cb = sizeof si;
    ZeroMemory(&pi, sizeof pi);
    if (!CreateProcessW(NULL, cmdline, NULL, NULL, FALSE, CREATE_NEW_CONSOLE, NULL, folder, &si, &pi)) {
        error_box(L"No se pudo abrir iniciar.bat. Prueba a ejecutarlo con doble clic directamente.");
        return 1;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}

/* ¿Está todo listo para iniciar sin preguntar nada? Devuelve la ruta de Python y carga el entorno. */
static int ready(const wchar_t *folder, wchar_t *py, int pycap) {
    wchar_t path[MAX_PATH + 40], req[MAX_PATH + 40], value[2048];
    _snwprintf(py, pycap, L"%ls\\python\\python.exe", folder);
    if (!exists(py)) {
        /* Instalación normal: entorno .venv con las librerías al día respecto a requirements.txt */
        _snwprintf(py, pycap, L"%ls\\.venv\\Scripts\\python.exe", folder);
        if (!exists(py)) return 0;
        _snwprintf(path, sizeof path / sizeof path[0], L"%ls\\.venv\\requirements.instalado", folder);
        _snwprintf(req, sizeof req / sizeof req[0], L"%ls\\requirements.txt", folder);
        if (!same_file(req, path)) return 0;
    }
    _snwprintf(path, sizeof path / sizeof path[0], L"%ls\\database.url", folder);
    if (!first_line(path, value, 2048)) return 0;
    SetEnvironmentVariableW(L"DATABASE_URL", value);
    _snwprintf(path, sizeof path / sizeof path[0], L"%ls\\.secret", folder);
    if (!first_line(path, value, 2048) || wcslen(value) < 32) return 0;
    SetEnvironmentVariableW(L"COMANDIA_SECRET", value);
    SetEnvironmentVariableW(L"PYTHONUNBUFFERED", L"1");
    SetEnvironmentVariableW(L"PYTHONUTF8", L"1");
    return 1;
}

/* Inicia el servidor sin ventana; lo que escribe va a comandia.log. */
static int start_hidden(const wchar_t *folder, const wchar_t *py, PROCESS_INFORMATION *pi) {
    wchar_t logpath[MAX_PATH + 24], cmdline[MAX_PATH * 3];
    _snwprintf(logpath, sizeof logpath / sizeof logpath[0], L"%ls\\comandia.log", folder);
    SECURITY_ATTRIBUTES sa = {sizeof sa, NULL, TRUE};
    DWORD mode = OPEN_ALWAYS;
    WIN32_FILE_ATTRIBUTE_DATA info;
    if (GetFileAttributesExW(logpath, GetFileExInfoStandard, &info) && info.nFileSizeLow > 2 * 1024 * 1024) mode = CREATE_ALWAYS; /* el registro no crece sin límite */
    HANDLE log = CreateFileW(logpath, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, &sa, mode, FILE_ATTRIBUTE_NORMAL, NULL);
    HANDLE nul = CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &sa, OPEN_EXISTING, 0, NULL);
    if (log == INVALID_HANDLE_VALUE || nul == INVALID_HANDLE_VALUE) {
        if (log != INVALID_HANDLE_VALUE) CloseHandle(log);
        if (nul != INVALID_HANDLE_VALUE) CloseHandle(nul);
        return 0;
    }
    SYSTEMTIME t;
    GetLocalTime(&t);
    char stamp[96];
    DWORD wrote;
    int len = _snprintf(stamp, sizeof stamp, "\r\n=== Comandia iniciado %04d-%02d-%02d %02d:%02d:%02d ===\r\n", t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond);
    WriteFile(log, stamp, len, &wrote, NULL);
    _snwprintf(cmdline, sizeof cmdline / sizeof cmdline[0],
               L"\"%ls\" -m uvicorn app.main:app --app-dir . --host 127.0.0.1 --port %d", py, PORT);
    STARTUPINFOW si;
    ZeroMemory(&si, sizeof si);
    si.cb = sizeof si;
    si.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    si.hStdInput = nul;
    si.hStdOutput = log;
    si.hStdError = log;
    ZeroMemory(pi, sizeof *pi);
    BOOL ok = CreateProcessW(NULL, cmdline, NULL, NULL, TRUE, CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP, NULL, folder, &si, pi);
    CloseHandle(log);
    CloseHandle(nul);
    return ok ? 1 : 0;
}

/* Apaga el servidor que escucha en el puerto de Comandia. 1 = se detuvo, 0 = no estaba corriendo, -1 = error. */
static int stop_server(void) {
    DWORD size = 0;
    GetExtendedTcpTable(NULL, &size, FALSE, AF_INET, TCP_TABLE_OWNER_PID_LISTENER, 0);
    if (!size) return 0;
    MIB_TCPTABLE_OWNER_PID *table = (MIB_TCPTABLE_OWNER_PID *)HeapAlloc(GetProcessHeap(), 0, size);
    if (!table) return -1;
    int result = 0;
    if (GetExtendedTcpTable(table, &size, FALSE, AF_INET, TCP_TABLE_OWNER_PID_LISTENER, 0) == NO_ERROR) {
        for (DWORD i = 0; i < table->dwNumEntries; i++) {
            if (ntohs((u_short)table->table[i].dwLocalPort) != PORT) continue;
            DWORD pid = table->table[i].dwOwningPid;
            if (!pid) continue;
            HANDLE h = OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
            if (!h) { result = -1; continue; }
            /* Solo se cierra si es Python (el servidor de Comandia): nunca otro programa que use ese puerto. */
            wchar_t image[MAX_PATH];
            DWORD len = MAX_PATH;
            if (!QueryFullProcessImageNameW(h, 0, image, &len) || len < 10 || _wcsicmp(image + len - 10, L"python.exe") != 0) {
                CloseHandle(h);
                result = -1;
                continue;
            }
            if (TerminateProcess(h, 0)) { WaitForSingleObject(h, 5000); if (result == 0) result = 1; } else result = -1;
            CloseHandle(h);
        }
    }
    HeapFree(GetProcessHeap(), 0, table);
    return result;
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR args, int show) {
    (void)inst; (void)prev; (void)show;
    wchar_t folder[MAX_PATH], py[MAX_PATH + 40];
    DWORD n = GetModuleFileNameW(NULL, folder, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) {
        error_box(L"No pude saber en qué carpeta está Comandia.exe.");
        return 1;
    }
    wchar_t *slash = wcsrchr(folder, L'\\');
    if (slash) *slash = L'\0';
    const wchar_t *a = args ? args : L"";

    if (wcsstr(a, L"/detener")) {
        int r = stop_server();
        MessageBoxW(NULL, r > 0 ? L"Comandia se detuvo. Para volver a usarlo, abre Comandia.exe."
                          : r == 0 ? L"Comandia no estaba corriendo."
                                   : L"No se pudo detener Comandia. Ciérralo desde el Administrador de tareas (python.exe).",
                    L"Comandia", MB_OK | (r < 0 ? MB_ICONWARNING : MB_ICONINFORMATION));
        return r < 0 ? 1 : 0;
    }
    if (wcsstr(a, L"/ventana")) return run_visible(folder);

    /* Un solo lanzador a la vez: si se hace doble clic dos veces, el segundo espera y abre el navegador. */
    HANDLE mutex = CreateMutexW(NULL, TRUE, L"Local\\ComandiaLauncher");
    if (mutex && GetLastError() == ERROR_ALREADY_EXISTS) {
        if (wait_for_server(NULL)) open_browser();
        return 0;
    }
    if (port_open()) {  /* ya está corriendo: solo abrir el navegador */
        open_browser();
        return 0;
    }
    if (ready(folder, py, sizeof py / sizeof py[0])) {
        PROCESS_INFORMATION pi;
        if (start_hidden(folder, py, &pi)) {
            if (wait_for_server(pi.hProcess)) {
                open_browser();
                CloseHandle(pi.hThread);
                CloseHandle(pi.hProcess);
                return 0;
            }
            if (WaitForSingleObject(pi.hProcess, 0) != WAIT_OBJECT_0) TerminateProcess(pi.hProcess, 1);
            CloseHandle(pi.hThread);
            CloseHandle(pi.hProcess);
            MessageBoxW(NULL, L"Comandia no pudo iniciar en segundo plano. Se abrirá una ventana con el detalle del problema.\n\n"
                              L"(Lo que pasó también quedó en el archivo comandia.log.)", L"Comandia", MB_OK | MB_ICONWARNING);
        }
    }
    return run_visible(folder);
}
