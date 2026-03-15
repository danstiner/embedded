#!/usr/bin/env bash
# Mirrors the GitHub lint CI job locally.
# Usage: ./lint.sh [--fix]
set -euo pipefail

FIX=false
if [[ "${1:-}" == "--fix" ]]; then
    FIX=true
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ---------------------------------------------------------------------------
# ruff
# ---------------------------------------------------------------------------
if ! command -v ruff &>/dev/null; then
    echo "ruff not found — install with: pip install ruff  or  brew install ruff" >&2
    exit 1
fi

echo "==> ruff"
if $FIX; then
    ruff check --fix .
    ruff format .
else
    ruff check .
    ruff format --check .
fi

# ---------------------------------------------------------------------------
# clang-format
# ---------------------------------------------------------------------------
CLANG_FORMAT="${CLANG_FORMAT:-}"
if [[ -z "$CLANG_FORMAT" ]]; then
    # Prefer a versioned binary close to what CI uses (18), fall back to whatever is installed
    for candidate in clang-format-18 clang-format-19 clang-format-20 clang-format; do
        if command -v "$candidate" &>/dev/null; then
            CLANG_FORMAT="$candidate"
            break
        fi
    done
fi

if [[ -z "$CLANG_FORMAT" ]]; then
    echo "clang-format not found — install with: brew install llvm" >&2
    exit 1
fi

echo "==> clang-format ($($CLANG_FORMAT --version | head -1))"

FILES=()
while IFS= read -r -d '' f; do
    FILES+=("$f")
done < <(find . \
    -type f \
    \( -name '*.c' -o -name '*.cpp' -o -name '*.h' -o -name '*.hpp' \) \
    -not -path './west/*' \
    -not -path '*/build*/*' \
    -not -path '*/zap-generated/*' \
    -print0)

if [[ ${#FILES[@]} -eq 0 ]]; then
    echo "No C/C++ files found."
elif $FIX; then
    "$CLANG_FORMAT" -i "${FILES[@]}"
    echo "Formatted ${#FILES[@]} file(s)."
else
    if ! "$CLANG_FORMAT" --dry-run --Werror "${FILES[@]}" 2>&1; then
        echo ""
        echo "Run './lint.sh --fix' to auto-fix." >&2
        exit 1
    fi
    echo "All ${#FILES[@]} file(s) are correctly formatted."
fi

echo ""
echo "All checks passed."
