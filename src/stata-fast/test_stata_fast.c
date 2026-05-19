/* SPDX-License-Identifier: AGPL-3.0-only */
/*
 * test_stata_fast.c — Test libstata_fast C API.
 *
 * Compile: cc -O0 -g -Wall -Wextra -Wpedantic -std=c99 \
 *            -o test_stata_fast test_stata_fast.c -L. -lstata_fast
 */

#include "stata_fast.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

/* Fallback defaults when not building via CMake */
#ifndef TEST_STATA_PATH
#define TEST_STATA_PATH "/Applications/StataNow"
#endif
#ifndef TEST_STATA_EDITION
#define TEST_STATA_EDITION "se"
#endif

static int tests = 0;
static int passed = 0;

#define TEST(name, cond) do {                                   \
    ++tests;                                                    \
    if (!(cond)) {                                              \
        fprintf(stderr, "  FAIL [%s:%d] %s\n",                  \
                __FILE__, __LINE__, name);                      \
    } else {                                                    \
        ++passed;                                               \
        printf("  PASS  %s\n", name);                           \
    }                                                           \
} while(0)

int main(void) {
    const char* st_path = getenv("STATA_PATH");
    if (!st_path) st_path = TEST_STATA_PATH;
    const char* edition = getenv("STATA_EDITION");
    if (!edition) edition = TEST_STATA_EDITION;

    printf("=== libstata_fast test ===\n");
    printf("  st_path=%s  edition=%s\n\n", st_path, edition);

    /* ---- init ---- */
    printf("[init] Calling stata_init...\n");
    stata_ctx* ctx = stata_init(st_path, edition, 0);  /* no splash */
    if (!ctx) {
        fprintf(stderr, "  FAIL: stata_init returned NULL: %s\n",
                stata_last_error(NULL));
        return 1;
    }
    TEST("stata_init returns non-NULL", ctx != NULL);

    /* ---- execute simple command (no echo) ---- */
    printf("\n[execute] display 1+1 (no echo)\n");
    char* out = NULL;
    size_t out_len = 0;
    int rc = -1;
    int err = stata_execute(ctx, "display 1+1", 0, &out, &out_len, &rc);
    TEST("stata_execute returns STATA_OK", err == STATA_OK);
    TEST("stata_execute rc=0", rc == 0);
    TEST("stata_execute output non-NULL", out != NULL);
    if (out) {
        /* Output should contain "2" somewhere */
        TEST("stata_execute output contains '2'", strstr(out, "2") != NULL);
        printf("  output=[%.200s]  len=%zu  rc=%d\n", out, out_len, rc);
        stata_free(out);
        out = NULL;
    }

    /* ---- execute with echo ---- */
    printf("\n[execute] display 3+4 (with echo)\n");
    err = stata_execute(ctx, "display 3+4", 1, &out, &out_len, &rc);
    TEST("echo execute returns STATA_OK", err == STATA_OK);
    TEST("echo execute rc=0", rc == 0);
    if (out) {
        TEST("echo output contains '7'", strstr(out, "7") != NULL);
        printf("  output=[%.300s]  len=%zu  rc=%d\n", out, out_len, rc);
        stata_free(out);
        out = NULL;
    }

    /* ---- execute again (ensure context reuse) ---- */
    printf("\n[execute] display 10*10\n");
    err = stata_execute(ctx, "display 10*10", 0, &out, &out_len, &rc);
    TEST("second execute rc=0", rc == 0);
    if (out) {
        TEST("output contains '100'", strstr(out, "100") != NULL);
        printf("  output=[%.200s]  rc=%d\n", out, rc);
        stata_free(out);
        out = NULL;
    }

    /* ---- get_output (should be empty since execute drains) ---- */
    printf("\n[get_output] (should be empty after execute)\n");
    char* buf = stata_get_output(ctx);
    TEST("get_output is empty after execute", buf == NULL || buf[0] == '\0');
    stata_free(buf);

    /* ---- get_output after execute that reuses buffer ---- */
    printf("\n[get_output] after a new execute\n");
    err = stata_execute(ctx, "display 42", 0, &out, &out_len, &rc);
    if (out) stata_free(out);
    /* get_output now should have nothing because execute drained it */
    buf = stata_get_output(ctx);
    TEST("get_output empty after second execute", buf == NULL || buf[0] == '\0');
    stata_free(buf);

    /* ---- clear_output ---- */
    printf("\n[clear_output]\n");
    /* First put something in the buffer */
    err = stata_execute(ctx, "display 99", 0, NULL, NULL, NULL);
    /* Then clear */
    stata_clear_output(ctx);
    buf = stata_get_output(ctx);
    TEST("buffer empty after clear", buf == NULL || buf[0] == '\0');
    stata_free(buf);

    /* ---- error command (rc != 0) ---- */
    printf("\n[execute] errored command\n");
    err = stata_execute(ctx, "no_such_command", 0, &out, &out_len, &rc);
    TEST("error execute returns STATA_OK (command ran)", err == STATA_OK);
    TEST("error rc != 0", rc != 0);
    if (out) {
        printf("  output=[%.200s]  rc=%d\n", out, rc);
        stata_free(out);
        out = NULL;
    }

    /* ---- set_break ---- */
    printf("\n[set_break] (no-op if nothing running)\n");
    err = stata_set_break(ctx);
    TEST("stata_set_break returns OK", err == STATA_OK);

    /* ---- last_error ---- */
    printf("\n[last_error] should be empty\n");
    const char* errmsg = stata_last_error(ctx);
    TEST("last_error is empty string", errmsg != NULL && errmsg[0] == '\0');

    /* ---- NULL-safe shutdown ---- */
    printf("\n[shutdown]\n");
    stata_shutdown(ctx);
    TEST("shutdown succeeded (no crash)", 1);

    /* ---- double shutdown (null-safe) ---- */
    stata_shutdown(NULL);
    TEST("NULL shutdown is safe", 1);

    printf("\n=== Results: %d/%d passed ===\n", passed, tests);
    return (passed == tests) ? 0 : 1;
}
