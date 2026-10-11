import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_web_auth_2/flutter_web_auth_2.dart';
import 'package:http/http.dart' as http;

import '../config.dart';
import '../core/api.dart';
import '../core/query.dart';
import '../core/session.dart';
import 'reminders.dart';
import 'sync.dart';

/// Everything the screens share, created once at start-up.
class Services {
  Services({required Uri base, http.Client? client})
      : session = Session(),
        reminders = Reminders() {
    api = Api(base: base, session: session, client: client);
    queries = QueryClient(api);
    sync = SyncController(api, queries);
  }

  final Session session;
  final Reminders reminders;
  late final Api api;
  late final QueryClient queries;
  late final SyncController sync;

  /// Google sign-in in the system browser, returning to the app's deep link. With [consent],
  /// Google asks again for Gmail and Classroom access (after it was declined or revoked).
  /// Returns false when the student closed the sign-in page.
  Future<bool> signIn({bool consent = false}) async {
    final start = (await api.send('POST', '/mobile/auth/start', body: {'consent': consent}, authenticated: false)) as Map;
    final String result;
    try {
      result = await FlutterWebAuth2.authenticate(url: start['url'] as String, callbackUrlScheme: callbackScheme);
    } on PlatformException catch (e) {
      if (e.code == 'CANCELED') return false;
      rethrow;
    }
    final params = Uri.parse(result).queryParameters;
    final code = params['code'];
    if (code == null) {
      throw ApiError(
        'Sign-in could not be completed. Use your verified @somaiya.edu Google account and try again.',
        401,
        code: params['error'],
      );
    }
    final out = (await api.send(
      'POST',
      '/mobile/auth/callback',
      body: {'state': start['state'], 'code': code},
      authenticated: false,
    )) as Map;
    final previous = session.handle;
    await session.signIn(out['session'] as String);
    if (previous != null && previous != session.handle) {
      // Signing in again for consent replaces the session; end the old one quietly.
      try {
        await api.send('POST', '/mobile/auth/logout', bearer: previous, timeout: const Duration(seconds: 10));
      } catch (_) {}
    }
    await queries.invalidateAll();
    return true;
  }

  Future<void> signOut() async {
    await api.send('POST', '/mobile/auth/logout');
    await forget();
  }

  /// Drop everything private kept on this phone.
  Future<void> forget() async {
    sync.stop();
    await reminders.clear();
    await queries.clear();
    await session.clear();
  }
}

class AppScope extends InheritedWidget {
  const AppScope({super.key, required this.services, required super.child});

  final Services services;

  static Services of(BuildContext context) =>
      context.getInheritedWidgetOfExactType<AppScope>()!.services;

  @override
  bool updateShouldNotify(AppScope old) => old.services != services;
}
