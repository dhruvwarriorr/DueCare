import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'core/models.dart';
import 'core/query.dart';
import 'screens/deletion.dart';
import 'screens/sign_in.dart';
import 'screens/workspace.dart';
import 'state/data.dart';
import 'state/quick_complete.dart';
import 'state/services.dart';
import 'ui/theme.dart';

final navigatorKey = GlobalKey<NavigatorState>();

class DueCareApp extends StatefulWidget {
  const DueCareApp({super.key, required this.services, this.savedAt});

  final Services services;
  final DateTime? savedAt;

  @override
  State<DueCareApp> createState() => _DueCareAppState();
}

class _DueCareAppState extends State<DueCareApp> {
  final quick = QuickComplete();
  Services get services => widget.services;

  @override
  void initState() {
    super.initState();
    services.session.addListener(_sessionChanged);
    services.api.onDeleting = _deleting;
  }

  @override
  void dispose() {
    services.session.removeListener(_sessionChanged);
    super.dispose();
  }

  void _sessionChanged() {
    // A session that ends (sign-out, expiry, revocation) takes its cached private data with it.
    if (!services.session.signedIn) services.forget();
    navigatorKey.currentState?.popUntil((r) => r.isFirst);
    setState(() {});
  }

  /// Every screen stops showing private data once account deletion begins.
  Future<void> _deleting() async {
    try {
      final job = (await services.api.get('/privacy/account-deletion')) as Map;
      await services.session.deleting(job['resumeToken'] as String);
    } catch (_) {}
  }

  /// The profile's appearance choice; the saved profile supplies it at launch.
  late String theme = () {
    final me = services.queries.peek(Keys.me);
    return me?.data is Map ? Profile((me!.data as Map).cast<String, dynamic>()).theme : 'system';
  }();

  void _theme(String value) {
    if (value != theme) setState(() => theme = value);
  }

  ThemeMode _themeMode() {
    return switch (theme) {
      'light' => ThemeMode.light,
      'dark' => ThemeMode.dark,
      _ => ThemeMode.system,
    };
  }

  @override
  Widget build(BuildContext context) {
    final session = services.session;
    final Widget home;
    if (session.deletionToken != null) {
      home = const DeletionScreen();
    } else if (!session.signedIn) {
      home = const SignInScreen();
    } else {
      home = Workspace(savedAt: widget.savedAt, onTheme: _theme);
    }
    return AppScope(
      services: services,
      child: QueryScope(
        client: services.queries,
        child: QuickCompleteScope(
          notifier: quick,
          child: MaterialApp(
            title: 'DueCare',
            debugShowCheckedModeBanner: false,
            navigatorKey: navigatorKey,
            theme: duecareTheme(Brightness.light),
            darkTheme: duecareTheme(Brightness.dark),
            themeMode: _themeMode(),
            builder: (context, child) => AnnotatedRegion<SystemUiOverlayStyle>(
              value: Theme.of(context).brightness == Brightness.dark ? SystemUiOverlayStyle.light : SystemUiOverlayStyle.dark,
              child: child!,
            ),
            home: KeyedSubtree(key: ValueKey('${session.signedIn}${session.deletionToken != null}'), child: home),
          ),
        ),
      ),
    );
  }
}
