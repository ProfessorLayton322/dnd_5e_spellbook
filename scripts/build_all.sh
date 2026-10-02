#!/usr/bin/env bash
# Build the Windows installer and signed Android APK into dist/.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
source scripts/toolchain-env.sh

python3.13 packaging/windows/build.py
packaging/android/build.sh -Pspellbook.buildPython="$(command -v python3.13)"

printf 'Built packages:\n'
find dist -maxdepth 1 -type f \( -name '*.exe' -o -name '*.apk' \) -printf '  %f (%s bytes)\n' | sort
