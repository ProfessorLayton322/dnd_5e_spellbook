#!/usr/bin/env bash
# Build the signed Android APK into dist/.
#
# Needs JDK 17 (JAVA_HOME), the Android SDK (ANDROID_HOME), and Python 3.13 as
# python3.13 on PATH (or pass -Pspellbook.buildPython=/path/to/python3.13).
# Extra arguments are passed to Gradle.
set -euo pipefail
cd "$(dirname "$0")"

: "${ANDROID_HOME:?Set ANDROID_HOME to the Android SDK directory}"
keytool="${JAVA_HOME:+$JAVA_HOME/bin/}keytool"
signing_dir="${DND5E_SIGNING_DIR:-${HOME}/.local/share/dnd5e-spellbook/signing}"
signing_properties="$signing_dir/keystore.properties"
release_keystore="$signing_dir/release.keystore"

mkdir -p "$signing_dir"
chmod 700 "$signing_dir"
if [ ! -f "$signing_properties" ] || [ ! -f "$release_keystore" ]; then
  # Every update must be signed with this same key, or Android refuses to install it.
  password=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
  "$keytool" -genkeypair -keystore "$release_keystore" -alias spellbook -keyalg RSA -keysize 4096 -validity 10000 \
    -storepass "$password" -keypass "$password" -dname "CN=DnD 5e Spellbook"
  printf 'storeFile=release.keystore\nstorePassword=%s\nkeyAlias=spellbook\nkeyPassword=%s\n' "$password" "$password" > "$signing_properties"
  echo "Created signing files in $signing_dir. Back them up: later versions must use the same key."
fi
chmod 600 "$release_keystore" "$signing_properties"

./gradlew --no-daemon assembleRelease -Pspellbook.keystoreProperties="$signing_properties" "$@"

version=$(sed -n 's/^version = "\(.*\)"/\1/p' ../../pyproject.toml)
mkdir -p ../../dist
cp app/build/outputs/apk/release/app-release.apk "../../dist/DnD5eSpellbook-$version.apk"
echo "Built dist/DnD5eSpellbook-$version.apk"
