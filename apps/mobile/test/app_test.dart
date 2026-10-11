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

Future<http.Response> fakeApi(http.Request r) async {
  final path = r.url.path.replaceFirst('/api/v1', '');
  final page = {'items': <Object>[], 'nextCursor': null};
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

  testWidgets('signed out, the app offers Google sign-in', (tester) async {
    FlutterSecureStorage.setMockInitialValues({});
    SharedPreferences.setMockInitialValues({});
    final services = Services(base: Uri.parse('https://duecare.test'), client: MockClient(fakeApi));
    await services.session.load();
    phone(tester);
    await tester.pumpWidget(DueCareApp(services: services));
    await settle(tester);
    expect(find.text('Everything due, on one week.', findRichText: true), findsOneWidget);
    await tester.scrollUntilVisible(find.text('Continue with Google'), 200);
    expect(find.textContaining('@somaiya.edu'), findsOneWidget);
    await finish(tester);
  });

  testWidgets('the week shows the next deadline, counts, today’s due work and classes', (tester) async {
    final services = await signedIn();
    phone(tester);
    await tester.pumpWidget(DueCareApp(services: services));
    await settle(tester);

    expect(find.text('NEXT DUE'), findsOneWidget);
    expect(find.text('DBMS ER diagram'), findsWidgets);
    expect(find.text('This week'), findsOneWidget);
    expect(find.text('to review'), findsOneWidget);
    expect(find.text('Classes'.toUpperCase()), findsOneWidget);
    expect(find.text('09:00'), findsOneWidget);
    expect(find.text('Theory · 601'), findsOneWidget);

    await tester.tap(find.text('Tasks').last);
    await settle(tester);
    expect(find.text('All tasks'), findsOneWidget);
    expect(find.text('OS write-up'), findsOneWidget);
    expect(find.text('MISSED'), findsWidgets);

    // The row title carries the HIGH priority flag beside it.
    await tester.tap(find.textContaining('DBMS ER diagram').last);
    await settle(tester);
    expect(find.text('Task details'), findsOneWidget);
    final instructions = find.byWidgetPredicate((w) => w is SelectableText && w.data == 'Draw the ER diagram for the library system.');
    await tester.scrollUntilVisible(instructions, 200, scrollable: find.byType(Scrollable).last);
    expect(instructions, findsOneWidget);
    expect(find.text('Mark completed'), findsOneWidget);
    await finish(tester);
  });

  testWidgets('More lists every other part of the app and the account', (tester) async {
    final services = await signedIn();
    phone(tester);
    await tester.pumpWidget(DueCareApp(services: services));
    await settle(tester);
    await tester.tap(find.text('More'));
    await settle(tester);
    for (final label in ['Subjects', 'Activity', 'Profile & privacy', 'Sources', 'Rules', 'Sign out']) {
      expect(find.text(label), findsWidgets);
    }
    expect(find.text('Asha Rao'), findsOneWidget);
    expect(find.text('SY · COMPS · Div A · Batch A1'), findsOneWidget);
    await finish(tester);
  });
}
