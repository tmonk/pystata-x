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
