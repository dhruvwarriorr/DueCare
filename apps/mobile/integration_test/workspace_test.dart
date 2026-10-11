import 'package:duecare/app.dart';
import 'package:duecare/config.dart';
import 'package:duecare/core/query.dart';
import 'package:duecare/main.dart' as app;
import 'package:duecare/notifications/notifier.dart';
import 'package:duecare/screens/workspace.dart';
import 'package:duecare/state/services.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:integration_test/integration_test.dart';

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

  Future<void> Function() settler(WidgetTester tester) => () => tester.pumpAndSettle(
        const Duration(milliseconds: 100),
        EnginePhase.sendSemanticsUpdate,
        const Duration(seconds: 30),
      );

  testWidgets('Android workspace, task lifecycle and notifications against the local API', (tester) async {
    const api = String.fromEnvironment('API_URL');
    expect(Uri.parse(api).host, '10.0.2.2', reason: 'This test must use the emulator host and synthetic API.');
    expect(Uri.parse(api).port, 8001);
    expect(const String.fromEnvironment('DEV_SESSION'), isNotEmpty);
    await app.main();
    final settle = settler(tester);

    Future<void> waitFor(Finder finder) async {
      final until = DateTime.now().add(const Duration(seconds: 30));
      while (finder.evaluate().isEmpty && DateTime.now().isBefore(until)) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      expect(finder, findsWidgets);
    }

    // Scroll the target into view first, as a person would on a phone.
    Future<void> tap(String text) async {
      // A long list builds lazily (more so with large text): scroll back up to find the row.
      final lists = find.byType(Scrollable);
      if (find.text(text).evaluate().isEmpty && lists.evaluate().isNotEmpty) {
        await tester.scrollUntilVisible(find.text(text), -200, scrollable: lists.last);
      }
      await tester.ensureVisible(find.text(text).last);
      await tester.pumpAndSettle();
      await tester.tap(find.text(text).last);
      await settle();
    }

    Future<void> tapTooltip(String tooltip) async {
      await tester.tap(find.byTooltip(tooltip).last);
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
    await waitFor(find.text('This week'));
    expect(find.text('DBMS ER diagram'), findsWidgets);
    expect(find.text('Next due'), findsOneWidget);
    await shot('01-week');
    final services = AppScope.of(tester.element(find.byType(Shell)));
    // Remove tasks an interrupted earlier run may have left behind.
    for (final prefix in ['Emulator lifecycle', 'Pushed assignment']) {
      final stale = await services.api.get('/tasks?q=${Uri.encodeQueryComponent(prefix)}') as Map;
      for (final t in (stale['items'] as List).cast<Map>()) {
        await services.api.send('DELETE', '/tasks/${t['id']}?revision=${t['revision']}');
      }
    }

    // Tasks: quick completion with Undo, details, completing and reopening.
    await tap('Tasks');
    expect(find.textContaining('OS write-up'), findsOneWidget);
    await shot('02-tasks');
    await tester.tap(find.bySemanticsLabel('Mark done: DBMS ER diagram'));
    await settle();
    expect(find.text('Marked done: DBMS ER diagram'), findsOneWidget);
    await tap('Undo');
    await tester.tap(find.text('DBMS ER diagram').last);
    await settle();
    await shot('03-task-details');
    await tap('Mark as done');
    expect(find.text('Reopen task'), findsOneWidget);
    await tap('Reopen task');
    expect(find.text('Mark as done'), findsOneWidget);
    await back();

    // Create with validation, search, open and edit.
    final title = 'Emulator lifecycle ${DateTime.now().millisecondsSinceEpoch}';
    await tapTooltip('Add task');
    await shot('04-editor');
    await tap('Save');
    expect(find.text('Give the task a name'), findsOneWidget);
    await tester.enterText(find.byType(TextField).first, title);
    await tap('Tomorrow');
    await tap('Save');
    var page = await services.api.get('/tasks?q=${Uri.encodeQueryComponent(title)}') as Map;
    expect((page['items'] as List).length, 1);
    final id = ((page['items'] as List).single as Map)['id'] as String;
    await tapTooltip('Search');
    await tester.enterText(find.byType(TextField).first, title);
    await tester.pump(const Duration(milliseconds: 500));
    await settle();
    await tester.tap(find.text(title).last);
    await settle();
    await tapTooltip('Edit');
    await tester.enterText(find.byType(TextField).first, '$title edited');
    await tap('Save');
    expect(find.text('$title edited'), findsOneWidget);
    expect((await services.api.get('/tasks/$id') as Map)['title'], '$title edited');
    await back();

    // Review.
    await tap('Review');
    expect(find.text('Synthetic review: keep your current assignment details?'), findsOneWidget);
    await shot('05-review');
    await tester.scrollUntilVisible(find.text('Keep current'), 200, scrollable: find.byType(Scrollable).last);
    await tap('Keep current');
    expect(find.text('All clear'), findsOneWidget);

    // More and every settings page.
    await tap('More');
    expect(find.text('Test Student'), findsOneWidget);
    await shot('06-more');
    for (final (label, screenshot) in [
      ('Subjects', '07-subjects'),
      ('Profile', '08-profile'),
      ('Sources', '09-sources'),
      ('Rules', '10-rules'),
      ('Privacy & data', '11-privacy'),
      ('Activity', '12-activity'),
    ]) {
      await tap(label);
      await shot(screenshot);
      await back();
    }

    // Notifications: settings save to the server and rebuild the phone's schedule.
    // Start from the defaults, whatever an earlier run chose.
    final current = await services.api.get('/notification-settings') as Map;
    await services.api.send('PUT', '/notification-settings', body: {'revision': current['revision'], 'settings': <String, dynamic>{}});
    await tap('Notifications');
    await waitFor(find.text('Remind me before deadlines'));
    await shot('13-notifications');
    await tap('30 minutes before');
    await tester.pump(const Duration(seconds: 2));
    await settle();
    final saved = await services.api.get('/notification-settings') as Map;
    expect((saved['settings'] as Map)['reminderLeads'], [1440, 60, 30]);
    // Saving refreshes the schedule in the background; let it finish.
    final until = DateTime.now().add(const Duration(seconds: 15));
    var pending = await services.notifier.pending();
    while (!pending.any((n) => n.title == 'Due in 30 minutes: DBMS ER diagram') && DateTime.now().isBefore(until)) {
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 300)));
      pending = await services.notifier.pending();
    }
    final titles = pending.map((n) => n.title).toList();
    debugPrint('QA pending reminders: $titles');
    expect(titles, containsAll(['Due in 1 day: DBMS ER diagram', 'Due in 1 hour: DBMS ER diagram', 'Due in 30 minutes: DBMS ER diagram']));
    expect(titles.where((t) => t!.contains('OS write-up')), isEmpty, reason: 'Past deadlines get no reminders.');

    // A local test notification reaches the shade.
    await tester.scrollUntilVisible(find.text('Send a test notification'), 200, scrollable: find.byType(Scrollable).last);
    await tap('Send a test notification');
    var active = await services.notifier.active();
    expect(active.map((n) => n.title), contains('DueCare notifications are on'));

    // The push path: new work arrives on the server; handling the push shows it by name.
    final pushed = 'Pushed assignment ${DateTime.now().millisecondsSinceEpoch}';
    // The synthetic server stands in for an import that found new work in Gmail.
    await services.api.send('POST', '/test/synthetic-import', body: {'title': pushed});
    final me = await services.api.get('/me') as Map;
    await services.notifier.handlePush({'type': 'activity', 'u': ownerHash(me['id'] as String)}, services.api);
    active = await services.notifier.active();
    debugPrint('QA active notifications: ${active.map((n) => '${n.channelId}: ${n.title}').toList()}');
    expect(active.map((n) => n.title), contains('New: $pushed'));
    expect(active.map((n) => n.title).where((t) => t!.startsWith('Reopened') || t.contains('Emulator lifecycle')), isEmpty,
        reason: 'The student’s own changes are not announced back to them.');
    // A push meant for another account on this phone is ignored.
    final before = active.length;
    await services.notifier.handlePush({'type': 'test', 'u': ownerHash('someone-else')}, services.api);
    expect((await services.notifier.active()).length, before);
    await shot('14-notifications-sent');
    await back();

    // Clean up the disposable tasks through the UI and the API.
    await tap('Tasks');
    await shot('15-tasks-before-cleanup');
    if (find.byType(TextField).evaluate().isEmpty) await tapTooltip('Search');
    await tester.enterText(find.byType(TextField).first, title);
    await tester.pump(const Duration(milliseconds: 500));
    await settle();
    await tester.tap(find.text('$title edited').last);
    await settle();
    await tapTooltip('More');
    await tap('Delete task');
    await tap('Delete');
    page = await services.api.get('/tasks?q=${Uri.encodeQueryComponent(title)}') as Map;
    expect(page['items'], isEmpty);
    final extra = await services.api.get('/tasks?q=${Uri.encodeQueryComponent(pushed)}') as Map;
    for (final t in (extra['items'] as List).cast<Map>()) {
      await services.api.send('DELETE', '/tasks/${t['id']}?revision=${t['revision']}');
    }
    expect(tester.takeException(), isNull);
    // Finish this instance's debounced persistence before simulating a new process.
    await tester.pump(const Duration(seconds: 3));
  });

  testWidgets('saved workspace survives connection failure and recovers', (tester) async {
    final client = NetworkClient()..offline = true;
    final services = Services(base: apiBase(), client: client);
    await services.session.load();
    expect(services.session.signedIn, isTrue);
    await services.notifier.init();
    final savedAt = await services.queries.restore();
    expect(savedAt, isNotNull, reason: 'The online test must have saved a workspace on this device.');
    runApp(DueCareApp(services: services, savedAt: savedAt));
    final settle = settler(tester);
    await settle();
    await binding.convertFlutterSurfaceToImage();
    await settle();
    expect(find.text('This week'), findsOneWidget);
    expect(find.text('DBMS ER diagram'), findsWidgets);
    expect(find.textContaining('Offline'), findsOneWidget);
    await binding.takeScreenshot('16-offline-week');
    await tester.tap(find.text('Tasks').last);
    await settle();
    await binding.takeScreenshot('16-offline-tasks');
    final list = find.byWidgetPredicate((w) => w is Scrollable && w.axisDirection == AxisDirection.down);
    await tester.scrollUntilVisible(find.textContaining('OS write-up'), 200, scrollable: list.first);
    expect(find.textContaining('OS write-up'), findsOneWidget);

    client.offline = false;
    await services.queries.invalidateAll();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    final until = DateTime.now().add(const Duration(seconds: 10));
    while (find.textContaining('Offline').evaluate().isNotEmpty && DateTime.now().isBefore(until)) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    await settle();
    expect(find.textContaining('Offline'), findsNothing);
    expect(find.textContaining('OS write-up'), findsOneWidget);
    await binding.takeScreenshot('17-recovered');

    // Local session removal also removes the private saved workspace and scheduled reminders.
    await services.forget();
    await settle();
    expect(find.text('Continue with Google'), findsOneWidget);
    expect(await QueryClient(services.api).restore(), isNull);
    expect(await services.notifier.pending(), isEmpty);
    await binding.takeScreenshot('18-signed-out');
    expect(tester.takeException(), isNull);
    client.close();
  });
}
