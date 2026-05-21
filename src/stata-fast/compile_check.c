/**
 * compile_check.c — Minimal compilation smoke test for libstata_fast.
 *
 * Verifies the public header compiles cleanly and the library links
 * on any platform, without requiring a Stata installation at runtime.
 *
 * Usage:
 *   cc -c compile_check.c          # header validity (no Stata needed)
 *   cc compile_check.c -lstata_fast  # link check (needs built library)
 *
 * SPDX-License-Identifier: AGPL-3.0-only
 */

#include "stata_fast.h"
#include <stdio.h>

int main(void)
{
    /* Verify types are valid and constants compile */
    printf("STATA_OK=%d\n", STATA_OK);
    printf("stata_init symbol=%p\n", (void *)(size_t)stata_init);
    printf("stata_get_output symbol=%p\n", (void *)(size_t)stata_get_output);
    (void)sizeof(stata_ctx*); /* verify opaque pointer type exists */
    return 0;
}
