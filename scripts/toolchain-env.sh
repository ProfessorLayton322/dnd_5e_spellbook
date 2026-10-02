#!/usr/bin/env bash
# Environment for the user-local Windows and Android build toolchain.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "Source this file, or run scripts/build_all.sh." >&2
  exit 2
fi

toolchain_root="${DND5E_TOOLCHAIN_ROOT:-${HOME}/.local/share/dnd5e-spellbook/toolchain}"
export JAVA_HOME="$toolchain_root/jdk"
export ANDROID_HOME="$toolchain_root/android-sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export NSISDIR="$toolchain_root/nsis/usr/share/nsis"
export PATH="$toolchain_root/python/bin:$JAVA_HOME/bin:$toolchain_root/nsis/usr/bin:$ANDROID_HOME/platform-tools:$PATH"

for required in \
  "$JAVA_HOME/bin/java" \
  "$JAVA_HOME/bin/keytool" \
  "$ANDROID_HOME/platforms/android-35/android.jar" \
  "$ANDROID_HOME/build-tools/35.0.0/aapt2" \
  "$toolchain_root/python/bin/python3.13" \
  "$toolchain_root/nsis/usr/bin/makensis"
do
  if [[ ! -e "$required" ]]; then
    echo "Missing build tool: $required" >&2
    return 1
  fi
done

unset required toolchain_root
