/**
 * test_bi_st_harness.c — C shared library for testing _bi_st_* calling convention
 *
 * This is loaded into the running Python/Stata process to eliminate ctypes/FFI
 * as a variable in calling convention experiments.
 *
 * Build: cc -O2 -shared -o test_bi_st_harness.dylib test_bi_st_harness.c
 * Load:  import ctypes; lib = ctypes.CDLL('./test_bi_st_harness.dylib')
 *
 * The Python code passes function addresses and arg values directly.
 */

#include <stdio.h>
#include <stdint.h>
#include <stddef.h>

/* Stata internal stack pointer is at _BASE + 0x39b7000 + 0x108,
   stored as a uint64_t* (pointer to current SP value).
   The SP value itself is a pointer into the tsmat stack. */

/* Function pointer types for push helpers */
typedef void (*pushint_fn_t)(int64_t val);
typedef void (*pushdbl_fn_t)(double *val);
typedef void (*pushstr_fn_t)(const char *str, size_t len);
typedef void (*bist_fn_t)(int arg_count);

/**
 * Call a _bi_st_* function with int args passed through.
 * This is the C equivalent of what call_void does in Python.
 *
 * Args:
 *   fn_addr: address of the _bi_st_* function
 *   pushint: address of the _pushint helper function
 *   sp_ptr:  pointer to the Stata internal stack SP variable
 *   err_ptr: pointer to the error code variable
 *   arg_count: number of args (w0)
 *   args: array of int64_t arg values
 *
 * Returns:
 *   error code after the call, or -1 on crash
 */
int64_t call_bist_with_ints(
    void *fn_addr,
    void *pushint_addr,
    void *sp_ptr,
    void *err_ptr,
    int arg_count,
    int64_t *args
) {
    pushint_fn_t pushint = (pushint_fn_t)pushint_addr;
    bist_fn_t fn = (bist_fn_t)fn_addr;
    volatile uint64_t *sp = (volatile uint64_t *)sp_ptr;
    volatile int32_t *err_code = (volatile int32_t *)err_ptr;
    
    uint64_t sp_before = *sp;
    
    /* Push each arg */
    for (int i = 0; i < arg_count; i++) {
        pushint(args[i]);
    }
    
    /* Call the function */
    fn(arg_count);
    
    int64_t err = *err_code;
    uint64_t sp_after = *sp;
    
    /* Restore SP */
    *sp = sp_before;
    
    return err;
}

/**
 * Call a _bi_st_* function with mixed string+int args.
 * First arg is a string, remaining are ints.
 *
 * This is designed for _bi_st_strlpart which needs:
 *   arg1 (SP[-2]): string name (via pushstr, creates type=-3 tsmat)
 *   arg2 (SP[-1]): int
 *   arg3 (SP[0]):  int
 */
int64_t call_bist_strlpart(
    void *fn_addr,
    void *pushint_addr,
    void *pushstr_addr,
    void *sp_ptr,
    void *err_ptr,
    const char *str_arg,
    size_t str_len,
    int int_arg2,
    int int_arg3
) {
    pushint_fn_t pushint = (pushint_fn_t)pushint_addr;
    pushstr_fn_t pushstr = (pushstr_fn_t)pushstr_addr;
    bist_fn_t fn = (bist_fn_t)fn_addr;
    volatile uint64_t *sp = (volatile uint64_t *)sp_ptr;
    volatile int32_t *err_code = (volatile int32_t *)err_ptr;
    
    uint64_t sp_before = *sp;
    
    /* Push 3 args: string first (SP[-2]), then 2 ints */
    pushstr(str_arg, str_len);
    pushint(int_arg2);
    pushint(int_arg3);
    
    /* Call with 3 args */
    fn(3);
    
    int64_t err = *err_code;
    uint64_t sp_after = *sp;
    
    /* Restore SP */
    *sp = sp_before;
    
    return err;
}

/**
 * Probe a _bi_st_* function by calling with various arg combinations.
 * Returns the error code after each call.
 *
 * Args:
 *   fn_addr: the function to test
 *   pushint: _pushint function
 *   sp_ptr:  internal stack SP
 *   err_ptr: error code
 *   test_pattern: bitmask 
 *     0x01 = test with 0 int args
 *     0x02 = test with 1 int arg
 *     0x04 = test with 2 int args
 *     0x08 = test with 3 int args
 *     0x10 = test with 1 string arg
 * 
 * Returns bitmask of patterns that didn't crash
 */
int probe_function(
    void *fn_addr,
    void *pushint_addr,
    void *pushstr_addr,
    void *sp_ptr,
    void *err_ptr,
    int test_pattern
) {
    pushint_fn_t pushint = (pushint_fn_t)pushint_addr;
    pushstr_fn_t pushstr = (pushstr_fn_t)pushstr_addr;
    bist_fn_t fn = (bist_fn_t)fn_addr;
    volatile uint64_t *sp = (volatile uint64_t *)sp_ptr;
    volatile int32_t *err_code = (volatile int32_t *)err_ptr;
    
    int results = 0;
    
    if (test_pattern & 0x01) {
        uint64_t sp_before = *sp;
        fn(0);
        if (*err_code != -1) results |= 0x01; // didn't crash
        *sp = sp_before;
    }
    
    if (test_pattern & 0x02) {
        uint64_t sp_before = *sp;
        pushint(1);
        fn(1);
        if (*err_code != -1) results |= 0x02;
        *sp = sp_before;
    }
    
    if (test_pattern & 0x04) {
        uint64_t sp_before = *sp;
        pushint(1); pushint(2);
        fn(2);
        if (*err_code != -1) results |= 0x04;
        *sp = sp_before;
    }
    
    if (test_pattern & 0x08) {
        uint64_t sp_before = *sp;
        pushint(1); pushint(2); pushint(3);
        fn(3);
        if (*err_code != -1) results |= 0x08;
        *sp = sp_before;
    }
    
    if (test_pattern & 0x10) {
        uint64_t sp_before = *sp;
        pushstr("auto", 4);
        fn(1);
        if (*err_code != -1) results |= 0x10;
        *sp = sp_before;
    }
    
    return results;
}

/**
 * Print summary of _bi_st_* reverse engineering findings.
 */
void print_findings(void) {
    printf("=== _bi_st_* Reverse Engineering Results ===\n");
    printf("\n");
    printf("1. Key finding: _bi_st_* functions use the SAME push+stack calling\n");
    printf("   convention as _bist_*, but with important differences:\n");
    printf("\n");
    printf("   a) Some read args at different stack offsets:\n");
    printf("      - _bist_data: reads SP[0] and SP[-1] (2 args)\n");
    printf("      - _bi_st_strlpart: reads SP[-2], SP[-1], SP[0] (3 args)\n");
    printf("      - _bi_st_unab: reads SP[0] for 2-arg calls\n");
    printf("\n");
    printf("   b) Type field at tsmat+0x34 matters:\n");
    printf("      - _pushint creates type=0 tsmats\n");
    printf("      - _pushstr creates type=-3 (0xfffd) tsmats\n");
    printf("      - _bist_data accepts type=0 or type=-3\n");
    printf("      - _bi_st_strlpart requires type=-3 for arg1\n");
    printf("\n");
    printf("2. Working calls (from Python probes):\n");
    printf("   - _bi_st_unab(b'make'): err=0, no crash, state preserved\n");
    printf("   - _bi_st_strlpart(b's', 1, 0): err=0, no crash, state preserved\n");
    printf("     (strL var 's', obs=1, part=0)\n");
    printf("\n");
    printf("3. Still unknown:\n");
    printf("   - Where does _bi_st_strlpart store its result?\n");
    printf("     (Not on stack — SP decreases. Maybe modifies tsmat in-place?)\n");
    printf("   - Correct interpretation of 'part' arg (byte offset? piece index?)\n");
    printf("   - Whether _bi_st_putmatrixcolstripe/rowstripe work similarly\n");
    printf("\n");
}
