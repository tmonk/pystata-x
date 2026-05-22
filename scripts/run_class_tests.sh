#!/usr/bin/env bash
# run_class_tests.sh — Run each per-class e2e test file in a separate process.
#
# Usage:
#   ./run_class_tests.sh                    # Run on current machine
#   PLATFORM=linux ./run_class_tests.sh      # Label results as linux
#   PLATFORM=windows ./run_class_tests.sh    # Label results as windows
#
# Exits 0 if ALL test files pass, non-zero if any file fails.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PLATFORM="${PLATFORM:-linux}"
RESULTS_DIR="${SCRIPT_DIR}/../test-results"

mkdir -p "$RESULTS_DIR"

PASSED=0
FAILED=0
FAILED_FILES=()

# ── List all test files ──
declare -a TEST_FILES
for f in "$PROJECT_DIR"/tests/e2e/core/*.py; do
    TEST_FILES+=("$f")
done
TEST_FILES+=("$PROJECT_DIR/tests/e2e/test_sfi.py")

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SUMMARY_FILE="$RESULTS_DIR/${PLATFORM}_${TIMESTAMP}.log"

echo "============================================"
echo "  pystata-x Per-Class e2e Test Runner"
echo "  Platform:  $PLATFORM"
echo "  Timestamp: $(date)"
echo "  Test files: ${#TEST_FILES[@]}"
echo "============================================"
echo ""

for tfile in "${TEST_FILES[@]}"; do
    base=$(basename "$tfile" .py)
    echo -n "  [ ] $base ... "

    # Run each file with -m requires_stata (the default pyproject.toml marker
    # excludes requires_stata, so we must explicitly include it)
    set +e
    output=$("$PROJECT_DIR/.venv/bin/python3" -m pytest "$tfile" \
        -m requires_stata --tb=line -q 2>&1)
    ec=$?
    set -e

    if [ "$ec" -eq 0 ]; then
        echo "PASS"
        PASSED=$((PASSED + 1))
    else
        echo "FAIL"
        FAILED=$((FAILED + 1))
        FAILED_FILES+=("$base")
        # Log failures
        echo "=== $base ===" >> "$SUMMARY_FILE"
        echo "$output" | grep -E "^tests.*FAILED|^.*ERROR" >> "$SUMMARY_FILE" 2>/dev/null || true
    fi
done

# ── Summary ──
echo ""
echo "============================================"
echo "  Results: $PASSED passed, $FAILED failed"
if [ ${#FAILED_FILES[@]} -gt 0 ]; then
    echo "  Failed files:"
    for ff in "${FAILED_FILES[@]}"; do
        echo "    - $ff"
    done
fi
echo ""
echo "  Log: $SUMMARY_FILE"
echo "============================================"

# Write JUnit-compatible summary XML
XML_FILE="$RESULTS_DIR/${PLATFORM}_${TIMESTAMP}.xml"
{
    echo '<?xml version="1.0" encoding="UTF-8"?>'
    echo "<testsuite name=\"pystata-x-e2e-${PLATFORM}\" tests=\"${#TEST_FILES[@]}\" failures=\"${FAILED}\">"
    for tfile in "${TEST_FILES[@]}"; do
        base=$(basename "$tfile" .py)
        # We re-run to get per-class result — quick check
        set +e
        "$PROJECT_DIR/.venv/bin/python3" -m pytest "$tfile" -m requires_stata --tb=line -q >/dev/null 2>&1
        ec=$?
        set -e
        if [ "$ec" -eq 0 ]; then
            echo "  <testcase classname=\"${PLATFORM}\" name=\"${base}\" />"
        else
            echo "  <testcase classname=\"${PLATFORM}\" name=\"${base}\">"
            echo "    <failure message=\"${base} failed\" />"
            echo "  </testcase>"
        fi
    done
    echo "</testsuite>"
} > "$XML_FILE"

echo "  JUnit XML: $XML_FILE"

if [ "$FAILED" -gt 0 ]; then
    exit 1
fi
exit 0
