#include <windows.h>
#include <stdio.h>
#include <string.h>

typedef unsigned int (__stdcall *progress_cb)(const char *, int, int, const char *);
typedef int (__cdecl *freearc_extract)(progress_cb, const char *, const char *,
    const char *, const char *, const char *, const char *, const char *,
    const char *, const char *, const char *);

static unsigned int __stdcall progress(const char *message, int x, int y,
    const char *extra) {
    static int last_read_y = -1;
    static int last_write_y = -1;
    int *last_y;
    int noisy;

    if (!message || !*message)
        return 0;

    noisy = strcmp(message, "read") == 0 || strcmp(message, "write") == 0;
    last_y = strcmp(message, "read") == 0 ? &last_read_y : &last_write_y;
    /*
     * Read/write callbacks are extremely frequent. Keep enough samples to
     * prove progress, but never suppress control, filename or error events.
     * The old callback filtered only by x/y and could therefore hide the
     * final error when it reused the last progress counters.
     */
    if (!noisy || *last_y < 0 || y < *last_y ||
            (long long)y - (long long)*last_y >= 64LL * 1024 * 1024) {
        fprintf(stderr, "[FreeArc] event=%s x=%d y=%d", message, x, y);
        if (extra && *extra)
            fprintf(stderr, " extra=%s", extra);
        fputc('\n', stderr);
        fflush(stderr);
        if (noisy)
            *last_y = y;
    }
    return 0;
}

int main(int argc, char **argv) {
    HMODULE module;
    HANDLE init_mapping;
    char *init_view;
    freearc_extract extract;
    const char *args[10] = {0};
    int count;
    int i;
    int rc;

    if (argc < 3) {
        fprintf(stderr, "usage: unarc-helper.exe unarc.dll command ...\n");
        return 2;
    }

    /*
     * FitGirl's universal CLS shims expect their host (normally ISDone/Inno)
     * to publish the namespace prefix through this named shared-memory block.
     * Without it the sidecar worker tries to open unprefixed mappings and
     * displays "Can't open read file mapping!" under Wine.
     */
    init_mapping = CreateFileMappingA(INVALID_HANDLE_VALUE, NULL,
        PAGE_READWRITE, 0, 256, "Init_MapFile_");
    if (!init_mapping) {
        fprintf(stderr, "CreateFileMapping(Init_MapFile_) failed: %lu\n",
            (unsigned long)GetLastError());
        return 5;
    }
    init_view = (char *)MapViewOfFile(init_mapping, FILE_MAP_ALL_ACCESS,
        0, 0, 256);
    if (!init_view) {
        fprintf(stderr, "MapViewOfFile(Init_MapFile_) failed: %lu\n",
            (unsigned long)GetLastError());
        CloseHandle(init_mapping);
        return 6;
    }
    memset(init_view, 0, 256);
    memcpy(init_view, "Global\\", 8);

    module = LoadLibraryA(argv[1]);
    if (!module) {
        fprintf(stderr, "LoadLibrary(unarc.dll) failed: %lu\n",
            (unsigned long)GetLastError());
        UnmapViewOfFile(init_view);
        CloseHandle(init_mapping);
        return 3;
    }
    extract = (freearc_extract)GetProcAddress(module, "FreeArcExtract");
    if (!extract) {
        fprintf(stderr, "FreeArcExtract export not found\n");
        UnmapViewOfFile(init_view);
        CloseHandle(init_mapping);
        return 4;
    }
    count = argc - 2;
    if (count > 10)
        count = 10;
    for (i = 0; i < count; ++i)
        args[i] = argv[i + 2];

    rc = extract(progress, args[0], args[1], args[2], args[3], args[4],
        args[5], args[6], args[7], args[8], args[9]);
    fprintf(stderr, "[FreeArc] final rc=%d win32_error=%lu\n", rc,
        (unsigned long)GetLastError());
    fflush(stderr);
    UnmapViewOfFile(init_view);
    CloseHandle(init_mapping);
    return rc == 0 ? 0 : 1;
}
