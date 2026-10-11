// Review logic for an uploaded timetable's draft, ported from apps/web timetable-import.tsx and
// lib/import-subject.ts. Rows are the API's DraftRow maps; nothing here talks to the network.

import 'models.dart';

const _issueText = {
  'check_text': 'Check this entry against the original',
  'batch_unknown': 'Add your batch in your profile so batch sessions can be filtered',
  'ambiguous_subject': 'Several subjects match. Choose the right one',
  'clipped_start': 'This class is cut off at the top of your screenshots. Check its start time',
  'placeholder': 'A class-wide slot for each student’s own choice. Link it to your subject, or exclude it',
  'clipped_end': 'This class is cut off at the bottom of your screenshots. Check its end time',
};

/// Mirrors the server's name normalization, so a repeat is caught before asking it.
String normalized(String value) => value.toLowerCase().replaceAll('&', 'and').replaceAll(RegExp('[^a-z0-9]'), '');

class RowView {
  RowView(this.row, {required this.included, this.reason, this.problems = const [], this.notes = const []});

  final Json row;
  final bool included;
  final String? reason;
  final List<String> problems;
  final List<String> notes;

  String get id => row['id'] as String;
}

String _str(Object? v) => v is String ? v : '';

/// What one draft row becomes given the student's group choices and taken courses.
RowView viewOf(Json row, Map<String, String> choices, Map<String, bool> taken) {
  final component = row['component'] as String?;
  final notes = [
    for (final i in ((row['issues'] as List?) ?? []).cast<String>())
      i == 'component_missing'
          ? 'No ${component ?? 'lab or tutorial'} subject matches ${row['baseLabel']}. Add one or choose another'
          : (_issueText[i] ?? i),
  ];
  if (row['include'] != true) return RowView(row, included: false, reason: (row['exclusionReason'] as String?) ?? 'Excluded', notes: notes);
  final family = row['familyKey'] as String?;
  if (family != null && taken[family] == false) {
    final track = row['track'];
    return RowView(row, included: false, reason: 'Not one of your ${track == 'honours' ? 'honours courses' : '${track}s'}', notes: notes);
  }
  final choiceKey = row['choiceKey'] as String?;
  final choice = choiceKey == null ? null : choices[choiceKey];
  if (choiceKey != null && choice != null && choice != row['choiceLabel']) {
    return RowView(
      row,
      included: false,
      reason: choice == 'none'
          ? 'You don’t take this'
          : choiceKey.startsWith('group:')
              ? 'Not your group'
              : choiceKey.startsWith('teacher:')
                  ? 'Not your teacher’s group'
                  : 'Not your room',
      notes: notes,
    );
  }
  final problems = <String>[];
  if (choiceKey != null && choice == null) {
    problems.add(choiceKey.startsWith('group:')
        ? 'Choose your group'
        : choiceKey.startsWith('teacher:')
            ? 'Choose your teacher'
            : 'Choose your room');
  }
  if (row['subjectId'] == null) problems.add('Choose a subject');
  final start = _str(row['startTime']), end = _str(row['endTime']);
  if (start.isEmpty || end.isEmpty || end.compareTo(start) <= 0) problems.add('Check this time');
  return RowView(row, included: true, problems: problems, notes: notes);
}

/// One course (same printed name or code and component) is linked once for all its weekly slots.
String courseKey(Json row) {
  if (row['cellId'] == null) return row['id'] as String; // Slots the student adds stay separate.
  final name = (row['code'] as String?) ?? _str(row['baseLabel']).trim().toLowerCase();
  return '$name|${row['component'] ?? 'batch'}';
}

class Course {
  Course({
    required this.key,
    required this.label,
    required this.code,
    required this.component,
    required this.track,
    required this.slots,
    required this.subjectId,
    required this.mixed,
    required this.suggestion,
    required this.suggestionSource,
    required this.needsReview,
    required this.notes,
  });

  final String key, label, component;
  final String? code, track, subjectId, suggestion, suggestionSource;
  final List<RowView> slots;
  final bool mixed, needsReview;
  final List<String> notes;

  Set<String> get rowIds => slots.map((v) => v.id).toSet();
}

String _componentText(Json row) {
  final component = row['component'] as String?;
  if (component != null) return component;
  return ((row['batches'] as List?)?.isNotEmpty ?? false) || row['group'] != null ? 'batch session' : '';
}

List<Course> coursesOf(List<RowView> views) {
  final map = <String, List<RowView>>{};
  for (final v in views) {
    map.putIfAbsent(courseKey(v.row), () => []).add(v);
  }
  return [
    for (final MapEntry(:key, value: slots) in map.entries)
      () {
        final first = slots.first.row;
        final linked = slots.map((v) => v.row['subjectId']).toSet();
        final suggested = slots.where((v) => v.row['suggestedSubjectId'] != null).firstOrNull?.row;
        final track = first['track'] as String?;
        slots.sort((a, b) {
          final day = (a.row['weekday'] as num).compareTo(b.row['weekday'] as num);
          return day != 0 ? day : _str(a.row['startTime']).compareTo(_str(b.row['startTime']));
        });
        return Course(
          key: key,
          label: _str(first['baseLabel']).isNotEmpty ? _str(first['baseLabel']) : _str(first['label']),
          code: first['code'] as String?,
          component: _componentText(first),
          track: track != null && track != 'core' ? (first['placeholder'] == true ? '$track slot' : track) : null,
          slots: slots,
          subjectId: linked.length == 1 ? first['subjectId'] as String? : null,
          mixed: linked.length > 1,
          suggestion: suggested?['suggestedSubjectId'] as String?,
          suggestionSource: suggested?['suggestionSource'] as String?,
          needsReview: slots.any((v) => v.problems.isNotEmpty),
          notes: {for (final v in slots) ...v.notes}.toList(),
        );
      }(),
  ];
}

class ChoiceGroup {
  ChoiceGroup(this.key, this.title);

  final String key, title;
  final Map<String, List<Json>> options = {};
}

const _days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

/// Parallel groups, teachers or rooms the student must pick one of.
List<ChoiceGroup> choiceGroupsOf(List<Json> rows, Map<String, bool> taken) {
  final groups = <String, ChoiceGroup>{};
  for (final r in rows) {
    final key = r['choiceKey'] as String?;
    if (key == null || r['include'] != true) continue;
    final family = r['familyKey'] as String?;
    if (family != null && taken[family] == false) continue;
    final base = _str(r['baseLabel']);
    final g = groups.putIfAbsent(
      key,
      () => ChoiceGroup(
        key,
        key.startsWith('group:')
            ? '$base: which group are you in?'
            : key.startsWith('teacher:')
                ? '$base: whose group are you in?'
                : '$base on ${_days[(r['weekday'] as num).toInt() - 1]} at ${r['startTime']}: which room?',
      ),
    );
    final label = (r['choiceLabel'] as String?) ?? _str(r['label']);
    g.options.putIfAbsent(label, () => []).add(r);
  }
  return groups.values.toList();
}

final _maths = RegExp(r'\b(math(s|ematics)?|am|em|itvc|calculus)(?:\b|(?=[1-4]))|integral transforms', caseSensitive: false);

/// The kind for a subject created from a batch session without a stated component: maths
/// courses run tutorials, everything else a lab.
String importSubjectKind(Json row, List<Subject> subjects) {
  final component = row['component'] as String?;
  if (component != null) return component;
  final labels = [_str(row['baseLabel']), _str(row['label']), _str(row['code'])];
  final related = subjects.where((s) => [s.name, s.code ?? '', ...s.aliases].any(
        (value) => value.isNotEmpty && labels.any((label) => label.isNotEmpty && value.toLowerCase() == label.toLowerCase()),
      ));
  return [...labels, ...related.map((s) => s.name)].any(_maths.hasMatch) ? 'tutorial' : 'lab';
}
