/* SPDX-License-Identifier: AGPL-3.0-only */
/*
 * stata_fast.c — Minimal C wrapper around StataSO_* libstata calls.
 *
 * Loads libstata-{edition}.{dylib,so,dll} at init and wraps the raw
 * StataSO C functions into a lean API that does ClearBuffer +
 * Execute + GetOutputBuffer in a single call.
 *
 * Platform support:
 *   macOS   — .dylib, dlopen/dlsym from libSystem
 *   Linux   — .so,   dlopen/dlsym from libdl
 *   Windows — .dll,  LoadLibrary/GetProcAddress from kernel32
 */

#include "stata_fast.h"

#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <stdint.h>

/* ------------------------------------------------------------------ */
/*  Platform abstraction — dynamic library loading                    */
/* ------------------------------------------------------------------ */

#if defined(_WIN32)

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

/* Windows: LoadLibrary / GetProcAddress / FreeLibrary */
#define DL_OPEN(name)     ((void*)LoadLibraryA(name))
#define DL_SYM(handle, n) ((void*)GetProcAddress((HMODULE)(handle), n))
#define DL_CLOSE(handle)  (FreeLibrary((HMODULE)(handle)))
#define DL_ERROR()        win32_dlerror()

/* setenv equivalent */
#define SETENV(n, v, o)   do { (void)(o); _putenv_s((n), (v)); } while(0)

#if defined(_MSC_VER) && _MSC_VER < 1900
#define snprintf _snprintf
#endif

static const char* win32_dlerror(void) {
    static char buf[256];
    DWORD err = GetLastError();
    if (err == 0) return "";
    LPWSTR msg = NULL;
    DWORD len = FormatMessageW(
        FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM,
        NULL, err, LANG_NEUTRAL, (LPWSTR)&msg, 0, NULL);
    if (msg) {
        int n = WideCharToMultiByte(CP_UTF8, 0, msg, (int)len,
                                     buf, (int)sizeof(buf) - 1,
                                     NULL, NULL);
        if (n > 0) buf[n] = '\0';
        LocalFree(msg);
    } else {
        (void)snprintf(buf, sizeof(buf), "Windows error %lu",
                       (unsigned long)err);
    }
    return buf;
}

#else
/* --- POSIX (macOS / Linux): dlopen / dlsym / dlclose --- */
#include <dlfcn.h>

#define DL_OPEN(name)     dlopen(name, RTLD_NOW | RTLD_GLOBAL)
#define DL_SYM(handle, n) dlsym(handle, n)
#define DL_CLOSE(handle)  dlclose(handle)
#define DL_ERROR()        dlerror()

#ifdef __APPLE__
#define SETENV(n, v, o)   setenv((n), (v), (o))
#else
#define SETENV(n, v, o)   setenv((n), (v), (o))
#endif

#endif /* _WIN32 */

/* ------------------------------------------------------------------ */
/*  libstata function-pointer types                                   */
/* ------------------------------------------------------------------ */
typedef int  (*so_main_t)(int argc, char** argv);
typedef int  (*so_exec_t)(const char* cmd, int echo);
typedef void (*so_clear_t)(void);
typedef const char* (*so_getout_t)(void);
typedef void (*so_setbreak_t)(void);
typedef void (*so_shutdown_t)(void);

/* ------------------------------------------------------------------ */
/*  Runtime context                                                    */
/* ------------------------------------------------------------------ */
struct stata_ctx {
    void*         lib_handle;      /* DL_OPEN handle                  */
    so_main_t     StataSO_Main;
    so_exec_t     StataSO_Execute;
    so_clear_t    StataSO_ClearOutputBuffer;
    so_getout_t   StataSO_GetOutputBuffer;
    so_setbreak_t StataSO_SetBreak;
    so_shutdown_t StataSO_Shutdown;

    char          errmsg[512];     /* last error message               */
    int           has_error;       /* non-zero when errmsg is set      */
};

/* ------------------------------------------------------------------ */
/*  Internal helpers                                                  */
/* ------------------------------------------------------------------ */

static void set_error(stata_ctx* ctx, const char* msg) {
    if (!ctx) return;
    ctx->has_error = 1;
    (void)snprintf(ctx->errmsg, sizeof(ctx->errmsg), "%s", msg);
}

static void clear_error(stata_ctx* ctx) {
    if (!ctx) return;
    ctx->has_error = 0;
    ctx->errmsg[0] = '\0';
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/*
 * Check if a file exists.  Returns 1 if found, 0 otherwise.
 */
static int file_exists(const char* path) {
    if (!path) return 0;
    FILE* f = fopen(path, "r");
    if (!f) return 0;
    fclose(f);
    return 1;
}

/* ------------------------------------------------------------------ */
/*  Locate libstata path                                              */
/* ------------------------------------------------------------------ */

/*
 * Build the path to the Stata shared library.
 *
 * Returns a heap-allocated string (caller must free) or NULL on error.
 */
static char* build_lib_path(const char* st_path, const char* edition) {
    if (!st_path || !edition) return NULL;

    const char* app_name = NULL;

    /* Map lowercase edition to correct app suffix */
    if (strcmp(edition, "be") == 0) app_name = "BE";
    else if (strcmp(edition, "se") == 0) app_name = "SE";
    else if (strcmp(edition, "mp") == 0) app_name = "MP";
    else return NULL;

#if defined(__APPLE__)
    /* --- macOS path ---
     * /Applications/StataNow/StataSE.app/Contents/MacOS/libstata-se.dylib
     */
    size_t needed = strlen(st_path) + 1 + 32 + 1 + strlen(app_name) + 6
                    + 1 + 8 + 1 + 8 + 1 + strlen(edition) + 6 + 1;
    char* path = malloc(needed);
    if (!path) return NULL;
    (void)snprintf(path, needed,
        "%s/Stata%s.app/Contents/MacOS/libstata-%s.dylib",
        st_path, app_name, edition);
    return path;
#elif defined(_WIN32)
    /* --- Windows paths (try multiple candidates) ---
     *
     * Common layouts:
     *   C:\Program Files\StataNow\libstata-se.dll        (StataNow)
     *   C:\Program Files\Stata18\libstata-se-x64.dll     (Stata 18, 64-bit)
     *   C:\Program Files\StataSE18\libstata-se-x64.dll   (Stata 18 SE)
     *   C:\Program Files\Stata\libstata-se.dll           (older installs)
     *
     * Override with STATA_LIB_NAME env var.
     */
    const char* lib_names[] = {
        "libstata-%s.dll",       /* StataNow / Stata 16 */
        "libstata-%s-x64.dll",   /* Stata 17 / 18       */
        NULL
    };
    const char* override = getenv("STATA_LIB_NAME");
    if (override && override[0]) {
        lib_names[0] = override;
        lib_names[1] = NULL;
    }
    char path_buffer[1024];
    for (int ni = 0; lib_names[ni] != NULL; ni++) {
        const char* fmt = lib_names[ni];
        for (int di = 0; di < 2; di++) {
            if (di == 0) {
                (void)snprintf(path_buffer, sizeof(path_buffer),
                    "%s\\", st_path);
            } else {
                (void)snprintf(path_buffer, sizeof(path_buffer),
                    "%s\\..\\distn\\win64\\", st_path);
            }
            size_t prefix_len = strlen(path_buffer);
            if (strcmp(edition, "be") == 0) {
                (void)snprintf(path_buffer + prefix_len,
                    sizeof(path_buffer) - prefix_len,
                    "libstata.dll");
            } else {
                char lib_name[128];
                (void)snprintf(lib_name, sizeof(lib_name), fmt, edition);
                (void)snprintf(path_buffer + prefix_len,
                    sizeof(path_buffer) - prefix_len,
                    "%s", lib_name);
            }
            if (file_exists(path_buffer)) {
                char* result = malloc(strlen(path_buffer) + 1);
                if (result) strcpy(result, path_buffer);
                return result;
            }
        }
    }
    /* None found — return first candidate for error message */
    (void)snprintf(path_buffer, sizeof(path_buffer),
        "%s\\libstata-%s.dll", st_path, edition);
    char* result = malloc(strlen(path_buffer) + 1);
    if (result) strcpy(result, path_buffer);
    return result;
#else
    /* --- Linux paths (try multiple candidates) ---
     *
     * Common layouts:
     *   /usr/local/stata17/libstata-se.so
     *   /usr/local/stata17/../distn/linux64/libstata-se.so
     *   /usr/local/stata17/../distn/linux.64p/libstata-se.so
     *   /usr/local/stata17/../distn/linux.64/libstata-se.so
     *   /usr/local/stata17/libstata.so  (BE edition only)
     */
    const char* subdirs[] = {
        "",                    /* st_path/libstata-se.so */
        "../distn/linux64",    /* st_path/../distn/linux64/libstata-se.so */
        "../distn/linux.64p",  /* st_path/../distn/linux.64p/libstata-se.so */
        "../distn/linux.64",   /* st_path/../distn/linux.64/libstata-se.so */
        NULL
    };
    char path_buffer[1024];
    for (int i = 0; subdirs[i] != NULL; i++) {
        if (subdirs[i][0] == '\0') {
            if (strcmp(edition, "be") == 0)
                (void)snprintf(path_buffer, sizeof(path_buffer),
                    "%s/libstata.so", st_path);
            else
                (void)snprintf(path_buffer, sizeof(path_buffer),
                    "%s/libstata-%s.so", st_path, edition);
        } else {
            if (strcmp(edition, "be") == 0)
                (void)snprintf(path_buffer, sizeof(path_buffer),
                    "%s/%s/libstata.so", st_path, subdirs[i]);
            else
                (void)snprintf(path_buffer, sizeof(path_buffer),
                    "%s/%s/libstata-%s.so", st_path, subdirs[i], edition);
        }
        if (file_exists(path_buffer)) {
            char* result = malloc(strlen(path_buffer) + 1);
            if (result) strcpy(result, path_buffer);
            return result;
        }
    }
    /* None found — return first candidate for error message */
    if (strcmp(edition, "be") == 0)
        (void)snprintf(path_buffer, sizeof(path_buffer),
            "%s/libstata.so", st_path);
    else
        (void)snprintf(path_buffer, sizeof(path_buffer),
            "%s/libstata-%s.so", st_path, edition);
    char* result = malloc(strlen(path_buffer) + 1);
    if (result) strcpy(result, path_buffer);
    return result;
#endif
}

/* ------------------------------------------------------------------ */
/*  Loading: DL_OPEN + DL_SYM (no engine initialisation)              */
/* ------------------------------------------------------------------ */

stata_ctx* stata_load(const char* st_path, const char* edition) {
    if (!st_path || !edition) return NULL;

    stata_ctx* ctx = calloc(1, sizeof(stata_ctx));
    if (!ctx) return NULL;
    clear_error(ctx);

    /* 1. Locate libstata */
    char* lib_path = build_lib_path(st_path, edition);
    if (!lib_path) {
        set_error(ctx, "Failed to build libstata path");
        free(ctx);
        return NULL;
    }

    if (!file_exists(lib_path)) {
        set_error(ctx, "libstata not found at computed path");
        free(lib_path);
        free(ctx);
        return NULL;
    }

    /* 2. DL_OPEN */
    ctx->lib_handle = DL_OPEN(lib_path);
    if (!ctx->lib_handle) {
        set_error(ctx, DL_ERROR());
        free(lib_path);
        free(ctx);
        return NULL;
    }
    free(lib_path);

    /* 3. DL_SYM all functions */
    ctx->StataSO_Main            = (so_main_t)DL_SYM(ctx->lib_handle, "StataSO_Main");
    ctx->StataSO_Execute         = (so_exec_t)DL_SYM(ctx->lib_handle, "StataSO_Execute");
    ctx->StataSO_ClearOutputBuffer = (so_clear_t)DL_SYM(ctx->lib_handle, "StataSO_ClearOutputBuffer");
    ctx->StataSO_GetOutputBuffer = (so_getout_t)DL_SYM(ctx->lib_handle, "StataSO_GetOutputBuffer");
    ctx->StataSO_SetBreak        = (so_setbreak_t)DL_SYM(ctx->lib_handle, "StataSO_SetBreak");
    ctx->StataSO_Shutdown        = (so_shutdown_t)DL_SYM(ctx->lib_handle, "StataSO_Shutdown");

    if (!ctx->StataSO_Main || !ctx->StataSO_Execute) {
        set_error(ctx, "Required StataSO symbols not found in libstata");
        DL_CLOSE(ctx->lib_handle);
        free(ctx);
        return NULL;
    }

    return ctx;
}

/* ------------------------------------------------------------------ */
/*  Engine initialisation (StataSO_Main only, avoids -pyexec)          */
/* ------------------------------------------------------------------ */

int stata_init_engine(stata_ctx* ctx, int splash) {
    if (!ctx) return -1;
    if (!ctx->StataSO_Main) {
        set_error(ctx, "StataSO_Main not found (call stata_load first)");
        return -1;
    }

    /* Set SYSDIR_STATA if caller hasn't (stata_load sets it, but be safe) */
    const char* sd = getenv("SYSDIR_STATA");
    if (!sd || !sd[0]) {
        SETENV("SYSDIR_STATA", "/Applications/StataNow", 1);
    }

#define STATA_ARGV_MAX 8
#define STATA_ARGV_STR_MAX 128
    char* argv[STATA_ARGV_MAX];
    char  argv_buf[STATA_ARGV_MAX][STATA_ARGV_STR_MAX];
    int argc = 0;

    /*
     * argv layout:
     *   Without splash: ["", "-q"]   (suppress banner, ~7 ms saved)
     *   With splash:    [""]           (still need argv[0] for argc>=1)
     *
     * NOTE: We intentionally do NOT pass -pyexec.  That flag causes
     * Stata to initialise the CPython sub-interpreter immediately
     * via _python_initialize_so (~80 ms).  Our bridge never uses
     * "python:" inside Stata, so we skip it for a ~10x init speedup.
     */
    if (!splash) {
        argv_buf[argc][0] = '\0';  /* argv[0] = empty string */
        argv[argc] = argv_buf[argc];
        argc++;
        (void)snprintf(argv_buf[argc], STATA_ARGV_STR_MAX, "-q");
        argv[argc] = argv_buf[argc];
        argc++;
    } else {
        argv_buf[argc][0] = '\0';
        argv[argc] = argv_buf[argc];
        argc++;
    }

    clear_error(ctx);
    int rc = ctx->StataSO_Main(argc, argv);

    /* StataSO_Main returns -7100 on certain license conditions but
     * the engine is still usable — same behaviour as StataCorp's pystata. */
    if (rc < 0 && rc != -7100) {
        char err_buf[256];
        (void)snprintf(err_buf, sizeof(err_buf),
                       "StataSO_Main failed with rc=%d", rc);
        set_error(ctx, err_buf);
        return rc;
    }

    return 0;
}

/* ------------------------------------------------------------------ */
/*  Combined load + init (convenience wrapper)                         */
/* ------------------------------------------------------------------ */

stata_ctx* stata_init(const char* st_path, const char* edition, int splash) {
    stata_ctx* ctx = stata_load(st_path, edition);
    if (!ctx) return NULL;

    /* Set SYSDIR_STATA — required by Stata to find its system files */
    SETENV("SYSDIR_STATA", st_path, 1);

    int rc = stata_init_engine(ctx, splash);
    if (rc != 0) {
        DL_CLOSE(ctx->lib_handle);
        free(ctx);
        return NULL;
    }

    return ctx;
}

/* ------------------------------------------------------------------ */
/*  Shutdown                                                           */
/* ------------------------------------------------------------------ */

void stata_shutdown(stata_ctx* ctx) {
    if (!ctx) return;
    if (ctx->StataSO_Shutdown) {
        ctx->StataSO_Shutdown();
    }
    if (ctx->lib_handle) {
        DL_CLOSE(ctx->lib_handle);
    }
    free(ctx);
}

/* ------------------------------------------------------------------ */
/*  Execute — the hot path                                            */
/* ------------------------------------------------------------------ */

int stata_execute(stata_ctx* ctx, const char* command, int echo,
                  char** output, size_t* out_len, int* retcode) {
    if (!ctx || !command) return STATA_ERR;
    if (!ctx->StataSO_Execute) return STATA_NOT_INIT;

    clear_error(ctx);

    /* Clear the output buffer from the previous command */
    if (ctx->StataSO_ClearOutputBuffer) {
        ctx->StataSO_ClearOutputBuffer();
    }

    /* Execute */
    int rc = ctx->StataSO_Execute(command, echo);

    if (retcode) *retcode = rc;

    /* Read output buffer */
    if (output) {
        const char* raw = NULL;
        if (ctx->StataSO_GetOutputBuffer) {
            raw = ctx->StataSO_GetOutputBuffer();
        }
        if (raw && *raw) {
            size_t len = strlen(raw);
            char* copy = malloc(len + 1);
            if (!copy) {
                set_error(ctx, "Out of memory copying output");
                return STATA_NOMEM;
            }
            memcpy(copy, raw, len + 1);
            *output = copy;
            if (out_len) *out_len = len;
        } else {
            *output = NULL;
            if (out_len) *out_len = 0;
        }
    }

    return STATA_OK;
}

/* ------------------------------------------------------------------ */
/*  Output buffer helpers                                             */
/* ------------------------------------------------------------------ */

char* stata_get_output(stata_ctx* ctx) {
    if (!ctx || !ctx->StataSO_GetOutputBuffer) return NULL;
    const char* raw = ctx->StataSO_GetOutputBuffer();
    if (!raw || !*raw) return NULL;
    size_t len = strlen(raw);
    char* copy = malloc(len + 1);
    if (!copy) return NULL;
    memcpy(copy, raw, len + 1);
    return copy;
}

void stata_clear_output(stata_ctx* ctx) {
    if (!ctx || !ctx->StataSO_ClearOutputBuffer) return;
    ctx->StataSO_ClearOutputBuffer();
}

/* ------------------------------------------------------------------ */
/*  Break / interrupt                                                  */
/* ------------------------------------------------------------------ */

int stata_set_break(stata_ctx* ctx) {
    if (!ctx || !ctx->StataSO_SetBreak) return STATA_ERR;
    ctx->StataSO_SetBreak();
    return STATA_OK;
}

/* ------------------------------------------------------------------ */
/*  Pointer authentication (PAC) for arm64e                            */
/* ------------------------------------------------------------------ */

void* stata_sign_ptr(void* ptr) {
    if (!ptr) return NULL;
#if defined(__ARM_FEATURE_PAC_DEFAULT) && __ARM_FEATURE_PAC_DEFAULT
    /*
     * arm64e (ARMv8.3+ with PAC extension): sign the function pointer
     * with the function-pointer key (ASIA) and discriminator 0.
     * ptrauth.h is provided by the Clang compiler when targeting arm64e.
     */
#ifdef __has_include
#if __has_include(<ptrauth.h>)
#include <ptrauth.h>
    return ptrauth_sign_unauthenticated(ptr, ptrauth_key_function_pointer, 0);
#else
    /* Fallback: assume the pointer is already valid (e.g. pointer-authenticated
       code section running on arm64e without explicit ptrauth.h) */
    return ptr;
#endif
#else
    return ptr;
#endif
#else
    /* arm64 (non-PAC), x86_64, Windows: signing is a no-op */
    (void)ptr;
    return ptr;
#endif
}

void* stata_sign_bist(void* base, uint64_t vmaddr) {
    if (vmaddr == 0) return NULL;
    uint8_t* raw = (uint8_t*)base + vmaddr;
    return stata_sign_ptr((void*)raw);
}

/* ------------------------------------------------------------------ */
/*  Diagnostics                                                        */
/* ------------------------------------------------------------------ */

const char* stata_last_error(stata_ctx* ctx) {
    if (!ctx) return "NULL context";
    return ctx->has_error ? ctx->errmsg : "";
}

void stata_free(char* ptr) {
    free(ptr);
}
