import 'package:flutter/material.dart';

import 'app.dart';
import 'config.dart';
import 'state/services.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final services = Services(base: apiBase());
  await services.session.load();
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
