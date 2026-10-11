import 'dart:async';
import 'dart:ui';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

import '../config.dart';
import '../core/api.dart';
import '../core/session.dart';
import 'notifier.dart';

/// Firebase options for this build, from `--dart-define-from-file=firebase.json` (see README).
/// Builds without them have no push; reminders and the daily summary still work.
FirebaseOptions? firebaseOptions() {
  const apiKey = String.fromEnvironment('FIREBASE_API_KEY');
  const appId = String.fromEnvironment('FIREBASE_APP_ID');
  const sender = String.fromEnvironment('FIREBASE_SENDER_ID');
  const project = String.fromEnvironment('FIREBASE_PROJECT_ID');
  if ([apiKey, appId, sender, project].any((v) => v.isEmpty)) return null;
  return const FirebaseOptions(apiKey: apiKey, appId: appId, messagingSenderId: sender, projectId: project);
}

/// Pushes arriving while DueCare is closed or in the background run here, in their own isolate.
@pragma('vm:entry-point')
Future<void> backgroundPush(RemoteMessage message) async {
  DartPluginRegistrant.ensureInitialized();
  await Firebase.initializeApp(options: firebaseOptions());
  final session = Session();
  await session.load();
  if (!session.signedIn) return;
  final notifier = Notifier();
  await notifier.init();
  await notifier.handlePush(message.data, Api(base: apiBase(), session: session));
}

/// Registers this phone for push and routes pushes that arrive while the app is open.
class Push {
  Push(this.notifier);

  final Notifier notifier;
  bool _started = false;
  String? _token;
  StreamSubscription<String>? _refresh;
  StreamSubscription<RemoteMessage>? _foreground;

  bool get configured => firebaseOptions() != null;

  /// Called once at start-up, before the app runs.
  Future<void> init() async {
    if (!configured) return;
    try {
      await Firebase.initializeApp(options: firebaseOptions());
      FirebaseMessaging.onBackgroundMessage(backgroundPush);
      _started = true;
    } catch (e) {
      debugPrint('Push unavailable: ${e.runtimeType}');
    }
  }

  bool get available => _started;

  /// Register for push with the signed-in session. [onPush] runs for pushes received while the
  /// app is open (after their notification is shown), to refresh what is on screen.
  Future<bool> register(Api api, {required VoidCallback onPush}) async {
    if (!_started) return false;
    final messaging = FirebaseMessaging.instance;
    final permission = await messaging.requestPermission();
    if (permission.authorizationStatus == AuthorizationStatus.denied) return false;
    final token = await messaging.getToken();
    if (token == null) return false;
    _token = token;
    await api.send('POST', '/devices', body: {'token': token, 'platform': 'android'});
    await _refresh?.cancel();
    _refresh = messaging.onTokenRefresh.listen((t) async {
      _token = t;
      try {
        await api.send('POST', '/devices', body: {'token': t, 'platform': 'android'});
      } catch (_) {}
    });
    await _foreground?.cancel();
    _foreground = FirebaseMessaging.onMessage.listen((m) async {
      await notifier.handlePush(m.data, api);
      onPush();
    });
    return true;
  }

  /// Stop pushes to this phone (sign-out). Best effort: a token the server still holds only ever
  /// wakes the app for an account it no longer has, which the app ignores.
  Future<void> unregister(Api api) async {
    await _refresh?.cancel();
    await _foreground?.cancel();
    final token = _token;
    _token = null;
    if (!_started || token == null) return;
    try {
      await api.send('POST', '/devices/unregister', body: {'token': token}).timeout(const Duration(seconds: 10));
    } catch (_) {}
    try {
      await FirebaseMessaging.instance.deleteToken();
    } catch (_) {}
  }
}
