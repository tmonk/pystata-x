/*
 * bypass_init.c  —  DYLD_INSERT_LIBRARIES stub for Stata init bypass
 *
 * On modern macOS (15+), DYLD_INSERT_LIBRARIES-based symbol interposing
 * of system library symbols (dlopen, etc.) is restricted by SIP and
 * hardened runtime policies.  This file is retained as a reference
 * implementation for environments where dyld interposing is available.
 *
 * The working runtime mechanism used by libstata_fast is argv
 * manipulation (omitting the -pyexec flag when calling StataSO_Main),
 * implemented in stata_fast.c's stata_init_engine().
 *
 * SPDX-FileCopyrightText: 2025 Thomas Monk <t.d.monk@lse.ac.uk>
 * SPDX-License-Identifier: AGPL-3.0-only
 */

/* This file intentionally kept minimal — the runtime mechanism is
 * implemented in stata_fast.c via argv manipulation.  See ANALYSIS.md
 * for details of why DYLD_INSERT_LIBRARIES is non-functional on macOS 15+. */

/* Satisfy -Wempty-translation-unit with a (discarded) symbol */
__attribute__((unused)) static const char* _bypass_init_version = "1.0";
