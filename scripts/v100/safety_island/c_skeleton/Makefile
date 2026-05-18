# Makefile for the safety-island C skeleton.
#
# Builds the safety_island library as a static archive and a unit-test
# executable. Compile flags target MISRA-C 2012 strictness; the production
# build adds vendor-specific certified toolchain flags (e.g. ARM Compiler 6
# with --cpu=Cortex-M7.fp.dp). For development on x86-64, plain gcc/clang
# with -Wall -Wextra -pedantic -std=c11 is sufficient.

CC ?= gcc
CFLAGS = -std=c11 -Wall -Wextra -Wpedantic -Wstrict-prototypes \
         -Wmissing-prototypes -Wmissing-declarations \
         -Wundef -Wno-unused-parameter \
         -fno-strict-aliasing -O2 -g

LDFLAGS =

OBJ = safety_island.o
LIB = libsafety_island.a
TEST_BIN = test_safety_island

.PHONY: all clean test misra

all: $(LIB)

$(LIB): $(OBJ)
	$(AR) rcs $@ $^

$(OBJ): %.o: %.c safety_island.h
	$(CC) $(CFLAGS) -c -o $@ $<

test: $(LIB) test_safety_island.c
	$(CC) $(CFLAGS) -o $(TEST_BIN) test_safety_island.c -L. -lsafety_island
	./$(TEST_BIN)

misra:
	@echo "Run PC-lint Plus or Polyspace MISRA-C 2012 against safety_island.c"
	@echo "TODO: add lint config in misra.lnt"

clean:
	rm -f $(OBJ) $(LIB) $(TEST_BIN)
