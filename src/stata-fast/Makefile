# SPDX-License-Identifier: AGPL-3.0-only
#
# Makefile for libstata_fast — lightweight C wrapper around libstata.
#
# ╔══════════════════════════════════════════════════════════════════╗
# ║  CMake is the PRIMARY build system for cross-platform work.    ║
# ║  This Makefile is kept for convenience during local iteration  ║
# ║  on macOS/Linux.  For Linux, Windows, and CI use:             ║
# ║    cmake -S . -B build && cmake --build build                  ║
# ╚══════════════════════════════════════════════════════════════════╝
#
# Targets
#   make          — build shared library
#   make test     — build and run unit tests
#   make clean    — remove build artifacts

UNAME := $(shell uname)

CFLAGS  ?= -O2 -fPIC -Wall -Wextra -Wpedantic -std=c99
LDFLAGS ?=

ifeq ($(UNAME), Darwin)
  # macOS: .dylib — dlopen is part of libSystem, no extra flags
  LIBNAME  = libstata_fast.dylib
  LDFLAGS += -dynamiclib -current_version 0.1.0 -compatibility_version 0.1.0
else
  # Linux: .so — requires -ldl for dlopen
  LIBNAME  = libstata_fast.so
  LDFLAGS += -shared -ldl
endif

SRC = stata_fast.c
OBJ = stata_fast.o

.PHONY: all clean test

all: $(LIBNAME) bypass_init.dylib

bypass_init.dylib: bypass_init.c
	$(CC) $(CFLAGS) -dynamiclib -o $@ $< -Wl,-undefined,dynamic_lookup

$(OBJ): $(SRC) stata_fast.h
	$(CC) $(CFLAGS) -c -o $@ $<

$(LIBNAME): $(OBJ)
	$(CC) $(LDFLAGS) -o $@ $^

test: $(LIBNAME) test_stata_fast.c stata_fast.h
	$(CC) $(CFLAGS) -o test_stata_fast test_stata_fast.c -L. -lstata_fast
	./test_stata_fast

clean:
	rm -f $(OBJ) $(LIBNAME) bypass_init.dylib test_stata_fast
