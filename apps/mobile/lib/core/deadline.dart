import 'ist.dart';
import 'models.dart';

/// The days a window-derived deadline stands for, when the exact day is not announced.
({String start, String end})? dueWindow(Task t) {
  final basis = t.basisOf('dueAt') ?? '';
  final start = t.dateWindowStart, end = t.dateWindowEnd;
  return start != null && end != null && basis.endsWith('window-end') ? (start: start, end: end) : null;
}

/// One description of when work is due, shared by every view.
({String main, String? note}) deadline(Task t) {
  if (t.dueAt == null) return (main: 'No due date yet', note: null);
  final tentative = t.timingTentative != null ? 'Tentative · ' : '';
  final w = dueWindow(t);
  if (w != null) return (main: formatRange(w.start, w.end), note: '${tentative}exact day not announced');
  if (t.dueDate != null) {
    return (
      main: formatDay(t.dueDate!, withYear: true),
      note: tentative + (t.isTest ? 'time not announced' : 'date only · due by 23:59'),
    );
  }
  return (main: formatTime(t.dueAt), note: t.timingTentative != null ? 'Tentative' : null);
}

/// The clock shown on a due item: a window or a date without an announced time has none.
String dueClock(Task t) {
  final String when;
  if (dueWindow(t) != null) {
    when = 'last day of window';
  } else if (t.dueDate != null && t.isTest) {
    when = 'time TBA';
  } else if (t.dueDate != null) {
    when = '23:59';
  } else {
    when = clock(minutesOf(DateTime.parse(t.dueAt!)));
  }
  return t.timingTentative != null ? '$when · tentative' : when;
}

/// What Classroom shows for the student's turn-in: a returned grade, or that it was late.
String? classroomNote(Task t) {
  final c = t.classroom;
  if (c == null) return null;
  final parts = <String>[];
  final grade = c['grade'] as num?;
  final max = c['maxPoints'] as num?;
  String n(num v) => v == v.roundToDouble() ? v.toInt().toString() : v.toString();
  if (grade != null) {
    parts.add('graded ${n(grade)}${max != null && max != 0 ? '/${n(max)}' : ''}');
  } else if (c['state'] == 'RETURNED') {
    parts.add('returned');
  }
  if (c['late'] == true && (c['state'] == 'TURNED_IN' || c['state'] == 'RETURNED')) parts.add('turned in late');
  return parts.isEmpty ? null : parts.join(' · ');
}

const sourceName = {'gmail': 'Gmail', 'classroom': 'Classroom'};

/// "Assignment · DBMS · from Gmail"
String taskSubline(Task t) {
  final from = sourceName[t.source];
  return [
    t.isTest ? 'Test' : 'Assignment',
    t.subjectName ?? 'No subject',
    if (from != null) 'from $from',
    ?classroomNote(t),
  ].join(' · ');
}

/// The word printed on a status pill.
String statusWord(String status) => status == 'completed' ? 'done' : status;
