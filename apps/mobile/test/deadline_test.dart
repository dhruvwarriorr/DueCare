import 'package:duecare/core/deadline.dart';
import 'package:duecare/core/models.dart';
import 'package:duecare/screens/rules.dart';
import 'package:flutter_test/flutter_test.dart';

Task task([Json extra = const {}]) => Task({
      'id': 't1',
      'revision': 1,
      'title': 'DBMS ER diagram',
      'type': 'assignment',
      'status': 'due',
      'createdAt': '2026-10-01T00:00:00Z',
      ...extra,
    });

void main() {
  test('deadline wording matches every web view', () {
    expect(deadline(task()), (main: 'No due date yet', note: null));
    expect(deadline(task({'dueAt': '2026-10-12T11:30:00Z'})), (main: '12 Oct 2026, 5:00 pm', note: null));
    expect(
      deadline(task({'dueAt': '2026-10-12T18:29:00Z', 'dueDate': '2026-10-12'})),
      (main: '12 Oct 2026', note: 'date only · due by 23:59'),
    );
    expect(
      deadline(task({'type': 'test', 'dueAt': '2026-10-12T18:29:00Z', 'dueDate': '2026-10-12', 'timingTentative': {}})),
      (main: '12 Oct 2026', note: 'Tentative · time not announced'),
    );
    final window = task({
      'dueAt': '2026-10-16T18:29:00Z',
      'dateWindowStart': '2026-10-12',
      'dateWindowEnd': '2026-10-16',
      'timingProvenance': {
        'dueAt': {'basis': 'date-window-end'},
      },
    });
    expect(deadline(window), (main: '12 Oct – 16 Oct 2026', note: 'exact day not announced'));
    expect(dueClock(window), 'last day of window');
  });

  test('due item clocks', () {
    expect(dueClock(task({'dueAt': '2026-10-12T06:45:00Z'})), '12:15');
    expect(dueClock(task({'dueAt': '2026-10-12T18:29:00Z', 'dueDate': '2026-10-12'})), '23:59');
    expect(dueClock(task({'type': 'test', 'dueAt': '2026-10-12T18:29:00Z', 'dueDate': '2026-10-12'})), 'time TBA');
    expect(dueClock(task({'dueAt': '2026-10-12T06:45:00Z', 'timingTentative': {}})), '12:15 · tentative');
  });

  test('Classroom turn-in notes and the task subline', () {
    expect(classroomNote(task()), isNull);
    expect(classroomNote(task({'classroom': {'state': 'RETURNED', 'late': true, 'grade': 18, 'maxPoints': 20}})),
        'graded 18/20 · turned in late');
    expect(classroomNote(task({'classroom': {'state': 'RETURNED', 'late': false, 'grade': null}})), 'returned');
    expect(
      taskSubline(task({'subjectName': 'DBMS', 'source': 'gmail', 'type': 'test'})),
      'Test · DBMS · from Gmail',
    );
    expect(taskSubline(task()), 'Assignment · No subject');
    expect(statusWord('completed'), 'done');
  });

  test('rules read as one plain sentence', () {
    final subjects = [
      Subject({'id': 's1', 'revision': 1, 'name': 'ITVC', 'kind': 'theory'}),
      Subject({'id': 's2', 'revision': 1, 'name': 'ITVC', 'kind': 'tutorial'}),
    ];
    expect(describeRule(ruleDraft('high', 'subjectId', 's1', subjects), subjects), 'Make ITVC work high priority');
    expect(describeRule(ruleDraft('hide', 'keyword', 'seminar', subjects), subjects), 'Hide work containing “seminar”');
    expect(describeRule(ruleDraft('critical', 'taskType', 'test', subjects), subjects), 'Make tests critical priority');
    expect(describeRule(ruleDraft('hide', 'source', 'gmail', subjects), subjects), 'Hide work from Gmail');
    final both = {
      'conditions': [
        {'field': 'subjectId', 'op': 'in', 'value': ['s1', 's2']},
      ],
      'action': {'type': 'priority', 'priority': 'low'},
    };
    // One course across two subjects is named once.
    expect(describeRule(both, subjects), 'Make ITVC work low priority');
    expect(ruleDraft('low', 'keyword', ' quiz ', subjects)['conditions'], [
      {'field': 'keyword', 'op': 'contains', 'value': 'quiz'},
    ]);
  });
}
