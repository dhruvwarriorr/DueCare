import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

/// The student's notification choices (the API's notification settings). The phone keeps the
/// last copy so reminders and pushes follow them even offline or in the background.
class NotifyPrefs {
  const NotifyPrefs({
    this.push = true,
    this.newWork = true,
    this.changes = true,
    this.review = true,
    this.completed = true,
    this.syncIssues = true,
    this.reminders = true,
    this.reminderLeads = const [1440, 60],
    this.reminderScope = 'all',
    this.digest = false,
    this.digestTime = '08:00',
    this.quietHours = false,
    this.quietStart = '22:00',
    this.quietEnd = '07:00',
  });

  final bool push, newWork, changes, review, completed, syncIssues, reminders, digest, quietHours;
  final List<int> reminderLeads;
  final String reminderScope, digestTime, quietStart, quietEnd;

  /// Lead times the student can choose, in minutes, with their labels.
  static const leads = [
    (10080, '1 week'),
    (4320, '3 days'),
    (1440, '1 day'),
    (360, '6 hours'),
    (180, '3 hours'),
    (60, '1 hour'),
    (30, '30 minutes'),
  ];

  static String leadLabel(int minutes) =>
      leads.where((l) => l.$1 == minutes).map((l) => l.$2).firstOrNull ?? '$minutes minutes';

  factory NotifyPrefs.fromJson(Map<String, dynamic> j) {
    const d = NotifyPrefs();
    bool b(String k, bool fallback) => j[k] is bool ? j[k] as bool : fallback;
    String s(String k, String fallback) => j[k] is String ? j[k] as String : fallback;
    final leads = (j['reminderLeads'] is List) ? (j['reminderLeads'] as List).whereType<num>().map((n) => n.toInt()).toList() : d.reminderLeads;
    return NotifyPrefs(
      push: b('push', d.push),
      newWork: b('newWork', d.newWork),
      changes: b('changes', d.changes),
      review: b('review', d.review),
      completed: b('completed', d.completed),
      syncIssues: b('syncIssues', d.syncIssues),
      reminders: b('reminders', d.reminders),
      reminderLeads: leads.isEmpty ? d.reminderLeads : leads,
      reminderScope: s('reminderScope', d.reminderScope),
      digest: b('digest', d.digest),
      digestTime: s('digestTime', d.digestTime),
      quietHours: b('quietHours', d.quietHours),
      quietStart: s('quietStart', d.quietStart),
      quietEnd: s('quietEnd', d.quietEnd),
    );
  }

  Map<String, dynamic> toJson() => {
        'push': push,
        'newWork': newWork,
        'changes': changes,
        'review': review,
        'completed': completed,
        'syncIssues': syncIssues,
        'reminders': reminders,
        'reminderLeads': reminderLeads,
        'reminderScope': reminderScope,
        'digest': digest,
        'digestTime': digestTime,
        'quietHours': quietHours,
        'quietStart': quietStart,
        'quietEnd': quietEnd,
      };

  NotifyPrefs copyWith(Map<String, dynamic> changes) => NotifyPrefs.fromJson({...toJson(), ...changes});

  /// Whether an activity event of [kind] should be shown, given these choices.
  bool shows(String kind) {
    if (!push) return false;
    return switch (kind) {
      'new_task' => newWork,
      'revision' || 'reopened' => changes,
      'review' => review,
      'auto_completed' => completed,
      'sync_issue' => syncIssues,
      _ => false,
    };
  }

  static const _key = 'duecare.notify.prefs.v1';

  static Future<NotifyPrefs> load() async {
    try {
      final raw = (await SharedPreferences.getInstance()).getString(_key);
      return raw == null ? const NotifyPrefs() : NotifyPrefs.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } catch (_) {
      return const NotifyPrefs();
    }
  }

  Future<void> save() async {
    try {
      await (await SharedPreferences.getInstance()).setString(_key, jsonEncode(toJson()));
    } catch (_) {}
  }

  @override
  bool operator ==(Object other) => other is NotifyPrefs && jsonEncode(other.toJson()) == jsonEncode(toJson());

  @override
  int get hashCode => jsonEncode(toJson()).hashCode;
}
