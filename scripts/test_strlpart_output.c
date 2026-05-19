/**
 * test_strlpart_output.c — C function to read _bi_st_strlpart result
 *
 * Tests whether _bi_st_strlpart modifies the string tsmat in-place
 * to contain the StrL part data.
 *
 * Build: cc -O2 -shared -o scripts/test_strlpart_output.dylib scripts/test_strlpart_output.c
 */

#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stddef.h>

typedef void (*pushint_fn_t)(int64_t val);
typedef void (*pushstr_fn_t)(const char *str, size_t len);
typedef void (*bist_fn_t)(int arg_count);

/**
 * Push 3 args (string, int, int), call _bi_st_strlpart,
 * and return the tsmat content after the call.
 *
 * Results are stored in output buffers.
 *
 * Returns: error code
 */
int64_t test_strlpart_read_result(
    void *fn_addr,
    void *pushint_addr,
    void *pushstr_addr,
    void *sp_ptr,
    void *err_ptr,
    const char *str_arg,
    size_t str_len,
    int int_arg2,
    int int_arg3,
    uint64_t *out_tsmat_addr,
    uint64_t *out_tsmat_data[8]  /* 8 qwords of tsmat content */
) {
    pushint_fn_t pushint = (pushint_fn_t)pushint_addr;
    pushstr_fn_t pushstr = (pushstr_fn_t)pushstr_addr;
    bist_fn_t fn = (bist_fn_t)fn_addr;
    volatile uint64_t *sp = (volatile uint64_t *)sp_ptr;
    volatile int32_t *err_code = (volatile int32_t *)err_ptr;
    
    uint64_t sp_before = *sp;
    
    /* Push args */
    pushstr(str_arg, str_len);
    pushint(int_arg2);
    pushint(int_arg3);
    
    uint64_t sp_before_call = *sp;
    
    /* Get the string tsmat address (at SP[-2] = SP_before_call - 16) */
    uint64_t str_tsmat = *(uint64_t *)(sp_before_call - 16);
    
    /* Save tsmat content BEFORE call */
    uint64_t tsmat_before[8];
    for (int i = 0; i < 8; i++) {
        tsmat_before[i] = *(uint64_t *)(str_tsmat + i * 8);
    }
    
    /* Call */
    fn(3);
    
    int64_t err = *err_code;
    uint64_t sp_after = *sp;
    
    /* Get the tsmat remaining on stack */
    uint64_t remaining_tsmat = *(uint64_t *)sp_after;
    
    /* Fill output */
    *out_tsmat_addr = remaining_tsmat;
    for (int i = 0; i < 8; i++) {
        out_tsmat_data[i] = (uint64_t *)(uintptr_t)(*(uint64_t *)(remaining_tsmat + i * 8));
    }
    
    /* Restore SP */
    *sp = sp_before;
    
    return err;
}
