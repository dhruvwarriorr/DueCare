import 'dart:convert';
import 'dart:ui';

import 'package:crypto/crypto.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

import '../core/api.dart';
import '../core/models.dart';
import 'planner.dart';
import 'prefs.dart';

const _channels = {
  Channel.deadlines: AndroidNotificationChannel(
    'deadlines',
    'Deadline reminders',
    description: 'Before assignments and tests are due',
    importance: Importance.high,
  ),
  Channel.updates: AndroidNotificationChannel(
    'updates',
    'Updates',
    description: 'New work, changes, reviews and sync problems',
    importance: Importance.high,
  ),
  Channel.digest: AndroidNotificationChannel(
    'digest',
    'Daily summary',
    description: 'What is due today, each morning',
  ),
  Channel.quiet: AndroidNotificationChannel(
    'quiet',
    'During quiet hours',
    description: 'Notifications that arrive in your quiet hours, without sound',
    importance: Importance.low,
    playSound: false,
    enableVibration: false,
  ),
};

const _rose = Color(0xFFC21C58);
const _group = 'app.duecare.updates';
const _summaryId = 1;

String ownerHash(String userId) => sha256.convert(utf8.encode(userId)).toString().substring(0, 16);

/// Shows and schedules DueCare's notifications on the phone. Used by the app and by the push
/// handler, which runs in the background without any screen.
class Notifier {
  Notifier([FlutterLocalNotificationsPlugin? plugin]) : _plugin = plugin ?? FlutterLocalNotificationsPlugin();

  final FlutterLocalNotificationsPlugin _plugin;
  bool _ready = false;
  static const _markKey = 'duecare.notify.lastActivity';
  static const _ownerKey = 'duecare.notify.owner';

  /// Opens what a tapped notification is about.
  void Function(String? payload)? onTap;
  String? _launch;

  AndroidFlutterLocalNotificationsPlugin? get _android =>
      _plugin.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();

  Future<void> init() async {
    if (_ready) return;
    tzdata.initializeTimeZones();
    await _plugin.initialize(
      settings: const InitializationSettings(android: AndroidInitializationSettings('ic_stat_duecare')),
      onDidReceiveNotificationResponse: (r) => onTap?.call(r.payload),
    );
    for (final channel in _channels.values) {
      await _android?.createNotificationChannel(channel);
    }
    final launch = await _plugin.getNotificationAppLaunchDetails();
    if (launch?.didNotificationLaunchApp ?? false) _launch = launch!.notificationResponse?.payload;
    _ready = true;
  }

  bool get ready => _ready;

  /// The notification that opened the app, once.
  String? takeLaunch() {
    final p = _launch;
    _launch = null;
    return p;
  }

  // Platform questions answer conservatively when the plugin is unavailable.
  Future<T> _ask<T>(Future<T?>? Function() call, T fallback) async {
    try {
      return await call() ?? fallback;
    } catch (_) {
      return fallback;
    }
  }

  Future<bool> permitted() => _ask(() => _android?.areNotificationsEnabled(), false);

  Future<bool> requestPermission() => _ask(() => _android?.requestNotificationsPermission(), false);

  Future<bool> exactAllowed() => _ask(() => _android?.canScheduleExactNotifications(), false);

  /// Precise reminder times need the "Alarms & reminders" permission on Android 12+.
  Future<void> requestExact() => _ask(() => _android?.requestExactAlarmsPermission(), null);

  Future<void> openSettings() => _ask(() => _plugin.openAppNotificationSettings(), null);

  NotificationDetails _details(Channel channel, {String? body, bool group = false, StyleInformation? style}) {
    final c = _channels[channel]!;
    return NotificationDetails(
      android: AndroidNotificationDetails(
        c.id,
        c.name,
        channelDescription: c.description,
        importance: c.importance,
        priority: c.importance == Importance.low ? Priority.low : Priority.high,
        color: _rose,
        groupKey: group ? _group : null,
        category: channel == Channel.deadlines ? AndroidNotificationCategory.reminder : null,
        styleInformation: style ?? (body == null ? null : BigTextStyleInformation(body)),
      ),
    );
  }

  /// Rebuild every scheduled reminder and summary.
  Future<int> schedule(List<Task> tasks, NotifyPrefs prefs, {DateTime? now}) async {
    // Nothing is scheduled for an account that has signed out (a refresh may finish late).
    if (!_ready || !await _signedIn()) return 0;
    await _plugin.cancelAllPendingNotifications();
    final at = now ?? DateTime.now();
    final planned = [...planReminders(tasks, prefs, at), ...planDigests(tasks, prefs, at)];
    final mode = await exactAllowed() ? AndroidScheduleMode.exactAllowWhileIdle : AndroidScheduleMode.inexactAllowWhileIdle;
    for (final p in planned) {
      await _plugin.zonedSchedule(
        id: p.id,
        title: p.title,
        body: p.body,
        scheduledDate: tz.TZDateTime.from(p.at.toUtc(), tz.UTC),
        notificationDetails: _details(p.channel, body: p.body),
        androidScheduleMode: mode,
        payload: p.payload,
      );
    }
    return planned.length;
  }

  Future<List<PendingNotificationRequest>> pending() => _plugin.pendingNotificationRequests();

  /// Notifications currently in the shade.
  Future<List<ActiveNotification>> active() => _ask(() => _android?.getActiveNotifications(), const <ActiveNotification>[]);

  /// Fetch the student's upcoming work and rebuild the schedule.
  Future<int> refresh(Api api, {NotifyPrefs? prefs}) async {
    if (!_ready) return 0;
    final chosen = prefs ?? await NotifyPrefs.load();
    final List<Task> tasks;
    try {
      final since = DateTime.now().toUtc().toIso8601String();
      final page = await api.get('/tasks?status=due&limit=100&dateFrom=${Uri.encodeQueryComponent(since)}');
      tasks = pageOf(page).items.map(Task.new).toList();
    } on ApiError {
      return -1; // Keep the current schedule until the server answers.
    }
    return schedule(tasks, chosen);
  }

  /// Remember whose phone this is, and start notifying from now (never about older activity).
  Future<void> begin(String userId) async {
    final store = await SharedPreferences.getInstance();
    final owner = ownerHash(userId);
    if (store.getString(_ownerKey) != owner || store.getString(_markKey) == null) {
      await store.setString(_ownerKey, owner);
      await store.setString(_markKey, DateTime.now().toUtc().toIso8601String());
    }
  }

  Future<bool> _signedIn() async => (await SharedPreferences.getInstance()).getString(_ownerKey) != null;

  /// Forget the account on sign-out: nothing scheduled or shown survives it.
  Future<void> end() async {
    if (_ready) await _plugin.cancelAll();
    final store = await SharedPreferences.getInstance();
    await store.remove(_ownerKey);
    await store.remove(_markKey);
  }

  /// Show activity that arrived since the last notification.
  Future<int> showUpdates(Api api, NotifyPrefs prefs) async {
    final store = await SharedPreferences.getInstance();
    final mark = DateTime.tryParse(store.getString(_markKey) ?? '');
    if (mark == null) return 0;
    final page = pageOf(await api.get('/activity?read=false&limit=20'));
    final fresh = page.items.map(ActivityItem.new).where((a) => DateTime.parse(a.createdAt).isAfter(mark)).toList()
      ..sort((a, b) => a.createdAt.compareTo(b.createdAt));
    if (fresh.isEmpty) return 0;
    await store.setString(_markKey, fresh.last.createdAt);
    final tasks = <String, Task>{};
    final reviews = <String, ReviewItem>{};
    // Details for the latest few; the rest are summarized.
    for (final a in fresh.reversed.take(6)) {
      try {
        if (a.targetType == 'task') tasks[a.targetId] = Task((await api.get('/tasks/${a.targetId}')) as Map<String, dynamic>);
        if (a.targetType == 'review') {
          reviews[a.targetId] = ReviewItem((await api.get('/review-items/${a.targetId}')) as Map<String, dynamic>);
        }
      } on ApiError {
        // Removed since; the activity's own message is used.
      }
    }
    final notices = composeActivity(fresh, prefs, tasks: tasks, reviews: reviews);
    await show(notices, prefs);
    return notices.length;
  }

  Future<void> show(List<Notice> notices, NotifyPrefs prefs, {DateTime? now}) async {
    if (notices.isEmpty || !_ready || !await _signedIn()) return;
    final channel = isQuiet(prefs, now ?? DateTime.now()) ? Channel.quiet : Channel.updates;
    final grouped = notices.length > 1;
    for (final n in notices) {
      await _plugin.show(
        id: 2000 + (n.key.hashCode & 0x3fffffff) % 1000000,
        title: n.title,
        body: n.body,
        notificationDetails: _details(channel, body: n.body, group: grouped),
        payload: n.payload,
      );
    }
    if (grouped) {
      await _plugin.show(
        id: _summaryId,
        title: summarize(notices),
        body: notices.map((n) => n.title).join(', '),
        notificationDetails: NotificationDetails(
          android: AndroidNotificationDetails(
            _channels[channel]!.id,
            _channels[channel]!.name,
            color: _rose,
            groupKey: _group,
            setAsGroupSummary: true,
            styleInformation: InboxStyleInformation(notices.map((n) => n.title).take(6).toList(), summaryText: summarize(notices)),
          ),
        ),
        payload: 'week',
      );
    }
  }

  Future<void> showTest(NotifyPrefs prefs, {String body = 'Notifications from DueCare will look like this.'}) => show(
        [Notice(key: 'test-${DateTime.now().microsecondsSinceEpoch}', title: 'DueCare notifications are on', body: body, payload: 'week', kind: 'test')],
        prefs,
      );

  /// A push arrived: show what it announces and refresh the reminder schedule.
  Future<void> handlePush(Map<String, dynamic> data, Api api) async {
    final store = await SharedPreferences.getInstance();
    final owner = store.getString(_ownerKey);
    // A push for an account that has since signed out of this phone.
    if (owner == null || (data['u'] != null && data['u'] != owner)) return;
    final prefs = await NotifyPrefs.load();
    switch (data['type']) {
      case 'test':
        await showTest(prefs, body: 'Push notifications reach this phone.');
      case 'activity':
        try {
          await showUpdates(api, prefs);
        } on ApiError {
          // Shown next time; the activity stays unread.
        }
    }
    await refresh(api, prefs: prefs);
  }
}
