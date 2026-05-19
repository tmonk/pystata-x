# SPDX-License-Identifier: AGPL-3.0-only
#
# CMakeLists.txt — Cross-platform build for libstata_fast
#
# Targets:
#   libstata_fast (SHARED) — .dylib (macOS), .so (Linux), or .dll (Windows)
#   test_stata_fast       — C test binary (links against libstata_fast)
#
# Supported platforms: macOS (ARM64/x86_64), Linux (x86_64), Windows (x86_64)
#
# Usage:
#   mkdir build && cd build
#   cmake .. -DSTATA_PATH="/Applications/StataNow" -DSTATA_EDITION=se
#   cmake --build .
#   ctest

cmake_minimum_required(VERSION 3.20)
project(libstata_fast
    VERSION 0.1.0
    DESCRIPTION "Lean C wrapper around Stata's engine API"
    LANGUAGES C
)

# ── Project options ────────────────────────────────────────────────────────

set(STATA_PATH   "/Applications/StataNow" CACHE PATH "Stata installation root")
set(STATA_EDITION "se"  CACHE STRING        "Stata edition: be, se, or mp")

# ── C standard ─────────────────────────────────────────────────────────────

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

# https://cmake.org/cmake/help/latest/variable/CMAKE_POLICY_DEFAULT_CMP0177.html
# Prevent CMake from adding -fPIC automatically (we handle it ourselves)
if(POLICY CMP0177)
    cmake_policy(SET CMP0177 NEW)
endif()

# ── Compiler flags ─────────────────────────────────────────────────────────

# We must set POSIX source macros so that dlopen/dlsym/dlerror are declared
# on Linux (otherwise -std=c99 hides them).  On Windows these are not used.
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    add_compile_definitions(_POSIX_C_SOURCE=200809L _DARWIN_C_SOURCE)
endif()

# ── Library target ─────────────────────────────────────────────────────────

add_library(stata_fast SHARED
    stata_fast.c
)

target_include_directories(stata_fast
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

# ── Compiler flags (must be set after add_library) ─────────────────────────

if(MSVC)
    # MSVC is not C99-compliant by default; we still ask for it, but the
    # real compatibility is provided by the Universal CRT runtime library.
    # Silence deprecation warnings for POSIX names (snprintf, strdup, etc.)
    add_compile_definitions(_CRT_SECURE_NO_WARNINGS)
    target_compile_options(stata_fast PRIVATE /W4)
else()
    add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# Platform-specific link dependencies
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    # dlopen / dlsym / dlclose live in libdl on Linux
    target_link_libraries(stata_fast PRIVATE ${CMAKE_DL_LIBS})
elseif(CMAKE_SYSTEM_NAME STREQUAL "Windows")
    # LoadLibrary / GetProcAddress live in kernel32 — linked automatically
    # No extra link libraries needed
    target_link_libraries(stata_fast PRIVATE kernel32 user32)
    # Set output name: on Windows CMake produces stata_fast.dll (no lib prefix)
    set_target_properties(stata_fast PROPERTIES
        PREFIX ""
        IMPORT_PREFIX ""
    )
elseif(APPLE)
    # dlopen is in libSystem — included automatically, no extra flags
    # dlerror/dlsym etc. are also in libSystem on macOS
    set_target_properties(stata_fast PROPERTIES
        INSTALL_NAME_DIR "@rpath"
        BUILD_WITH_INSTALL_NAME_DIR ON
    )
endif()

# ── Compilation smoke test (no Stata needed) ─────────────────────────────

enable_testing()

# This executable only verifies the header compiles and the library links.
# It does NOT call any Stata API function, so it runs without Stata installed.
add_executable(compile_check
    compile_check.c
)
target_link_libraries(compile_check PRIVATE stata_fast)

add_test(NAME compile_check
    COMMAND compile_check
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
)

# ── Test executable (requires Stata at runtime) ────────────────────────────

add_executable(test_stata_fast
    test_stata_fast.c
)
target_link_libraries(test_stata_fast PRIVATE stata_fast)

# Provide Stata path / edition as compile definitions so test picks them up
target_compile_definitions(test_stata_fast PRIVATE
    TEST_STATA_PATH="${STATA_PATH}"
    TEST_STATA_EDITION="${STATA_EDITION}"
)

# Register test with Stata path / edition
add_test(NAME test_stata_fast
    COMMAND test_stata_fast
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
)
set_tests_properties(test_stata_fast PROPERTIES
    ENVIRONMENT "STATA_PATH=${STATA_PATH};STATA_EDITION=${STATA_EDITION}"
)

# Disable Stata-dependent test on CI where Stata is unavailable
# (tests still run when STATA_PATH points to a valid installation)
set_property(TEST test_stata_fast PROPERTY
    SKIP_RETURN_CODE 77
)

# ── Installation ───────────────────────────────────────────────────────────

include(GNUInstallDirs)

install(TARGETS stata_fast
    LIBRARY       DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME       DESTINATION ${CMAKE_INSTALL_BINDIR}
    ARCHIVE       DESTINATION ${CMAKE_INSTALL_LIBDIR}
)
install(FILES stata_fast.h
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
)
install(TARGETS test_stata_fast compile_check
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
    OPTIONAL
)

# ── Custom target: run tests with Stata path —──────────────────────────────

add_custom_target(check
    COMMAND ${CMAKE_COMMAND} -E env
        STATA_PATH="${STATA_PATH}"
        STATA_EDITION="${STATA_EDITION}"
        $<TARGET_FILE:test_stata_fast>
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
    USES_TERMINAL
)
