#!/usr/bin/env bash
set -euo pipefail

# Usage: ./tidy.sh <build-dir> [source-filter]

BUILD_DIR="${1:?Usage: $0 <build-dir> [source-filter]}"
SOURCE_FILTER="${2:-}"

COMPILE_DB="$BUILD_DIR/hygrometer/compile_commands.json"
if [ ! -f "$COMPILE_DB" ]; then
    echo "Error: $COMPILE_DB not found (was -DCMAKE_EXPORT_COMPILE_COMMANDS=ON passed?)" >&2
    exit 1
fi

TIDY_DIR=$(mktemp -d)
trap "rm -rf '$TIDY_DIR'" EXIT

# Strip GCC-only flags and inject cross-compiler C++ stdlib paths into the
# compilation database so host clang-tidy can parse everything.
# TODO: Once LLVM 22 ships (~Aug 2026), the flag-stripping can move into .clang-tidy
# using CompilationArgsToRemoveRegex. See https://github.com/llvm/llvm-project/pull/164344
python3 -c "
import json, os, sys

strip_flags = {
    '-fno-printf-return-value', '-fno-reorder-functions',
    '-mfp16-format=ieee', '-fno-defer-pop',
    '--param=min-pagesize=0', '--specs=picolibc.specs',
}

with open(sys.argv[1]) as f:
    cmds = json.load(f)

# Discover C++ stdlib include paths from the sysroot in the compile commands
cxx_isystem = ''
for part in cmds[0]['command'].split():
    if part.startswith('--sysroot='):
        sysroot = part.split('=', 1)[1]
        cxx_dir = os.path.join(sysroot, 'include', 'c++')
        if os.path.isdir(cxx_dir):
            ver = os.listdir(cxx_dir)[0]
            triple = 'arm-zephyr-eabi'
            cxx_isystem = ' '.join([
                f'-isystem {cxx_dir}/{ver}',
                f'-isystem {cxx_dir}/{ver}/{triple}',
                f'-isystem {cxx_dir}/{ver}/backward',
            ])
        break

for c in cmds:
    parts = [p for p in c['command'].split() if p not in strip_flags]
    if cxx_isystem:
        parts.insert(1, cxx_isystem)
    c['command'] = ' '.join(parts)

with open(sys.argv[2], 'w') as f:
    json.dump(cmds, f, indent=2)
" "$COMPILE_DB" "$TIDY_DIR/compile_commands.json"

RUN_CLANG_TIDY=$(command -v run-clang-tidy 2>/dev/null || true)
if [ -z "$RUN_CLANG_TIDY" ]; then
    # Homebrew LLVM on macOS
    RUN_CLANG_TIDY=$(find /opt/homebrew/Cellar/llvm -name run-clang-tidy -type f 2>/dev/null | head -1)
fi
if [ -z "$RUN_CLANG_TIDY" ]; then
    echo "Error: run-clang-tidy not found" >&2
    exit 1
fi

"$RUN_CLANG_TIDY" -p "$TIDY_DIR" $SOURCE_FILTER
