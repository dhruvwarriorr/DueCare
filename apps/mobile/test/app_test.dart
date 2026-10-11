import 'dart:convert';

import 'package:duecare/app.dart';
import 'package:duecare/core/ist.dart';
import 'package:duecare/state/services.dart';
import 'package:duecare/ui/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

final now = DateTime.now().toUtc();
String inHours(int h) => now.add(Duration(hours: h)).toIso8601String();

Map<String, dynamic> task(String id, String title, {String status = 'due', String? dueAt, String? subject}) => {
      'id': id,
      'revision': 1,
      'title': title,
      'type': 'assignment',
      'status': status,
      'priority': 'high',
      'subjectId': subject == null ? null : 's1',
      'subjectName': subject,
      'dueAt': dueAt,
      'dueDate': null,
      'createdAt': now.toIso8601String(),
      'source': 'gmail',
      'sources': ['gmail'],
      'instructions': 'Draw the ER diagram for the library system.',
      'notes': '',
      'completedAt': status == 'completed' ? now.toIso8601String() : null,
    };

final profile = {
  'id': 'u1',
  'revision': 3,
  'identity': {'id': 'u1', 'email': 'student@somaiya.edu', 'name': 'Asha Rao', 'photo': null},
  'onboardingComplete': true,
  'theme': 'light',
  'ignoreKtNotices': false,
  'branchCode': 'COMPS',
  'classYear': 'SY',
  'currentSemester': 3,
  'division': 'A',
  'generalBatch': 'A1',
  'rollNumber': '01',
  'branchOptions': [
    {'code': 'COMPS', 'name': 'Computer Engineering'},
  ],
};

final upcoming = task('t1', 'DBMS ER diagram', dueAt: inHours(30), subject: 'DBMS');
final missed = task('t2', 'OS write-up', status: 'missed', dueAt: now.subtract(const Duration(hours: 2)).toIso8601String());

http.Response json(Object body, [int status = 200]) => http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});

/// Every request the fake server received, newest last.
final requests = <http.Request>[];
Map<String, dynamic> notifySettings = {};

Future<http.Response> fakeApi(http.Request r) async {
  requests.add(r);
  final path = r.url.path.replaceFirst('/api/v1', '');
  final page = {'items': <Object>[], 'nextCursor': null};
  if (path == '/notification-settings' && r.method == 'PUT') {
    notifySettings = (jsonDecode(r.body) as Map)['settings'] as Map<String, dynamic>;
  }
  return switch (path) {
    '/me' => json(profile),
    '/changes' => json({'version': 'v1', 'at': now.toIso8601String()}),
    '/overview' => json({
        'counts': {'due': 1, 'missed': 1, 'completed': 0},
        'undated': 0,
        'hidden': 0,
        'tasks': [upcoming],
        'reviewCount': 2,
        'sync': {},
      }),
    '/activity' => json({...page, 'unreadCount': 3}),
    '/tasks' => json({'items': [upcoming, missed], 'nextCursor': null}),
    '/tasks/t1' => json(upcoming),
    '/tasks/t1/evidence' => json(page),
    '/subjects' => json({
        'items': [
          {'id': 's1', 'revision': 1, 'name': 'DBMS', 'kind': 'theory', 'aliases': <String>[]},
        ],
        'nextCursor': null,
      }),
    '/subjects/s1/timetable' => json({
        'revision': 1,
        'slots': [
          {'id': 'x1', 'weekday': weekdayOf(todayKey()), 'startTime': '09:00', 'endTime': '10:00', 'location': '601'},
        ],
      }),
    '/connections' => json(page),
    '/notification-settings' => json({
        'revision': 1,
        'settings': {'reminderLeads': [1440, 60], ...notifySettings},
        'push': {'configured': false, 'devices': 0},
      }),
    _ => json(page),
  };
}

/// A phone-sized screen (390 × 1400 logical pixels), so lists build their first rows.
void phone(WidgetTester tester) {
  tester.view.physicalSize = const Size(1170, 4200);
  tester.view.devicePixelRatio = 3;
  addTearDown(tester.view.reset);
}

/// Unmount and let the cache's debounced save run, so no timer outlives the test.
Future<void> finish(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox());
  await tester.pump(const Duration(seconds: 5));
}

Future<Services> signedIn() async {
  FlutterSecureStorage.setMockInitialValues({'duecare.session': 'handle-1'});
  SharedPreferences.setMockInitialValues({});
  final services = Services(base: Uri.parse('https://duecare.test'), client: MockClient(fakeApi));
  await services.session.load();
  return services;
}

/// Settle, failing fast instead of waiting minutes when something keeps animating.
Future<void> settle(WidgetTester tester) =>
    tester.pumpAndSettle(const Duration(milliseconds: 100), EnginePhase.sendSemanticsUpdate, const Duration(seconds: 10));

void main() {
  setUpAll(() => fetchFonts = false);

  setUp(() {
    requests.clear();
    notifySettings = {};
  });

  testWidgets('signed out, the app offers Google sign-in', (tester) async {
    FlutterSecureStorage.setMockInitialValues({});
    SharedPreferences.setMockInitialValues({});
    final services = Services(base: Uri.parse('https://duecare.test'), client: MockClient(fakeApi));
    await services.session.load();
    phone(tester);
    await tester.pumpWidget(DueCareApp(services: services));
    await settle(tester);
    expect(find.text('Everything due,\nin one place.', findRichText: true), findsOneWidget);
    expect(find.text('Continue with Google'), findsOneWidget);
    expect(find.textContaining('@somaiya.edu'), findsOneWidget);
    await finish(tester);
  });

  testWidgets('the week shows the next deadline, counts, today’s due work and classes', (tester) async {
    final services = await signedIn();
    phone(tester);
    await tester.pumpWidget(DueCareApp(services: services));
    await settle(tester);

    expect(find.text('Next due'), findsOneWidget);
    expect(find.text('DBMS ER diagram'), findsWidgets);
    expect(find.text('This week'), findsOneWidget);
    expect(find.text('To review'), findsOneWidget);
    expect(find.text('Classes'), findsOneWidget);
    expect(find.text('09:00'), findsOneWidget);
    expect(find.text('Theory · 601'), findsOneWidget);
    // Notification choices are fetched and kept for the background.
    expect(requests.any((r) => r.url.path.endsWith('/notification-settings')), isTrue);

    await tester.tap(find.text('Tasks').last);
    await settle(tester);
    expect(find.text('OS write-up'), findsOneWidget);
    expect(find.text('missed'), findsWidgets);

    await tester.tap(find.text('DBMS ER diagram').last);
    await settle(tester);
    expect(find.text('Mark as done'), findsOneWidget);
    final instructions = find.byWidgetPredicate((w) => w is SelectableText && w.data == 'Draw the ER diagram for the library system.');
    await tester.scrollUntilVisible(instructions, 200, scrollable: find.byType(Scrollable).last);
    expect(instructions, findsOneWidget);
    await tester.tap(find.text('Mark as done'));
    await settle(tester);
    final patch = requests.lastWhere((r) => r.method == 'PATCH');
    expect(jsonDecode(patch.body), {'revision': 1, 'status': 'completed'});
    await finish(tester);
  });

  testWidgets('tasks swipe to done, and long-press selects for bulk actions', (tester) async {
    final services = await signedIn();
    phone(tester);
    await tester.pumpWidget(DueCareApp(services: services));
    await settle(tester);
    await tester.tap(find.text('Tasks').last);
    await settle(tester);

    await tester.drag(find.text('DBMS ER diagram').last, const Offset(500, 0));
    await settle(tester);
    final patch = requests.lastWhere((r) => r.method == 'PATCH');
    expect(patch.url.path, '/api/v1/tasks/t1');
    expect(jsonDecode(patch.body)['status'], 'completed');
    expect(find.text('Marked done: DBMS ER diagram'), findsOneWidget);

    await tester.longPress(find.text('OS write-up'));
    await settle(tester);
    expect(find.text('1 selected'), findsOneWidget);
    await tester.tap(find.text('Done').last);
    await settle(tester);
    final bulk = requests.lastWhere((r) => r.url.path.endsWith('/tasks/bulk'));
    expect(jsonDecode(bulk.body), {'taskIds': ['t2'], 'action': 'complete'});
    await finish(tester);
  });

  testWidgets('More lists every part of the app; notification choices save', (tester) async {
    final services = await signedIn();
    phone(tester);
    await tester.pumpWidget(DueCareApp(services: services));
    await settle(tester);
    await tester.tap(find.text('More'));
    await settle(tester);
    for (final label in ['Subjects', 'Activity', 'Notifications', 'Profile', 'Sources', 'Rules', 'Privacy & data', 'Sign out']) {
      expect(find.text(label), findsWidgets);
    }
    expect(find.text('Asha Rao'), findsOneWidget);
    expect(find.text('SY · COMPS · Div A · Batch A1'), findsOneWidget);

    await tester.tap(find.text('Notifications'));
    await settle(tester);
    expect(find.text('Remind me before deadlines'), findsOneWidget);
    expect(find.text('Instant updates'), findsOneWidget);
    await tester.tap(find.text('30 minutes before'));
    await tester.tap(find.text('Morning summary'));
    await tester.pump(const Duration(seconds: 1));
    await settle(tester);
    final put = requests.lastWhere((r) => r.method == 'PUT');
    final saved = (jsonDecode(put.body) as Map)['settings'] as Map;
    expect(saved['reminderLeads'], [1440, 60, 30]);
    expect(saved['digest'], isTrue);
    expect(find.text('At 08:00'), findsOneWidget);
    await finish(tester);
  });
}
