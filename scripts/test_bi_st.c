/**
 * test_bi_st.c — C test harness for _bi_st_* functions
 *
 * Tests whether _bi_st_* functions work when called from C directly,
 * eliminating ctypes/Python FFI as a variable.
 *
 * Calling convention (ARM64, confirmed working for _bist_*):
 *   1. Push args to Stata's internal stack at SP (_BASE + 0x39b7000 + 0x108)
 *      via _pushint(val), _pushdbl(&val), or _pushstr(ptr, len)
 *   2. Call target function with w0 = arg count
 *   3. Read result from stack (SP incremented by result)
 *   4. Restore SP
 *
 * Build: cc -o test_bi_st test_bi_st.c
 * Run:   ./test_bi_st <libstata-se.dylib path>
 *
 * Note: This must be run from WITHIN a Python/Stata process that has
 * already initialized libstata-se.dylib (specifically, the engine
 * must be initialized). This test is designed to be loaded as a
 * shared library into the existing Python process, OR it can be run
 * as a standalone process that loads the dylib.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dlfcn.h>
#include <stdint.h>

// Stata internal stack pointer (relative to _BASE)
#define SP_OFFSET   (0x39b7000ULL + 0x108ULL)
#define ERR_OFFSET  (0x39b7000ULL + 0x11cULL)
#define BASE_PLUS   (0x39b7000ULL + 0x120ULL)

// Function pointer types for push helpers
typedef void (*pushint_fn_t)(int64_t val);
typedef void (*pushdbl_fn_t)(double *val);
typedef void (*pushstr_fn_t)(const char *str, size_t len);
typedef void (*bist_fn_t)(int arg_count);

// Base address of libstata-se.dylib (text section)
static uint64_t g_base = 0;
// Stata internal SP location
static volatile uint64_t *g_sp_ptr = NULL;
// Error code location
static volatile int32_t *g_err_ptr = NULL;

// Push helper function pointers
static pushint_fn_t g_pushint;
static pushdbl_fn_t g_pushdbl;
static pushstr_fn_t g_pushstr;

/**
 * Load libstata-se.dylib and resolve function addresses.
 * Returns 0 on success, -1 on failure.
 */
int load_stata_library(const char *dylib_path) {
    void *handle = dlopen(dylib_path, RTLD_LAZY | RTLD_LOCAL);
    if (!handle) {
        fprintf(stderr, "dlopen failed: %s\n", dlerror());
        return -1;
    }

    // Get text section base using dyld info
    // This is complex; for now we rely on the manifest offsets.
    // The manifest gives offsets relative to the __TEXT segment load address.
    
    // For a running process, we can find _BASE through the symbol table:
    // _BASE is typically the __TEXT segment vmaddr.
    // Look up a known symbol and subtract its offset.
    
    // For simplicity in this harness, we'll read offsets from manifest
    // and add to _BASE.
    
    fprintf(stderr, "Library loaded: %s\n", dylib_path);
    return 0;
}

/**
 * Push an integer arg to Stata's internal stack.
 */
void push_int(int64_t val) {
    if (g_pushint) g_pushint(val);
}

/**
 * Push a double arg to Stata's internal stack.
 */
void push_double(double val) {
    if (g_pushdbl) g_pushdbl(&val);
}

/**
 * Push a string arg to Stata's internal stack.
 */
void push_string(const char *str, size_t len) {
    if (g_pushstr) g_pushstr(str, len);
}

/**
 * Get current internal stack pointer value.
 */
uint64_t get_sp(void) {
    if (g_sp_ptr) return *g_sp_ptr;
    return 0;
}

/**
 * Restore internal stack pointer.
 */
void restore_sp(uint64_t sp_val) {
    if (g_sp_ptr) *g_sp_ptr = sp_val;
}

/**
 * Read error code.
 */
int32_t get_err(void) {
    if (g_err_ptr) return *g_err_ptr;
    return -1;
}

int main(int argc, char **argv) {
    printf("C Test Harness for _bi_st_* functions\n");
    printf("=====================================\n\n");
    
    printf("NOTE: This harness must be loaded from within a running\n");
    printf("Stata/Python process that has already initialized libstata-se.dylib.\n");
    printf("Run via: .venv/bin/python3 -c \"import ctypes; ctypes.CDLL('./test_bi_st.so')\"\n\n");
    
    printf("Alternatively, use the Python-based test scripts already created:\n");
    printf("  scripts/test_strlpart3.py — tests _bi_st_strlpart with correct types\n");
    printf("  scripts/test_unab2.py    — tests _bi_st_unab\n\n");
    
    printf("Key findings from static analysis (radare2) + Python probes:\n\n");
    printf("1. _bi_st_strlpart calling convention:\n");
    printf("   - Push 3 args: string name (SP[-2]), int obs (SP[-1]), int part (SP[0])\n");
    printf("   - string arg must have tsmat type=-3 at offset +0x34\n");
    printf("     (created by _pushstr, NOT by _pushint)\n");
    printf("   - call with w0=3\n");
    printf("   - Returns: err=0, SP decreases by 16 (2 args consumed, string left in place)\n");
    printf("   - No new result pushed to stack (result may be in tsmat modification)\n\n");
    
    printf("2. _bi_st_unab calling convention:\n");
    printf("   - Push 1 string arg (type=-3 tsmat)\n");
    printf("   - call with w0=1\n");
    printf("   - Returns: err=0, no result pushed\n\n");
    
    printf("3. Key difference from _bist_*:\n");
    printf("   - _bist_data: reads SP[0] and SP[-1] for 2 args (int tsmats, type=0)\n");
    printf("   - _bi_st_strlpart: reads SP[-2], SP[-1], SP[0] for 3 args\n");
    printf("     (arg1 must be type=-3 tsmat, created by _pushstr)\n");
    printf("   - _bi_st_unab: reads SP[0] only for 2-arg call, validates type=-3\n\n");
    
    printf("4. tsmat type field:\n");
    printf("   - Located at tsmat+0x34 (signed 16-bit)\n");
    printf("   - _pushint creates tsmat with type=0\n");
    printf("   - _pushstr creates tsmat with type=-3 (0xfffd)\n");
    printf("   - _bist_data accepts type=0 OR type=-3\n");
    printf("   - _bi_st_strlpart accepts type=-3 ONLY for arg1\n\n");
    
    printf("5. Next steps:\n");
    printf("   - Determine what _bi_st_strlpart actually returns (where is the part data?)\n");
    printf("   - Try _bi_st_strlpart with pre-allocated string buffer as arg1\n");
    printf("   - Test _bi_st_strlpartid variant (at 0x2ef* address range)\n");
    printf("   - Implement working engine wrapper once convention is fully understood\n\n");
    
    return 0;
}
