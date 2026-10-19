# HUDDLE Admin for Android 0.6.1

Native Android views and NFC reader mode; no WebView. Source package `com.hello.cards.admin` remains stable for existing installs. The app supports email/password and authenticator/recovery-code login, organization switching, member/card management, branding/templates, leads, analytics, spreadsheet onboarding and NFC preparation/write/read-back.

Set **Server** to your canonical HTTPS application origin (for example `https://YOUR_PROJECT.vercel.app`, later `https://app.huddle.co.in`). Sign in and select an employee/card. Physical NFC writes require a writable NDEF tag and an NFC-enabled Android device. The recipient opens the URL in their browser; no recipient app is needed.

The server declares the allowed public NFC origin separately from the API origin. Session cookies are sent only to the configured API origin. Google web login is supported by the server when configured; native Google OAuth is not implemented.

## Build a test APK

Install JDK 17, Android SDK platform 35 and build-tools 35.0.1. Set `ANDROID_SDK_ROOT` and `JAVA_HOME` if necessary, then run `bash android/build.sh` from the repository root.

Build intermediates and the generated debug signing key stay in `android/build` (ignored). Set `HELLO_ANDROID_BUILD_DIR` to your existing private build folder to preserve the old development signing key. Never commit or distribute a signing key. The generated APK is copied to `downloads/hello-admin-debug.apk` for the web download route; root APK aliases are ignored by Git.

These are test APKs, not Play Store release builds. Use a private production signing workflow and review release/distribution requirements before store submission. Cleartext HTTP remains available for local development testing only. Images are capped at 3 MB to match the Vercel API.
