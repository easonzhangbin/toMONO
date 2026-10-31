#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p build/native-macos
xcrun clang -arch arm64 -mmacosx-version-min=14.0 -std=c11 -O3 -Wall -Wextra -Werror -ffp-contract=off -fno-fast-math \
  -dynamiclib src/detail_native.c -o build/native-macos/libtomono_detail.dylib
xcrun clang -mmacosx-version-min=14.0 -std=c11 -O2 -Wall -Wextra -Werror -ffp-contract=off -fno-fast-math \
  -Isrc -dynamiclib src/tomono_core.c -o build/native-macos/libtomono_core.dylib
xcrun clang -mmacosx-version-min=14.0 -std=c11 -O2 -Wall -Wextra -Werror -ffp-contract=off -fno-fast-math \
  -Isrc src/tomono_core.c tests/selftest.c -o build/native-macos/selftest
./build/native-macos/selftest
file build/native-macos/libtomono_core.dylib
file build/native-macos/libtomono_detail.dylib
