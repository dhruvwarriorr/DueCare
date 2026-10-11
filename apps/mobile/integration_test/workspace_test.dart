import 'package:duecare/app.dart';
import 'package:duecare/config.dart';
import 'package:duecare/core/query.dart';
import 'package:duecare/main.dart' as app;
import 'package:duecare/screens/workspace.dart';
import 'package:duecare/state/services.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:http/http.dart' as http;

/// Real HTTP while online; a deterministic connection failure for the offline phase.
class NetworkClient extends http.BaseClient {
  final http.Client _client = http.Client();
  bool offline = false;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) {
    if (offline) {
      throw http.ClientException('Simulated offline transport', request.url);
    }
    return _client.send(request);
  }

  @override
  void close() => _client.close();
}

/// Run only against the local synthetic API, with a disposable signed-in fixture.
/// DEV_SESSION is supplied through an ignored dart-define file, never this source.
void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('Android workspace and task lifecycle against the local API', (
    tester,
  ) async {
    const api = String.fromEnvironment('API_URL');
    expect(
      Uri.parse(api).host,
      '10.0.2.2',
      reason: 'This test must use the emulator host and synthetic API.',
    );
    expect(Uri.parse(api).port, 8001);
    expect(const String.fromEnvironment('DEV_SESSION'), isNotEmpty);
    await app.main();

    Future<void> settle() => tester.pumpAndSettle(
      const Duration(milliseconds: 100),
      EnginePhase.sendSemanticsUpdate,
      const Duration(seconds: 30),
    );
    Future<void> waitFor(Finder finder) async {
      final until = DateTime.now().add(const Duration(seconds: 30));
      while (finder.evaluate().isEmpty && DateTime.now().isBefore(until)) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      expect(finder, findsWidgets);
    }

    Future<void> tap(String text) async {
      await tester.tap(find.text(text).last);
      await settle();
    }

    Future<void> back() async {
      await tester.pageBack();
      await settle();
    }

    Future<void> shot(String name) async {
      debugPrint('QA screenshot: $name');
      await tester.pump(const Duration(milliseconds: 300));
      await binding.takeScreenshot(name);
    }

    await settle();
    await binding.convertFlutterSurfaceToImage();
    await settle();
    await shot('00-startup');
    await waitFor(find.text('This week'));
    expect(find.text('This week'), findsOneWidget);
    expect(find.text('DBMS ER diagram'), findsWidgets);
    await shot('01-week');
    final services = AppScope.of(tester.element(find.byType(Shell)));

    await tap('Tasks');
    expect(find.text('All tasks'), findsOneWidget);
    expect(find.textContaining('OS write-up'), findsOneWidget);
    await shot('02-tasks');
    await tester.tap(find.bySemanticsLabel('Mark done: DBMS ER diagram'));
    await settle();
    expect(find.text('Marked done: DBMS ER diagram'), findsOneWidget);
    await tap('Undo');
    await tester.tap(find.textContaining('DBMS ER diagram').last);
    await settle();
    expect(find.text('Task details'), findsOneWidget);
    await shot('03-task-details');
    await tap('Mark completed');
    expect(find.text('Reopen task'), findsOneWidget);
    await tap('Reopen task');
    expect(find.text('Mark completed'), findsOneWidget);
    await back();

    final title = 'Emulator lifecycle ${DateTime.now().millisecondsSinceEpoch}';
    await tester.tap(find.bySemanticsLabel('Add task'));
    await settle();
    await tap('Save task');
    expect(find.text('Add a title'), findsOneWidget);
    await tester.enterText(find.byType(TextField).first, title);
    await tap('Save task');
    expect(find.text('All tasks'), findsOneWidget);
    var page = await services.api.get(
      '/tasks?q=${Uri.encodeQueryComponent(title)}',
    ) as Map;
    expect((page['items'] as List).length, 1);
    final id = ((page['items'] as List).single as Map)['id'] as String;

    await tester.enterText(find.byType(TextField).first, title);
    await tester.pump(const Duration(milliseconds: 400));
    await settle();
    await tester.tap(find.textContaining(title).last);
    await settle();
    await tap('Edit');
    await tester.enterText(find.byType(TextField).first, '$title edited');
    await tap('Save task');
    expect(find.text('$title edited'), findsOneWidget);
    final edited = await services.api.get('/tasks/$id') as Map;
    expect(edited['title'], '$title edited');
    await shot('04-created-and-edited');
    await back();
    await tap('Review');
    expect(find.text('Needs attention'), findsOneWidget);
    expect(
      find.text('Synthetic review: keep your current assignment details?'),
      findsOneWidget,
    );
    await shot('05-review');
    await tester.scrollUntilVisible(
      find.text('Keep current'),
      200,
      scrollable: find.byType(Scrollable).last,
    );
    await tap('Keep current');
    expect(find.text('Nothing needs your attention'), findsOneWidget);
    await shot('06-review-resolved');

    await tap('More');
    expect(find.text('Test Student'), findsOneWidget);
    await shot('07-more');
    for (final (label, screenshot) in [
      ('Subjects', '08-subjects'),
      ('Profile & privacy', '09-profile'),
      ('Sources', '10-sources'),
      ('Rules', '11-rules'),
      ('Activity', '12-activity'),
    ]) {
      await tap(label);
      await shot(screenshot);
      await back();
    }

    // Exercise deletion through the UI, only for the disposable task created above.
    await tap('Tasks');
    await tester.enterText(find.byType(TextField).first, title);
    await tester.pump(const Duration(milliseconds: 400));
    await settle();
    await tester.tap(find.textContaining('$title edited').last);
    await settle();
    await tap('Delete');
    await tap('Confirm deletion');
    page = await services.api.get(
      '/tasks?q=${Uri.encodeQueryComponent(title)}',
    ) as Map;
    expect(page['items'], isEmpty);
    expect(tester.takeException(), isNull);
    // Finish this instance's debounced persistence before simulating a new process.
    // A real process restart cannot leave the old instance's timer running.
    await tester.pump(const Duration(seconds: 3));
  });

  testWidgets('saved workspace survives connection failure and recovers', (
    tester,
  ) async {
    final client = NetworkClient()..offline = true;
    final services = Services(base: apiBase(), client: client);
    await services.session.load();
    expect(services.session.signedIn, isTrue);
    await services.reminders.init();
    final savedAt = await services.queries.restore();
    expect(
      savedAt,
      isNotNull,
      reason: 'The online test must have saved a workspace on this device.',
    );
    runApp(DueCareApp(services: services, savedAt: savedAt));
    Future<void> settle() => tester.pumpAndSettle(
      const Duration(milliseconds: 100),
      EnginePhase.sendSemanticsUpdate,
      const Duration(seconds: 30),
    );
    await settle();
    await binding.convertFlutterSurfaceToImage();
    await settle();
    expect(find.text('This week'), findsOneWidget);
    expect(find.text('DBMS ER diagram'), findsWidgets);
    expect(
      find.textContaining('Can’t reach DueCare right now'),
      findsOneWidget,
    );
    await binding.takeScreenshot('13-offline-week');
    await tester.tap(find.text('Tasks').last);
    await settle();
    expect(find.textContaining('OS write-up'), findsOneWidget);
    await binding.takeScreenshot('14-offline-tasks');

    client.offline = false;
    await services.queries.invalidateAll();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    final until = DateTime.now().add(const Duration(seconds: 10));
    while (find
            .textContaining('Can’t reach DueCare right now')
            .evaluate()
            .isNotEmpty &&
        DateTime.now().isBefore(until)) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    await settle();
    expect(find.textContaining('Can’t reach DueCare right now'), findsNothing);
    expect(find.textContaining('OS write-up'), findsOneWidget);
    await binding.takeScreenshot('15-recovered');

    // Local session removal must also remove the private saved workspace.
    await services.forget();
    await settle();
    expect(find.text('Continue with Google'), findsOneWidget);
    expect(await QueryClient(services.api).restore(), isNull);
    await binding.takeScreenshot('16-signed-out');
    expect(tester.takeException(), isNull);
    client.close();
  });
}
