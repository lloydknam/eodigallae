#!/usr/bin/env bash
# Gradle 없이 안드로이드 SDK 기본 도구만으로 APK를 만든다 (GitHub Actions 우분투 러너에 SDK가 이미 깔려 있음).
set -euo pipefail
cd "$(dirname "$0")"
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-/usr/local/lib/android/sdk}}"
BT="$SDK/build-tools/$(ls "$SDK/build-tools" | sort -V | tail -1)"
PLAT=""
for v in 34 35 36 33; do [ -f "$SDK/platforms/android-$v/android.jar" ] && { PLAT="$SDK/platforms/android-$v/android.jar"; break; }; done
[ -n "$PLAT" ] || PLAT="$(ls -d "$SDK"/platforms/android-*/android.jar | sort -V | tail -1)"
echo "build-tools: $BT"; echo "platform: $PLAT"
rm -rf build && mkdir -p build/gen build/obj
"$BT/aapt2" compile --dir res -o build/res.zip
"$BT/aapt2" link -o build/base.apk -I "$PLAT" --manifest AndroidManifest.xml -R build/res.zip --java build/gen --auto-add-overlay
javac -encoding UTF-8 -source 8 -target 8 -bootclasspath "$PLAT" -classpath "$PLAT" -d build/obj \
  $(find src build/gen -name '*.java') 2>&1 | grep -v "bootstrap classpath\|^warning\|^1 warning\|options were" || true
"$BT/d8" --release --min-api 24 --lib "$PLAT" --output build $(find build/obj -name '*.class')
cp build/base.apk build/unsigned.apk
(cd build && zip -qj unsigned.apk classes.dex)
"$BT/zipalign" -f -p 4 build/unsigned.apk build/aligned.apk
KS=build/key.jks
if [ -n "${ANDROID_KEYSTORE_B64:-}" ]; then
  echo "$ANDROID_KEYSTORE_B64" | base64 -d > "$KS"
else
  keytool -genkeypair -keystore "$KS" -storepass eodigallae -keypass eodigallae -alias app \
    -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Eodigallae, O=lloydknam, C=KR" >/dev/null 2>&1
fi
mkdir -p ../download
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:${ANDROID_KEYSTORE_PASS:-eodigallae} --ks-key-alias app \
  --out ../download/eodigallae.apk build/aligned.apk
"$BT/apksigner" verify ../download/eodigallae.apk
ls -l ../download/eodigallae.apk
