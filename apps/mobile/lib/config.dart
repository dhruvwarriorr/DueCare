import 'dart:io';

/// The DueCare API origin. Release builds pass it at build time:
///   flutter build apk --dart-define=API_URL=https://duecare-xi.vercel.app
/// Without it, debug builds use the local API (`uvicorn ... --port 8000`): the Android
/// emulator reaches the host computer at 10.0.2.2, the iOS simulator at 127.0.0.1.
Uri apiBase() {
  const configured = String.fromEnvironment('API_URL');
  if (configured.isNotEmpty) return Uri.parse(configured);
  return Uri.parse(Platform.isAndroid ? 'http://10.0.2.2:8000' : 'http://127.0.0.1:8000');
}

/// The deep link Supabase returns to after Google sign-in. It must match the API's
/// MOBILE_REDIRECT_URL, the Android CallbackActivity scheme and the iOS URL type.
const callbackScheme = 'duecare';
