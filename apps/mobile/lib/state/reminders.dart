import 'dart:io';

import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

import '../core/api.dart';
import '../core/deadline.dart';
import '../core/ist.dart';
import '../core/models.dart';

/// Reminders for upcoming deadlines, scheduled on the phone itself: a day before and an hour
/// before each due task. They are rebuilt whenever the app sees its tasks change, and they fire
/// even offline. Tasks that arrive while the app is closed get reminders the next time it opens.
class Reminders {
  Reminders() : _plugin = FlutterLocalNotificationsPlugin();

  final FlutterLocalNotificationsPlugin _plugin;
  static const _enabledKey = 'duecare.reminders';
  // iOS keeps at most 64 pending notifications per app.
  static const _max = 60;
  bool _ready = false;

  /// Opens a task when its reminder is tapped.
  void Function(String taskId)? onOpenTask;
  String? _launchTask;

  Future<void> init() async {
    tzdata.initializeTimeZones();
    await _plugin.initialize(
      settings: const InitializationSettings(
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
        iOS: DarwinInitializationSettings(
          requestAlertPermission: false,
          requestBadgePermission: false,
          requestSoundPermission: false,
        ),
      ),
      onDidReceiveNotificationResponse: (r) {
        final id = r.payload;
        if (id != null && id.isNotEmpty) onOpenTask?.call(id);
      },
    );
    final launch = await _plugin.getNotificationAppLaunchDetails();
    if (launch?.didNotificationLaunchApp ?? false) _launchTask = launch!.notificationResponse?.payload;
    _ready = true;
  }

  /// The task whose reminder opened the app, once.
  String? takeLaunchTask() {
    final id = _launchTask;
    _launchTask = null;
    return id;
  }

  Future<bool> get enabled async {
    try {
      return (await SharedPreferences.getInstance()).getBool(_enabledKey) ?? true;
    } catch (_) {
      return true;
    }
  }

  /// Turn reminders on (asking the system for permission) or off.
  Future<bool> setEnabled(bool value) async {
    var on = value;
    if (value) on = await _permission();
    await (await SharedPreferences.getInstance()).setBool(_enabledKey, on);
    if (!on) await clear();
    return on;
  }

  /// Ask for notification permission once, the first time the workspace opens.
  Future<void> askOnce() async {
    if (!_ready) return;
    final prefs = await SharedPreferences.getInstance();
    if (prefs.getBool('$_enabledKey.asked') ?? false) return;
    await prefs.setBool('$_enabledKey.asked', true);
    if (await enabled) await setEnabled(true);
  }

  Future<bool> _permission() async {
    if (Platform.isAndroid) {
      final android = _plugin.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
      return await android?.requestNotificationsPermission() ?? true;
    }
    final ios = _plugin.resolvePlatformSpecificImplementation<IOSFlutterLocalNotificationsPlugin>();
    return await ios?.requestPermissions(alert: true, badge: false, sound: true) ?? false;
  }

  Future<void> clear() async {
    if (_ready) await _plugin.cancelAll();
  }

  /// Rebuild the schedule from the student's upcoming due work.
  Future<void> refresh(Api api) async {
    if (!_ready || !await enabled) return;
    final List<Task> tasks;
    try {
      final now = DateTime.now().toUtc().toIso8601String();
      final page = await api.get('/tasks?status=due&limit=100&dateFrom=${Uri.encodeQueryComponent(now)}');
      tasks = pageOf(page).items.map(Task.new).toList();
    } on ApiError {
      return; // Keep the current schedule until the server answers.
    }
    await schedule(tasks);
  }

  Future<void> schedule(List<Task> tasks) async {
    await _plugin.cancelAll();
    final now = DateTime.now();
    final planned = <({DateTime at, Task task, String lead})>[];
    for (final t in tasks) {
      final due = parseTime(t.dueAt);
      if (due == null || t.status != 'due') continue;
      for (final (lead, before) in [('in 1 day', const Duration(days: 1)), ('in 1 hour', const Duration(hours: 1))]) {
        final at = due.subtract(before);
        if (at.isAfter(now)) planned.add((at: at, task: t, lead: lead));
      }
    }
    planned.sort((a, b) => a.at.compareTo(b.at));
    const details = NotificationDetails(
      android: AndroidNotificationDetails(
        'deadlines',
        'Deadlines',
        channelDescription: 'Reminders before assignments and tests are due',
        importance: Importance.high,
        priority: Priority.high,
      ),
      iOS: DarwinNotificationDetails(),
    );
    var id = 0;
    for (final p in planned.take(_max)) {
      final t = p.task;
      await _plugin.zonedSchedule(
        id: id++,
        title: '${t.isTest ? 'Test' : 'Due'} ${p.lead}: ${t.title}',
        body: [t.subjectName, deadline(t).main].whereType<String>().join(' · '),
        scheduledDate: tz.TZDateTime.from(p.at.toUtc(), tz.UTC),
        notificationDetails: details,
        androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
        payload: t.id,
      );
    }
  }
}
