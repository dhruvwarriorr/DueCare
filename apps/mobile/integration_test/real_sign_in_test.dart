import 'package:duecare/config.dart';
import 'package:duecare/core/session.dart';
import 'package:duecare/main.dart' as app;
import 'package:duecare/screens/sign_in.dart';
import 'package:duecare/state/services.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

/// Interactive acceptance test: a person completes Google sign-in and consent
/// in the emulator. No credentials, Google pages, or consent are automated.
void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  // Set before the test starts: the binding checks this value before tearDown.
  binding.shouldPropagateDevicePointerEvents = true;
  testWidgets('real Google login returns a working mobile session', (
    tester,
  ) async {
    expect(apiBase().origin, 'https://duecare-xi.vercel.app');
    expect(const String.fromEnvironment('DEV_SESSION'), isEmpty);
    await app.main();
    await tester.pump();
    final services = tester.widget<AppScope>(find.byType(AppScope)).services;
    if (const bool.fromEnvironment('REQUIRE_SAVED_SESSION')) {
      expect(
        services.session.signedIn,
        isTrue,
        reason: 'The session was not restored after restarting the app.',
      );
    }
    final until = DateTime.now().add(const Duration(seconds: 45));
    while (!services.session.signedIn &&
        find.byType(SignInScreen).evaluate().isEmpty &&
        DateTime.now().isBefore(until)) {
      await tester.pump(const Duration(milliseconds: 200));
    }
    if (!services.session.signedIn) {
      expect(find.byType(SignInScreen), findsOneWidget);
      final button = find.text('Continue with Google');
      await tester.ensureVisible(button);
      await tester.tap(button);
      await tester.pump();
      debugPrint(
        'REAL_AUTH: Waiting for the user to finish Google sign-in on the emulator.',
      );
    } else {
      debugPrint(
        'REAL_AUTH: Restored the saved session after restarting the app.',
      );
    }
    final deadline = DateTime.now().add(const Duration(minutes: 12));
    while (!services.session.signedIn && DateTime.now().isBefore(deadline)) {
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(seconds: 1)),
      );
      await tester.pump();
      if (find
          .textContaining('Sign-in could not be completed')
          .evaluate()
          .isNotEmpty) {
        fail('The app reported that sign-in could not be completed.');
      }
    }
    expect(
      services.session.signedIn,
      isTrue,
      reason: 'Google sign-in did not return an app session.',
    );
    final me = await tester.runAsync(() => services.api.get('/me')) as Map;
    final identity = me['identity'] as Map;
    expect((identity['email'] as String).endsWith('@somaiya.edu'), isTrue);
    final savedSession = Session();
    await tester.runAsync(savedSession.load);
    expect(savedSession.handle, services.session.handle);
    debugPrint(
      'REAL_AUTH: Callback redeemed; secure session saved; authenticated /me succeeded for somaiya.edu.',
    );
    await tester.pumpAndSettle();
    expect(find.byType(SignInScreen), findsNothing);
    expect(tester.takeException(), isNull);
  }, timeout: const Timeout(Duration(minutes: 15)));
}
