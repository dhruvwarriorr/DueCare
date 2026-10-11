import 'dart:convert';

import 'package:duecare/core/api.dart';
import 'package:duecare/core/ist.dart';
import 'package:duecare/core/models.dart';
import 'package:duecare/core/session.dart';
import 'package:duecare/notifications/notifier.dart';
import 'package:duecare/notifications/planner.dart';
import 'package:duecare/notifications/prefs.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

// 10:00 IST on Monday 12 October 2026.
final now = fromIst(2026, 10, 12, 10);

Task task(String id, {String status = 'due', DateTime? due, String type = 'assignment', String priority = 'low', String? dueDate, Json? hidden}) => Task({
      'id': id,
      'revision': 1,
      'title': 'Task $id',
      'type': type,
      'status': status,
      'priority': priority,
      'subjectName': 'DBMS',
      'dueAt': due?.toUtc().toIso8601String(),
      'dueDate': dueDate,
      'createdAt': now.toIso8601String(),
      'hiddenByRule': hidden,
    });

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('preferences', () {
    test('round-trip, defaults and categories', () {
      const d = NotifyPrefs();
      expect(d.reminderLeads, [1440, 60]);
      expect(NotifyPrefs.fromJson(d.toJson()), d);
      expect(NotifyPrefs.fromJson({'reminderLeads': [], 'digestTime': 7}).reminderLeads, [1440, 60]);
      final p = d.copyWith({'newWork': false});
      expect(p.shows('new_task'), isFalse);
      expect(p.shows('review'), isTrue);
      expect(d.copyWith({'push': false}).shows('review'), isFalse);
      expect(d.shows('something_new'), isFalse);
      expect(NotifyPrefs.leadLabel(4320), '3 days');
    });

    test('are kept on the phone', () async {
      SharedPreferences.setMockInitialValues({});
      await const NotifyPrefs(digest: true, digestTime: '07:15').save();
      final loaded = await NotifyPrefs.load();
      expect((loaded.digest, loaded.digestTime), (true, '07:15'));
    });
  });

  test('quiet hours follow IST and may cross midnight', () {
    const p = NotifyPrefs(quietHours: true, quietStart: '22:00', quietEnd: '07:00');
    expect(isQuiet(p, fromIst(2026, 10, 12, 23, 30)), isTrue);
    expect(isQuiet(p, fromIst(2026, 10, 12, 6, 59)), isTrue);
    expect(isQuiet(p, fromIst(2026, 10, 12, 7)), isFalse);
    expect(isQuiet(p, fromIst(2026, 10, 12, 12)), isFalse);
    const day = NotifyPrefs(quietHours: true, quietStart: '13:00', quietEnd: '14:00');
    expect(isQuiet(day, fromIst(2026, 10, 12, 13, 30)), isTrue);
    expect(isQuiet(day.copyWith({'quietHours': false}), fromIst(2026, 10, 12, 13, 30)), isFalse);
  });

  group('reminders', () {
    test('one per chosen lead time that is still ahead, nearest first', () {
      final tasks = [
        task('a', due: now.add(const Duration(hours: 30))),
        task('b', due: now.add(const Duration(minutes: 90))),
        task('done', status: 'completed', due: now.add(const Duration(hours: 5))),
        task('missed', status: 'missed', due: now.subtract(const Duration(hours: 1))),
        task('undated'),
        task('hidden', due: now.add(const Duration(hours: 5)), hidden: {'ruleId': 'r'}),
      ];
      final plan = planReminders(tasks, const NotifyPrefs(), now);
      expect(plan.map((p) => (p.payload, p.at.difference(now).inMinutes)), [
        ('task:b', 30), // 1 hour before; "1 day before" b is already past.
        ('task:a', 360), // 1 day before.
        ('task:a', 1740), // 1 hour before.
      ]);
      expect(plan.first.title, 'Due in 1 hour: Task b');
      expect(plan.first.body, startsWith('DBMS · '));
      expect(plan.map((p) => p.id), [1000, 1001, 1002]);
      expect(plan.every((p) => p.channel == Channel.deadlines), isTrue);
      expect(planReminders(tasks, const NotifyPrefs(reminders: false), now), isEmpty);
    });

    test('scope, test wording, quiet hours and date-only deadlines', () {
      final tasks = [
        task('quiz', type: 'test', due: now.add(const Duration(days: 2))),
        task('urgent', priority: 'high', due: now.add(const Duration(days: 2))),
        task('later', due: now.add(const Duration(days: 2))),
      ];
      final important = planReminders(tasks, const NotifyPrefs(reminderScope: 'important', reminderLeads: [1440]), now);
      expect(important.map((p) => p.payload), ['task:quiz', 'task:urgent']);
      expect(important.first.title, 'Test in 1 day: Task quiz');

      // Due 23:59 on a date-only deadline: the 30-minute reminder lands in quiet hours.
      final dateOnly = task('d', due: fromIst(2026, 10, 13, 23, 59), dueDate: '2026-10-13');
      final quiet = planReminders([dateOnly], const NotifyPrefs(reminderLeads: [30], quietHours: true), now);
      expect(quiet.single.channel, Channel.quiet);
      expect(quiet.single.body, contains('by 23:59'));
    });

    test('the daily summary lists each day with something due', () {
      final tasks = [
        task('x', due: fromIst(2026, 10, 12, 17)),
        task('y', due: fromIst(2026, 10, 13, 9)),
        task('z', due: fromIst(2026, 10, 13, 18)),
        task('done', status: 'completed', due: fromIst(2026, 10, 14, 9)),
      ];
      final plan = planDigests(tasks, const NotifyPrefs(digest: true, digestTime: '08:00'), now);
      // Today's 08:00 has passed; tomorrow lists two, the completed day is skipped.
      expect(plan.single.at, fromIst(2026, 10, 13, 8));
      expect(plan.single.title, '2 things due today');
      expect(plan.single.body, 'Task y (09:00), Task z (18:00)');
      expect(planDigests(tasks, const NotifyPrefs(), now), isEmpty);
      final early = planDigests(tasks, const NotifyPrefs(digest: true, digestTime: '06:00'), fromIst(2026, 10, 12, 5));
      expect(early.first.title, '1 thing due today');
    });
  });

  group('updates', () {
    ActivityItem item(String id, String kind, String target, {String type = 'task'}) => ActivityItem({
          'id': id,
          'revision': 1,
          'eventType': kind,
          'targetType': type,
          'targetId': target,
          'message': 'Content-free message.',
          'readAt': null,
          'createdAt': now.toIso8601String(),
        });

    test('compose readable notifications, honouring the categories', () {
      final items = [
        item('1', 'new_task', 't1'),
        item('2', 'revision', 't2'),
        item('3', 'review', 'r1', type: 'review'),
        item('4', 'auto_completed', 't1'),
        item('5', 'sync_issue', 'c1', type: 'connection'),
      ];
      final notices = composeActivity(
        items,
        const NotifyPrefs(changes: false),
        tasks: {'t1': task('t1', due: fromIst(2026, 10, 13, 17))},
        reviews: {'r1': ReviewItem({'id': 'r1', 'revision': 1, 'issueType': 'choose_subject', 'question': 'Which subject is this?', 'createdAt': ''})},
      );
      expect(notices.map((n) => (n.title, n.payload)), [
        ('New: Task t1', 'task:t1'),
        ('Needs your review', 'review:r1'),
        ('Done: Task t1', 'task:t1'),
        ('Sync problem', 'sources'),
      ]);
      expect(notices.first.body, 'DBMS · due 13 Oct 2026, 5:00 pm');
      expect(notices[1].body, 'Which subject is this?');
      expect(summarize(notices), '1 new task · 3 updates');
      // Without details (deleted since), the activity's own message stands in.
      expect(composeActivity([item('6', 'new_task', 'gone')], const NotifyPrefs()).single.body, 'Content-free message.');
      final mine = ActivityItem({...item('7', 'new_task', 't1').json, 'byStudent': true});
      expect(composeActivity([mine], const NotifyPrefs()), isEmpty);
    });

    test('route notification taps', () {
      expect(route('task:abc'), (kind: 'task', id: 'abc'));
      expect(route('sources'), (kind: 'sources', id: null));
      expect(route(null), (kind: 'week', id: null));
    });
  });

  group('push handling', () {
    late List<http.Request> requests;
    late Api api;

    setUp(() async {
      FlutterSecureStorage.setMockInitialValues({'duecare.session': 'h'});
      SharedPreferences.setMockInitialValues({});
      requests = [];
      final later = DateTime.now().toUtc().add(const Duration(minutes: 1)).toIso8601String();
      final session = Session();
      await session.load();
      api = Api(
        base: Uri.parse('https://duecare.test'),
        session: session,
        client: MockClient((r) async {
          requests.add(r);
          final body = switch (r.url.path) {
            '/api/v1/activity' => {
                'items': [
                  {'id': 'a1', 'revision': 1, 'eventType': 'new_task', 'targetType': 'task', 'targetId': 't1', 'message': 'm', 'readAt': null, 'createdAt': later},
                ],
                'nextCursor': null,
                'unreadCount': 1,
              },
            '/api/v1/tasks/t1' => task('t1').json,
            _ => {'items': [], 'nextCursor': null},
          };
          return http.Response(jsonEncode(body), 200);
        }),
      );
    });

    test('a push for another account on this phone is ignored', () async {
      final notifier = Notifier();
      await notifier.begin('student-1');
      await notifier.handlePush({'type': 'activity', 'u': ownerHash('someone-else')}, api);
      expect(requests, isEmpty);
    });

    test('nothing is shown before the account starts notifying (signed out)', () async {
      await Notifier().handlePush({'type': 'activity'}, api);
      expect(requests, isEmpty);
    });

    test('an activity push fetches what is new once, then marks it notified', () async {
      final notifier = Notifier();
      await notifier.begin('student-1');
      await notifier.handlePush({'type': 'activity', 'u': ownerHash('student-1')}, api);
      expect(requests.map((r) => r.url.path), ['/api/v1/activity', '/api/v1/tasks/t1']);
      requests.clear();
      // The same activity is not announced twice.
      expect(await notifier.showUpdates(api, const NotifyPrefs()), 0);
      await notifier.end();
      expect((await SharedPreferences.getInstance()).getString('duecare.notify.owner'), isNull);
    });
  });
}
