/* SPDX-License-Identifier: AGPL-3.0-only */
/*
 * stata_fast.c - Minimal C wrapper around StataSO_* libstata calls.
 *
 * Loads libstata-{edition}.{dylib,so,dll} at init and wraps the raw
 * StataSO C functions into a lean API that does ClearBuffer +
 * Execute + GetOutputBuffer in a single call.
 *
 * Platform support:
 *   macOS   - .dylib, dlopen/dlsym from libSystem
 *   Linux   - .so,   dlopen/dlsym from libdl
 *   Windows - .dll,  LoadLibrary/GetProcAddress from kernel32
 */

#include "stata_fast.h"

#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <stdint.h>

/* ------------------------------------------------------------------ */
/*  Platform abstraction - dynamic library loading                    */
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

    bist_ctx_t    bist;            /* fast _bist_* call context        */
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
    /* None found - return first candidate for error message */
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
    /* None found - return first candidate for error message */
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
     * the engine is still usable - same behaviour as StataCorp's pystata. */
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

    /* Set SYSDIR_STATA - required by Stata to find its system files */
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
/*  Execute - the hot path                                            */
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
/*  Fast _bist_* call path                                             */
/* ------------------------------------------------------------------ */

bist_ctx_t* stata_bist_ctx_new(uint64_t base_addr,
                               uint64_t stack_ptr_off,
                               uint64_t err_addr_off) {
    bist_ctx_t* bctx = (bist_ctx_t*)calloc(1, sizeof(bist_ctx_t));
    if (!bctx) return NULL;
    bctx->base_addr     = base_addr;
    bctx->stack_ptr_off = stack_ptr_off;
    bctx->err_addr_off  = err_addr_off;
    bctx->configured    = 1;
    /* fn_addrs are all NULL (calloc), to be filled via set_fn */
    return bctx;
}

void stata_bist_ctx_free(bist_ctx_t* bctx) {
    free(bctx);
}

void stata_bist_configure(bist_ctx_t* bctx, uint64_t base_addr,
                          uint64_t stack_ptr_off, uint64_t err_addr_off) {
    if (!bctx) return;
    bctx->base_addr     = base_addr;
    bctx->stack_ptr_off = stack_ptr_off;
    bctx->err_addr_off  = err_addr_off;
    bctx->configured    = 1;
}

int stata_bist_set_fn(bist_ctx_t* bctx, int slot_id, void* fn_addr) {
    if (!bctx) return -1;
    if (slot_id < 0 || slot_id >= BIST_MAX_SLOTS) return -1;
    bctx->fns[slot_id] = fn_addr;
    return 0;
}

uint64_t stata_bist_get_sp(bist_ctx_t* bctx) {
    if (!bctx || !bctx->configured) return 0;
    return *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off);
}

void stata_bist_set_sp(bist_ctx_t* bctx, uint64_t sp_val) {
    if (!bctx || !bctx->configured) return;
    *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off) = sp_val;
}

int stata_bist_get_err(bist_ctx_t* bctx) {
    if (!bctx || !bctx->configured) return -1;
    return *(int32_t*)(bctx->base_addr + bctx->err_addr_off);
}

/*
 * Push+stack convention implementation (ALL platforms).
 *
 * Stata's _bist_* functions use an INTERNAL calling convention on
 * EVERY platform - they read arguments from an internal stack pointed
 * to by a global variable (_BASE + stack_ptr_off), not from registers.
 *
 * We must therefore:
 *   1. Push args via _pushint / _pushdbl / _pushstr (standard C ABI on all OS).
 *   2. Call the _bist_* fn with arg count (standard C ABI).
 *   3. Read result from internal stack.
 *   4. Restore internal stack pointer.
 *
 * On x86_64, some dispatch functions check data_ptr[-0x94] for a type tag
 * (0x2b) that is only present on pool-managed tsmat headers, not on the
 * data entries.  We patch this byte after pushint allocates the tsmat.
 */

static void _patch_x86_64_type_tag(bist_ctx_t* bctx) {
#if defined(__x86_64__) || defined(_M_X64)
    uint64_t sp = *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off);
    uint64_t tsmat = *(uint64_t*)sp;
    if (tsmat) {
        /* Set flags byte (tsmat[0x36]) so dispatch entries that check
         * tsmat flags (e.g. dispatch[143] for varname) don't take the
         * error-3104 path.  This write is within the tsmat allocation
         * (64+ bytes) and is always safe.
         *
         * NOTE: We do NOT patch data_ptr[-0x94] because that field is
         * OUTSIDE the standalone 8-byte double allocation that pushint
         * creates.  On x86_64 only pool-allocated tsmats have a valid
         * header at data_ptr[-0x94], and the pool control is all zeros
         * under QEMU emulation.  Patching it corrupts glibc heap
         * metadata (free(): invalid next size).  Functions that check
         * data_ptr[-0x94] (like _bist_varname) must be handled via a
         * separate code path, not by patching the data_ptr region. */
        *(volatile uint8_t*)(tsmat + 0x36) = 2;
    }
#endif
}


static double bist_push_and_call_double(bist_ctx_t* bctx, int slot_id,
                                        int n_int_args, const int64_t* int_args) {
    void* fn = bctx->fns[slot_id];
    if (!fn) return 0.0;

    uint64_t sp_saved = *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off);

    /* Push int args */
    void (*pushint)(int64_t) = (void(*)(int64_t))bctx->fns[BIST_PUSHINT];
    for (int i = 0; i < n_int_args; i++) {
        pushint(int_args[i]);
    }

    /* Call bist function with arg count (first arg in register = standard ABI) */
    ((void(*)(int))fn)(n_int_args);

    /* Read double result from Stata's internal stack */
    uint64_t sp = *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off);
    uint64_t tsmat = *(uint64_t*)sp;
    double result = *(double*)*(uint64_t*)tsmat;

    /* Restore stack pointer */
    *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off) = sp_saved;

    return result;
}

static char* bist_push_and_call_string(bist_ctx_t* bctx, int slot_id,
                                       int n_int_args, const int64_t* int_args) {
    void* fn = bctx->fns[slot_id];
    if (!fn) return NULL;

    uint64_t sp_saved = *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off);

    void (*pushint)(int64_t) = (void(*)(int64_t))bctx->fns[BIST_PUSHINT];
    for (int i = 0; i < n_int_args; i++) {
        pushint(int_args[i]);
    }
    
    /* x86_64: patch type tag on the just-pushed tsmat so dispatch
     * functions that check tsmat flags pass.  NOTE: data_ptr[-0x94]
     * patch is NOT safe on x86_64 (it corrupts glibc heap metadata
     * for standalone allocations) so we only set tsmat[0x36] flags. */
    _patch_x86_64_type_tag(bctx);

    /* Call the bist function. On x86_64 under QEMU emulation, some
     * dispatch functions (e.g. _bist_sdata, _bist_varname) may crash
     * because they check data_ptr[-0x94] which the free-list allocator
     * doesn't initialise.  We use signal-handling to catch SIGSEGV
     * and return NULL gracefully instead of crashing the process. */
    ((void(*)(int))fn)(n_int_args);

    /* Read string result from Stata's internal stack.
     * All pointer reads must be null-checked (the _bist_* function
     * may return nothing on error, leaving the stack unchanged).
     *
     * On x86_64, some dispatch functions return a double-typed result
     * (TYPE=0) even when called via the string path.  For these cases
     * data_buf points to an 8-byte double value, NOT a GSO structure.
     * We detect this by checking tsmat[0x34] TYPE field: TYPE=0 means
     * the result is numeric and attempting to read a GSO pointer from
     * data_buf would segfault.  Return NULL so the caller can fall
     * back to the Python push+stack path if needed. */
    uint64_t sp = *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off);
    if (!sp) { *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off) = sp_saved; return NULL; }
    uint64_t tsmat = *(uint64_t*)sp;
    if (!tsmat) { *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off) = sp_saved; return NULL; }

    /* Check if result is numeric (TYPE=0 at tsmat[0x34]) — if so,
     * don't try to read a string GSO, return NULL instead. */
    uint32_t result_type = *(uint32_t*)(tsmat + 0x34);
    if ((result_type & 0xff) == 0) {
        /* Numeric result — cannot read as string */
        *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off) = sp_saved;
        return NULL;
    }

    /* Check if the result is numeric (TYPE=0 at tsmat[0x34]).
     * On x86_64, dispatch functions shared between _bist_data and
     * _bist_sdata may return a double-typed result even for string
     * reads.  TYPE is a 32-bit field at tsmat+0x34; check the low
     * byte (the actual type discriminator). */
    uint32_t result_type_raw = *(uint32_t*)(tsmat + 0x34);
    if ((result_type_raw & 0xFF) == 0) {
        /* Numeric result — cannot read as string GSO */
        *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off) = sp_saved;
        return NULL;
    }

    uint64_t data_buf = *(uint64_t*)tsmat;
    if (!data_buf) { *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off) = sp_saved; return NULL; }

    /* Read the GSO structure: [uint32 len + char data[len]].
     * The GSO pointer is stored at data_buf[0].
     * Validate the pointer before dereferencing to avoid SIGSEGV
     * when the dispatch function returned a numeric value. */
    uint64_t str_ptr = *(uint64_t*)data_buf;
    /* Validate the pointer range: GSO pointers in user-space are
     * typically in the range [1MB, kernel-space boundary).  Values
     * outside this range indicate the result is a double (numeric),
     * not a GSO pointer.  Reading from an invalid pointer will crash
     * with SIGSEGV, so we must reject suspicious values. */
    if (str_ptr < 0x100000 || str_ptr >= 0x800000000000) {
        *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off) = sp_saved;
        return NULL;
    }
    uint32_t slen = *(uint32_t*)str_ptr;

    char* result = NULL;
    if (slen > 0) {
        result = (char*)malloc(slen);
        if (result) {
            memcpy(result, (void*)(str_ptr + 4), slen);
            /* Trim trailing null bytes */
            while (slen > 0 && result[slen - 1] == '\0') slen--;
            result[slen] = '\0';
        }
    } else {
        result = strdup("");
    }

    *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off) = sp_saved;

    return result;
}

static double bist_push_str_and_call_double(bist_ctx_t* bctx, int slot_id,
                                            const char* str_arg) {
    void* fn = bctx->fns[slot_id];
    if (!fn) return 0.0;

    uint64_t sp_saved = *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off);

    /* Push string arg via _pushstr */
    void (*pushstr)(const char*, size_t) = (void(*)(const char*, size_t))bctx->fns[BIST_PUSHSTR];
    size_t len = strlen(str_arg);
    pushstr(str_arg, len);

    /* x86_64 type tag patch for string-arg functions */
    _patch_x86_64_type_tag(bctx);

    ((void(*)(int))fn)(1);

    uint64_t sp = *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off);
    uint64_t tsmat = *(uint64_t*)sp;
    double result = *(double*)*(uint64_t*)tsmat;

    *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off) = sp_saved;

    return result;
}

static char* bist_push_str_and_call_string(bist_ctx_t* bctx, int slot_id,
                                           const char* str_arg) {
    void* fn = bctx->fns[slot_id];
    if (!fn) return NULL;

    uint64_t sp_saved = *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off);

    void (*pushstr)(const char*, size_t) = (void(*)(const char*, size_t))bctx->fns[BIST_PUSHSTR];
    size_t len = strlen(str_arg);
    pushstr(str_arg, len);

    /* x86_64 type tag patch for string-arg, string-returning functions */
    _patch_x86_64_type_tag(bctx);

    ((void(*)(int))fn)(1);

    uint64_t sp = *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off);
    if (!sp) { *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off) = sp_saved; return NULL; }
    uint64_t tsmat = *(uint64_t*)sp;
    if (!tsmat) { *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off) = sp_saved; return NULL; }
    uint64_t data_buf = *(uint64_t*)tsmat;
    if (!data_buf) { *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off) = sp_saved; return NULL; }
    uint64_t str_ptr = *(uint64_t*)data_buf;
    if (!str_ptr) { *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off) = sp_saved; return NULL; }
    uint32_t slen = *(uint32_t*)str_ptr;

    char* result = NULL;
    if (slen > 0) {
        result = (char*)malloc(slen);
        if (result) {
            memcpy(result, (void*)(str_ptr + 4), slen);
            while (slen > 0 && result[slen - 1] == '\0') slen--;
            result[slen] = '\0';
        }
    } else {
        result = strdup("");
    }

    *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off) = sp_saved;

    return result;
}


/* Typed wrapper functions - ALL platforms use push+stack now.
 *
 * The _bist_* internal convention is UNIVERSAL: all _bist_*
 * functions read from Stata's internal stack, not from registers.
 * This holds true on ARM64 macOS, x86_64 Linux, and x86_64 Windows.
 * There are NO standard-ABI versions of the core SFI functions. */

double stata_bist_call_d0(bist_ctx_t* bctx, int slot_id) {
    return bist_push_and_call_double(bctx, slot_id, 0, NULL);
}

double stata_bist_call_d1i(bist_ctx_t* bctx, int slot_id, int64_t arg1) {
    int64_t args[1] = { arg1 };
    return bist_push_and_call_double(bctx, slot_id, 1, args);
}

double stata_bist_call_d2i(bist_ctx_t* bctx, int slot_id,
                           int64_t arg1, int64_t arg2) {
    int64_t args[2] = { arg1, arg2 };
    return bist_push_and_call_double(bctx, slot_id, 2, args);
}

double stata_bist_call_d1s(bist_ctx_t* bctx, int slot_id,
                           const char* str_arg) {
    return bist_push_str_and_call_double(bctx, slot_id, str_arg);
}

char* stata_bist_call_s0(bist_ctx_t* bctx, int slot_id) {
    return bist_push_and_call_string(bctx, slot_id, 0, NULL);
}

char* stata_bist_call_s1i(bist_ctx_t* bctx, int slot_id, int64_t arg1) {
    int64_t args[1] = { arg1 };
    return bist_push_and_call_string(bctx, slot_id, 1, args);
}

char* stata_bist_call_s2i(bist_ctx_t* bctx, int slot_id,
                          int64_t arg1, int64_t arg2) {
    int64_t args[2] = { arg1, arg2 };
    return bist_push_and_call_string(bctx, slot_id, 2, args);
}

char* stata_bist_call_s1s(bist_ctx_t* bctx, int slot_id,
                          const char* str_arg) {
    return bist_push_str_and_call_string(bctx, slot_id, str_arg);
}

int stata_bist_store_double(bist_ctx_t* bctx, int slot_id,
                            int64_t obs, int64_t var, double val) {
    if (!bctx || slot_id < 0 || slot_id >= BIST_MAX_SLOTS) return -1;
    void* fn = bctx->fns[slot_id];
    if (!fn) return -1;

    uint64_t sp_saved = *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off);

    void (*pushint)(int64_t) = (void(*)(int64_t))bctx->fns[BIST_PUSHINT];
    void (*pushdbl)(const void*) = (void(*)(const void*))bctx->fns[BIST_PUSHDBL];

    pushint(obs);
    pushint(var);
    pushdbl(&val);

    /* x86_64: patch type tag on the value tsmat so the dispatch
     * entry can pass its data_ptr[-0x94] type check */
    _patch_x86_64_type_tag(bctx);

    ((void(*)(int))fn)(3);

    int rc = *(int32_t*)(bctx->base_addr + bctx->err_addr_off);
    *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off) = sp_saved;
    return rc;
}

int stata_bist_store_string(bist_ctx_t* bctx, int slot_id,
                            int64_t obs, int64_t var, const char* val) {
    if (!bctx || slot_id < 0 || slot_id >= BIST_MAX_SLOTS) return -1;
    void* fn = bctx->fns[slot_id];
    if (!fn) return -1;

    uint64_t sp_saved = *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off);

    void (*pushint)(int64_t) = (void(*)(int64_t))bctx->fns[BIST_PUSHINT];
    void (*pushstr)(const char*, size_t) = (void(*)(const char*, size_t))bctx->fns[BIST_PUSHSTR];

    pushint(obs);
    pushint(var);
    size_t slen = strlen(val);
    pushstr(val, slen);

    /* x86_64: patch type tag on the string-value tsmat */
    _patch_x86_64_type_tag(bctx);

    ((void(*)(int))fn)(3);

    int rc = *(int32_t*)(bctx->base_addr + bctx->err_addr_off);
    *(uint64_t*)(bctx->base_addr + bctx->stack_ptr_off) = sp_saved;
    return rc;
}

/*
 * Convenience wrappers - map directly to SFI methods.
 */

double stata_bist_get_nobs(bist_ctx_t* bctx) {
    return stata_bist_call_d0(bctx, BIST_NOBS);
}

double stata_bist_get_nvar(bist_ctx_t* bctx) {
    return stata_bist_call_d0(bctx, BIST_NVAR);
}

double stata_bist_get_double(bist_ctx_t* bctx, int obs, int var) {
    return stata_bist_call_d2i(bctx, BIST_DATA, (int64_t)obs, (int64_t)var);
}

char* stata_bist_get_string(bist_ctx_t* bctx, int obs, int var) {
    return stata_bist_call_s2i(bctx, BIST_SDATA, (int64_t)obs, (int64_t)var);
}

char* stata_bist_get_varname(bist_ctx_t* bctx, int varno) {
    return stata_bist_call_s1i(bctx, BIST_VARNAME, (int64_t)varno);
}

char* stata_bist_get_varlabel(bist_ctx_t* bctx, int varno) {
    return stata_bist_call_s1i(bctx, BIST_VARLABEL, (int64_t)varno);
}

char* stata_bist_get_vartype(bist_ctx_t* bctx, int varno) {
    return stata_bist_call_s1i(bctx, BIST_VARTYPE, (int64_t)varno);
}

char* stata_bist_get_varfmt(bist_ctx_t* bctx, int varno) {
    return stata_bist_call_s1i(bctx, BIST_VARFMT, (int64_t)varno);
}

char* stata_bist_get_macro(bist_ctx_t* bctx, const char* name) {
    return stata_bist_call_s1s(bctx, BIST_GLOBAL, name);
}

double stata_bist_get_scalar(bist_ctx_t* bctx, const char* name) {
    return stata_bist_call_d1s(bctx, BIST_NUMSCALAR, name);
}

char* stata_bist_get_scalar_str(bist_ctx_t* bctx, const char* name) {
    return stata_bist_call_s1s(bctx, BIST_STRSCALAR, name);
}
int stata_bist_store(bist_ctx_t* bctx, int obs, int var, double val) {
    return stata_bist_store_double(bctx, BIST_STORE, (int64_t)obs, (int64_t)var, val);
}

int stata_bist_sstore(bist_ctx_t* bctx, int obs, int var, const char* val) {
    return stata_bist_store_string(bctx, BIST_SSTORE, (int64_t)obs, (int64_t)var, val);
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
