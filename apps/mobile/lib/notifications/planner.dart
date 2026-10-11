// What to notify and when, as plain data: deadline reminders, the daily summary, quiet hours and
// the wording of pushed updates. Kept free of plugins so every rule is unit-tested.

import '../core/deadline.dart';
import '../core/ist.dart';
import '../core/models.dart';
import 'prefs.dart';

enum Channel { deadlines, updates, digest, quiet }

class Planned {
  const Planned({required this.id, required this.at, required this.title, required this.body, required this.payload, required this.channel});

  final int id;
  final DateTime at;
  final String title, body, payload;
  final Channel channel;

  @override
  String toString() => '$at $title — $body';
}

/// Scheduled notifications use ids 1000–1999; shown updates use their own range.
const reminderIds = 1000;
const digestIds = 1900;
const maxReminders = 120;

int _minutes(String hhmm) => toMinutes(hhmm);

/// Quiet hours in IST; a window may cross midnight (22:00–07:00).
bool isQuiet(NotifyPrefs p, DateTime at) {
  if (!p.quietHours) return false;
  final m = minutesOf(at), start = _minutes(p.quietStart), end = _minutes(p.quietEnd);
  if (start == end) return false;
  return start < end ? m >= start && m < end : m >= start || m < end;
}

Channel _quietOr(NotifyPrefs p, DateTime at, Channel channel) => isQuiet(p, at) ? Channel.quiet : channel;

String _due(Task t) {
  final d = deadline(t);
  return d.note != null && d.note!.contains('date only') ? '${d.main}, by 23:59' : d.main;
}

bool _important(Task t) => t.isTest || t.priority == 'high' || t.priority == 'critical';

/// Reminders before each upcoming deadline, nearest first.
List<Planned> planReminders(List<Task> tasks, NotifyPrefs p, DateTime now) {
  if (!p.reminders) return [];
  final out = <Planned>[];
  for (final t in tasks) {
    final due = parseTime(t.dueAt);
    if (due == null || t.status != 'due' || t.hiddenByRule != null) continue;
    if (p.reminderScope == 'important' && !_important(t)) continue;
    for (final lead in p.reminderLeads) {
      final at = due.subtract(Duration(minutes: lead));
      if (!at.isAfter(now)) continue;
      out.add(Planned(
        id: 0,
        at: at,
        title: '${t.isTest ? 'Test' : 'Due'} in ${NotifyPrefs.leadLabel(lead)}: ${t.title}',
        body: [t.subjectName, _due(t)].whereType<String>().join(' · '),
        payload: 'task:${t.id}',
        channel: _quietOr(p, at, Channel.deadlines),
      ));
    }
  }
  out.sort((a, b) => a.at.compareTo(b.at));
  return [
    for (final (i, r) in out.take(maxReminders).indexed)
      Planned(id: reminderIds + i, at: r.at, title: r.title, body: r.body, payload: r.payload, channel: r.channel),
  ];
}

/// The morning summary for each of the next seven days that has something due.
List<Planned> planDigests(List<Task> tasks, NotifyPrefs p, DateTime now) {
  if (!p.digest) return [];
  final out = <Planned>[];
  final time = _minutes(p.digestTime);
  final today = todayKey(now);
  for (var i = 0; i < 7; i++) {
    final day = addDays(today, i);
    final at = DateTime.parse(istMidnight(day)).add(Duration(minutes: time));
    if (!at.isAfter(now)) continue;
    final due = tasks
        .where((t) => t.status == 'due' && t.hiddenByRule == null && t.dueAt != null && dayKey(DateTime.parse(t.dueAt!)) == day)
        .toList()
      ..sort((a, b) => a.dueAt!.compareTo(b.dueAt!));
    if (due.isEmpty) continue;
    final names = due.take(3).map((t) => '${t.title} (${dueClock(t)})').join(', ');
    out.add(Planned(
      id: digestIds + i,
      at: at,
      title: due.length == 1 ? '1 thing due today' : '${due.length} things due today',
      body: due.length > 3 ? '$names and ${due.length - 3} more' : names,
      payload: 'week',
      channel: _quietOr(p, at, Channel.digest),
    ));
  }
  return out;
}

/// An update from the server, ready to show.
class Notice {
  const Notice({required this.key, required this.title, required this.body, required this.payload, required this.kind});

  final String key, title, body, payload, kind;
}

/// Turns new activity into notifications. [tasks] and [reviews] hold whatever details could be
/// fetched; without them the activity's own (content-free) message is used.
List<Notice> composeActivity(List<ActivityItem> items, NotifyPrefs p, {Map<String, Task> tasks = const {}, Map<String, ReviewItem> reviews = const {}}) {
  final out = <Notice>[];
  for (final a in items) {
    final kind = (a.json['eventType'] as String?) ?? '';
    // The student's own changes (here or on the web) are never announced back to them.
    if (!p.shows(kind) || a.json['byStudent'] == true) continue;
    final t = tasks[a.targetId];
    final detail = t == null ? null : [t.subjectName, if (t.dueAt != null) 'due ${_due(t)}'].whereType<String>().join(' · ');
    final (title, body, payload) = switch (kind) {
      'new_task' => (t == null ? 'New work added' : 'New: ${t.title}', detail ?? a.message, 'task:${a.targetId}'),
      'revision' => (t == null ? 'Task updated' : 'Updated: ${t.title}', detail ?? a.message, 'task:${a.targetId}'),
      'reopened' => (t == null ? 'Task reopened' : 'Reopened: ${t.title}', detail ?? a.message, 'task:${a.targetId}'),
      'auto_completed' => (t == null ? 'Marked done' : 'Done: ${t.title}', 'Marked done from your submission', 'task:${a.targetId}'),
      'review' => ('Needs your review', reviews[a.targetId]?.question.isNotEmpty == true ? reviews[a.targetId]!.question : a.message, 'review:${a.targetId}'),
      _ => ('Sync problem', a.message, 'sources'),
    };
    out.add(Notice(key: a.id, title: title, body: body, payload: payload, kind: kind));
  }
  return out;
}

/// The single line for a group of updates.
String summarize(List<Notice> notices) {
  final newWork = notices.where((n) => n.kind == 'new_task').length;
  final others = notices.length - newWork;
  return [
    if (newWork > 0) '$newWork new ${newWork == 1 ? 'task' : 'tasks'}',
    if (others > 0) '$others ${others == 1 ? 'update' : 'updates'}',
  ].join(' · ');
}

/// Where a tapped notification leads.
({String kind, String? id}) route(String? payload) {
  if (payload == null || payload.isEmpty) return (kind: 'week', id: null);
  final i = payload.indexOf(':');
  return i < 0 ? (kind: payload, id: null) : (kind: payload.substring(0, i), id: payload.substring(i + 1));
}
