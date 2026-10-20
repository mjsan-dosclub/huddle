#!/bin/bash
set -euo pipefail
PROJECT="$(cd "$(dirname "$0")" && pwd)"
SDK="${ANDROID_SDK_ROOT:-$HOME/Library/Android/sdk}"
JAVA_HOME="${JAVA_HOME:-/Library/Java/JavaVirtualMachines/openjdk-17.jdk/libexec/openjdk.jdk/Contents/Home}"
BT="$SDK/build-tools/35.0.1"
ANDROID="$SDK/platforms/android-35/android.jar"
BUILD="${HELLO_ANDROID_BUILD_DIR:-$PROJECT/../../work/hello-android-build}"
mkdir -p "$BUILD/classes" "$BUILD/dex" "$BUILD/resources" "$PROJECT/../downloads"
"$BT/aapt2" compile --dir "$PROJECT/app/src/main/res" -o "$BUILD/resources.zip"
"$BT/aapt2" link -o "$BUILD/resources.apk" --manifest "$PROJECT/app/src/main/AndroidManifest.xml" -I "$ANDROID" "$BUILD/resources.zip" --min-sdk-version 26 --target-sdk-version 35 --java "$BUILD/generated"
find "$BUILD/classes" -type f -name '*.class' -delete
find "$BUILD/dex" -type f -name '*.dex' -delete
find "$PROJECT/app/src/main/java" "$BUILD/generated" -name '*.java' -print > "$BUILD/sources.list"
"$JAVA_HOME/bin/javac" -source 8 -target 8 -encoding UTF-8 -classpath "$ANDROID" -d "$BUILD/classes" @"$BUILD/sources.list"
find "$BUILD/classes" -name '*.class' -print > "$BUILD/classes.list"
JAVA_HOME="$JAVA_HOME" "$BT/d8" --lib "$ANDROID" --min-api 26 --output "$BUILD/dex" @"$BUILD/classes.list"
cp "$BUILD/resources.apk" "$BUILD/unsigned.apk"
(cd "$BUILD/dex" && /usr/bin/zip -q "$BUILD/unsigned.apk" classes*.dex)
"$BT/zipalign" -f 4 "$BUILD/unsigned.apk" "$BUILD/aligned.apk"
if [ ! -f "$BUILD/debug.keystore" ]; then
 "$JAVA_HOME/bin/keytool" -genkeypair -keystore "$BUILD/debug.keystore" -storepass android -keypass android -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 -dname 'CN=HUDDLE Local Test, O=HUDDLE, C=IN'
fi
JAVA_HOME="$JAVA_HOME" "$BT/apksigner" sign --ks "$BUILD/debug.keystore" --ks-pass pass:android --key-pass pass:android --out "$PROJECT/../hello-admin-debug.apk" "$BUILD/aligned.apk"
JAVA_HOME="$JAVA_HOME" "$BT/apksigner" verify --verbose "$PROJECT/../hello-admin-debug.apk"
cp "$PROJECT/../hello-admin-debug.apk" "$PROJECT/../downloads/hello-admin-debug.apk"
cp "$PROJECT/../hello-admin-debug.apk" "$PROJECT/../huddle-android-0.8.0.apk"
shasum -a 256 "$PROJECT/../huddle-android-0.8.0.apk" > "$PROJECT/../huddle-android-0.8.0.apk.sha256"
shasum -a 256 "$PROJECT/../hello-admin-debug.apk" > "$PROJECT/../hello-admin-debug.apk.sha256"
echo "Built HUDDLE: $PROJECT/../huddle-android-0.8.0.apk"
