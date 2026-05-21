/* SPDX-License-Identifier: AGPL-3.0-only */
/*
 * stata_fast.h — Minimal C wrapper around StataSO_* libstata calls.
 *
 * Loads libstata-{edition}.dylib/.so directly and exposes a lean
 * C API that bundles ClearBuffer + Execute + GetOutputBuffer into
 * a single call, eliminating Python-level overhead from the hot path.
 *
 * Thread-safety: not yet.  Use one context per thread.
 */

#ifndef STATA_FAST_H
#define STATA_FAST_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------ */
/*  Error codes                                                       */
/* ------------------------------------------------------------------ */
#define STATA_OK        0
#define STATA_ERR      -1   /* General / unspecified error           */
#define STATA_NOMEM    -2   /* Memory allocation failed              */
#define STATA_EXEC_ERR -3   /* Command execution returned non-zero   */
#define STATA_NOT_INIT -6   /* Context not initialised               */

/* ------------------------------------------------------------------ */
/*  Opaque context type                                               */
/* ------------------------------------------------------------------ */
typedef struct stata_ctx stata_ctx;

/* ------------------------------------------------------------------ */
/*  Lifecycle                                                         */
/* ------------------------------------------------------------------ */

/*
 * Initialise the Stata engine by loading libstata-{edition}.dylib/.so
 * from *st_path* and calling StataSO_Main.
 *
 *   st_path  — Stata installation root, e.g. "/Applications/StataNow".
 *   edition  — "be", "se", or "mp".
 *   splash   — non-zero ⇒ show the Stata splash banner.
 *
 * Returns an opaque handle on success, NULL on failure.
 * Call stata_last_error(NULL) to retrieve the reason.
 */
/*
 * Load libstata shared library and resolve all function pointers.
 * This does dlopen + dlsym only, no engine initialisation.
 * May be called before stata_init() to amortise the dlopen cost.
 * Returns NULL on error (see stata_last_error).
 */
stata_ctx* stata_load(const char* st_path, const char* edition);

/*
 * Initialise the Stata engine in a previously loaded context.
 * Calls StataSO_Main with -q (quiet) and no pyexec.
 * Returns 0 on success, negative on error.
 */
int stata_init_engine(stata_ctx* ctx, int splash);

/*
 * Combined load + init (convenience wrapper).  Same as before.
 */
stata_ctx* stata_init(const char* st_path, const char* edition, int splash);

/*
 * Shut down the Stata engine and free all resources.
 *
 * Safe to call with a NULL ctx or after a previous shutdown.
 */
void stata_shutdown(stata_ctx* ctx);

/* ------------------------------------------------------------------ */
/*  Command execution — one call does ClearBuffer + Execute + GetOut  */
/* ------------------------------------------------------------------ */

/*
 * Execute a single Stata command.
 *
 * Internally calls StataSO_ClearOutputBuffer, then StataSO_Execute,
 * then StataSO_GetOutputBuffer.  The output buffer is returned as a
 * NUL-terminated malloc'd string; *out_len is set to its length
 * (excluding NUL).  The caller must free *output with stata_free().
 *
 *   command  — Stata command(s).  Multi-line commands are handled by
 *              writing to a temp do-file and using include (same as
 *              the Python _core.execute fast path).
 *   echo     — non-zero ⇒ echo the command in the output.
 *   output   — on success, *output receives a malloc'd string.
 *              May be NULL if the caller does not need output.
 *   out_len  — if non-NULL, filled with output string length.
 *   retcode  — if non-NULL, filled with Stata's return code (0=OK).
 *
 * Returns STATA_OK on success (even if retcode != 0 — the command
 * executed, Stata just signalled an error).  Returns negative on
 * internal failure (e.g. libstata not loaded).
 */
int stata_execute(stata_ctx* ctx, const char* command, int echo,
                  char** output, size_t* out_len, int* retcode);

/* ------------------------------------------------------------------ */
/*  Output buffer helpers                                             */
/* ------------------------------------------------------------------ */

/*
 * Drain and return the current output buffer (malloc'd).
 * Caller must free with stata_free().  Returns NULL if empty.
 */
char* stata_get_output(stata_ctx* ctx);

/*
 * Clear the output buffer without reading it.
 */
void stata_clear_output(stata_ctx* ctx);

/* ------------------------------------------------------------------ */
/*  Break / interrupt                                                 */
/* ------------------------------------------------------------------ */

/*
 * Interrupt a running Stata command (calls StataSO_SetBreak).
 * Returns STATA_OK on success, negative on error.
 */
int stata_set_break(stata_ctx* ctx);

/* ------------------------------------------------------------------ */
/*  Pointer authentication (PAC) for arm64e                           */
/* ------------------------------------------------------------------ */

/*
 * Sign an unauthenticated function pointer for arm64e PAC.
 *
 * On arm64e: uses ptrauth_sign_unauthenticated with the function-pointer
 * key (ptrauth_key_function_pointer / ASIA) and discriminator 0.
 *
 * On arm64 (non-arm64e), x86_64, and Windows: returns ptr unchanged.
 *
 * Usage:
 *   void* raw = (void*)(base + vmaddr);
 *   void* signed_fn = stata_sign_ptr(raw);
 *   // now safe to call through signed_fn via a properly typed fn ptr
 */
void* stata_sign_ptr(void* ptr);

/*
 * Convenience: compute base + vmaddr and sign the result.
 * Returns NULL if vmaddr is 0.
 */
void* stata_sign_bist(void* base, uint64_t vmaddr);

/* ------------------------------------------------------------------ */
/*  Fast _bist_* call path (ARM64 push+stack convention)             */
/*                                                                    */
/*  All symbol addresses are resolved by the Python manifest system   */
/*  at runtime (cross-version safe).  The C extension receives the   */
/*  pre-resolved addresses once at init and caches them.             */
/*                                                                    */
/*  On ARM64, _bist_* functions DO NOT use standard AAPCS64 ABI.     */
/*  Instead they use Stata's proprietary push+stack convention:      */
/*    1. Push args via _pushint / _pushdbl / _pushstr                 */
/*    2. Call _bist_* as void(*)(int) with w0 = arg count            */
/*    3. Read result from Stata's internal stack (tsmat structure)   */
/*    4. Restore stack pointer                                        */
/*  On x86_64 / Windows, _bist_* use standard SysV/Microsoft ABI     */
/*  and the direct CFUNCTYPE path (via Python) is adequate.           */
/* ------------------------------------------------------------------ */

/* Max number of cached _bist_* function pointer slots */
#define BIST_MAX_SLOTS 64

/* Pre-defined slot IDs for common _bist_* functions */
/* Double-returning */
#define BIST_NOBS       0   /* _bist_nobs (0 int args)                    */
#define BIST_NVAR       1   /* _bist_nvar (0 int args)                    */
#define BIST_DATA       2   /* _bist_data (2 int args: obs, var)          */
#define BIST_NUMSCALAR  3   /* _bist_numscalar (1 str arg: name)          */
/* String-returning */
#define BIST_VARNAME    4   /* _bist_varname (1 int arg: varno)           */
#define BIST_VARTYPE    5   /* _bist_vartype (1 int arg: varno)           */
#define BIST_VARLABEL   6   /* _bist_varlabel (1 int arg: varno)          */
#define BIST_VARFMT     7   /* _bist_varformat (1 int arg: varno)         */
#define BIST_SDATA      8   /* _bist_sdata (2 int args: obs, var)         */
#define BIST_GLOBAL     9   /* _bist_global (1 str arg: name)             */
#define BIST_STRSCALAR 10   /* _bist_strscalar (1 str arg: name)          */
/* Store operations */
#define BIST_STORE     11   /* _bist_store (3 pushes: obs, var, double)   */
#define BIST_SSTORE    12   /* _bist_sstore (3 pushes: obs, var, str)     */
/* ValueLabel */
#define BIST_VLLOAD    13   /* _bist_vlload                               */
/* Push helper functions */
#define BIST_PUSHINT   30
#define BIST_PUSHDBL   31
#define BIST_PUSHSTR   32
/* Other internal helpers */
#define BIST_STSCALSAVE   40
#define BIST_XGSO_NEWCP   41
#define BIST_PUT_XGSO     42

/*
 * Fast _bist_* call context.
 * Stores pre-resolved function addresses and stack/error offsets
 * passed from the Python manifest system at init.
 */
typedef struct {
    uint64_t base_addr;          /* libstata load address                      */
    uint64_t stack_ptr_off;      /* stack pointer offset from base            */
    uint64_t err_addr_off;       /* error address offset from base            */
    void*    fns[BIST_MAX_SLOTS];/* function pointers indexed by slot ID      */
    int      configured;         /* non-zero after configure + set calls      */
} bist_ctx_t;

/*
 * Create a minimal bist-only context.  Does NOT load libstata — uses
 * the pre-resolved addresses passed by the Python manifest system.
 * This is the lightweight path for when the Stata engine was already
 * initialised via Python ctypes (standard config flow).
 * Returns heap-allocated bist_ctx_t (must free via stata_bist_ctx_free).
 */
bist_ctx_t* stata_bist_ctx_new(uint64_t base_addr,
                               uint64_t stack_ptr_off,
                               uint64_t err_addr_off);

/*
 * Free a bist-only context created by stata_bist_ctx_new.
 */
void stata_bist_ctx_free(bist_ctx_t* bctx);

/*
 * Configure the fast _bist_* context with base address and stack/error
 * offsets.  Must be called before any stata_bist_get_* function.
 * All these values come from the Python manifest system.
 */
void stata_bist_configure(bist_ctx_t* bctx, uint64_t base_addr,
                          uint64_t stack_ptr_off, uint64_t err_addr_off);

/*
 * Register a function pointer by slot ID.  Returns 0 on success, -1 on
 * invalid slot ID (> BIST_MAX_SLOTS).
 */
int stata_bist_set_fn(bist_ctx_t* bctx, int slot_id, void* fn_addr);

/*
 * Convenience: get the stack pointer from Stata's memory.
 * The stack pointer is stored at (base_addr + stack_ptr_off).
 */
uint64_t stata_bist_get_sp(bist_ctx_t* bctx);

/*
 * Convenience: restore the stack pointer to a previous value.
 */
void stata_bist_set_sp(bist_ctx_t* bctx, uint64_t sp_val);

/*
 * Generic _bist_* call functions — typed for the common argument
 * patterns used by SFI methods.  All use the ARM64 push+stack
 * convention internally (or direct std ABI on x86_64/Windows).
 *
 * Double-returning with 0, 1, or 2 int args:
 */
double stata_bist_call_d0(bist_ctx_t* bctx, int slot_id);
double stata_bist_call_d1i(bist_ctx_t* bctx, int slot_id, int64_t arg1);
double stata_bist_call_d2i(bist_ctx_t* bctx, int slot_id,
                           int64_t arg1, int64_t arg2);

/*
 * Double-returning with 1 string arg (macro/scalar name):
 */
double stata_bist_call_d1s(bist_ctx_t* bctx, int slot_id,
                           const char* str_arg);

/*
 * String-returning with 0, 1, or 2 int args.
 * Result is malloc'd; caller must free with stata_free().
 * Returns NULL on error.
 */
char* stata_bist_call_s0(bist_ctx_t* bctx, int slot_id);
char* stata_bist_call_s1i(bist_ctx_t* bctx, int slot_id, int64_t arg1);
char* stata_bist_call_s2i(bist_ctx_t* bctx, int slot_id,
                          int64_t arg1, int64_t arg2);

/*
 * String-returning with 1 string arg.
 */
char* stata_bist_call_s1s(bist_ctx_t* bctx, int slot_id,
                          const char* str_arg);

/*
 * Store double/int at (obs, var) — calls _bist_store with 3 args:
 * obs (int), var (int), double value (push as double).
 * Returns error code from global error variable (0 = success).
 */
int stata_bist_store_double(bist_ctx_t* bctx, int slot_id,
                            int64_t obs, int64_t var, double val);

/*
 * Store string at (obs, var) — calls _bist_sstore with 3 args:
 * obs (int), var (int), string value (push as string).
 * Returns error code from global error variable (0 = success).
 */
int stata_bist_store_string(bist_ctx_t* bctx, int slot_id,
                            int64_t obs, int64_t var, const char* val);

/*
 * Get the last Stata error code from the global error variable.
 */
int stata_bist_get_err(bist_ctx_t* bctx);


/* ------------------------------------------------------------------ */
/*  Convenience wrappers — match common SFI method signatures         */
/* ------------------------------------------------------------------ */

double  stata_bist_get_nobs(bist_ctx_t* bctx);
double  stata_bist_get_nvar(bist_ctx_t* bctx);
double  stata_bist_get_double(bist_ctx_t* bctx, int obs, int var);
char*   stata_bist_get_string(bist_ctx_t* bctx, int obs, int var);
char*   stata_bist_get_varname(bist_ctx_t* bctx, int varno);
char*   stata_bist_get_varlabel(bist_ctx_t* bctx, int varno);
char*   stata_bist_get_vartype(bist_ctx_t* bctx, int varno);
char*   stata_bist_get_varfmt(bist_ctx_t* bctx, int varno);
char*   stata_bist_get_macro(bist_ctx_t* bctx, const char* name);
double  stata_bist_get_scalar(bist_ctx_t* bctx, const char* name);
char*   stata_bist_get_scalar_str(bist_ctx_t* bctx, const char* name);

/*
 * Store operations — write values via _bist_store / _bist_sstore.
 * Returns error code (0 = success).
 */
int stata_bist_store(bist_ctx_t* bctx, int obs, int var, double val);
int stata_bist_sstore(bist_ctx_t* bctx, int obs, int var, const char* val);


/* ------------------------------------------------------------------ */
/*  Diagnostics                                                       */
/* ------------------------------------------------------------------ */

/*
 * Return the last error message (internal buffer — do not free).
 * Returns an empty string if no error.  Pass NULL for a global error
 * (e.g. when stata_init returned NULL).
 */
const char* stata_last_error(stata_ctx* ctx);

/*
 * Free a string previously returned by the library.
 */
void stata_free(char* ptr);

#ifdef __cplusplus
}
#endif

#endif /* STATA_FAST_H */
