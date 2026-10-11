import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'app.dart';
import 'config.dart';
import 'state/services.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final services = Services(base: apiBase());
  await services.session.load();
  // Debug builds only: start with a session the local browser-test server issued
  // (.local/e2e-account.json), since emulators cannot sign in to a real Somaiya account.
  // kDebugMode is a constant, so release builds do not contain this.
  const devSession = String.fromEnvironment('DEV_SESSION');
  if (kDebugMode && devSession.isNotEmpty && !services.session.signedIn) await services.session.signIn(devSession);
  try {
    await services.notifier.init();
  } catch (_) {
    // Notifications are optional; the workspace works without them.
  }
  await services.push.init();
  // The last saved tasks show at once; fresh data replaces them as it arrives.
  final savedAt = services.session.signedIn ? await services.queries.restore() : null;
  runApp(DueCareApp(services: services, savedAt: savedAt));
}
