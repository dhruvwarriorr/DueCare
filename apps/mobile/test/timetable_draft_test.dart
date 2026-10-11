import 'package:duecare/core/models.dart';
import 'package:duecare/core/timetable_draft.dart';
import 'package:flutter_test/flutter_test.dart';

Json row(String id, [Json extra = const {}]) => {
      'id': id,
      'cellId': 'c$id',
      'label': 'DBMS',
      'baseLabel': 'DBMS',
      'code': null,
      'component': 'theory',
      'batches': <String>[],
      'group': null,
      'weekday': 1,
      'startTime': '09:00',
      'endTime': '10:00',
      'include': true,
      'subjectId': null,
      'issues': <String>[],
      ...extra,
    };

void main() {
  test('a row needs a subject and a valid time before it is ready', () {
    final v = viewOf(row('1'), {}, {});
    expect(v.included, isTrue);
    expect(v.problems, ['Choose a subject']);
    final bad = viewOf(row('2', {'subjectId': 's1', 'endTime': '08:00'}), {}, {});
    expect(bad.problems, ['Check this time']);
    expect(viewOf(row('3', {'subjectId': 's1'}), {}, {}).problems, isEmpty);
  });

  test('exclusions, untaken courses and group choices leave rows out', () {
    expect(viewOf(row('1', {'include': false, 'exclusionReason': 'Batch B2'}), {}, {}).reason, 'Batch B2');
    final elective = row('2', {'familyKey': 'f1', 'track': 'elective'});
    expect(viewOf(elective, {}, {'f1': false}).reason, 'Not one of your electives');
    final grouped = row('3', {'subjectId': 's1', 'choiceKey': 'group:DBMS', 'choiceLabel': 'G1'});
    expect(viewOf(grouped, {}, {}).problems, ['Choose your group']);
    expect(viewOf(grouped, {'group:DBMS': 'G1'}, {}).included, isTrue);
    expect(viewOf(grouped, {'group:DBMS': 'G2'}, {}).reason, 'Not your group');
    expect(viewOf(grouped, {'group:DBMS': 'none'}, {}).reason, 'You don’t take this');
  });

  test('slots of one course are linked together, sorted by day and time', () {
    final views = [
      viewOf(row('1', {'weekday': 3, 'subjectId': 's1'}), {}, {}),
      viewOf(row('2', {'weekday': 1, 'subjectId': 's1'}), {}, {}),
      viewOf(row('3', {'label': 'OS', 'baseLabel': 'OS', 'suggestedSubjectId': 's9', 'suggestionSource': 'ai'}), {}, {}),
      viewOf(row('m1', {'cellId': null, 'label': '', 'baseLabel': ''}), {}, {}),
    ];
    final courses = coursesOf(views);
    expect(courses.map((c) => c.key), ['dbms|theory', 'os|theory', 'm1']);
    final dbms = courses.first;
    expect(dbms.subjectId, 's1');
    expect(dbms.slots.map((v) => v.id), ['2', '1']);
    expect(dbms.needsReview, isFalse);
    expect(courses[1].suggestion, 's9');
    expect(courses[1].needsReview, isTrue);
  });

  test('group questions collect each parallel option', () {
    final rows = [
      row('1', {'choiceKey': 'group:DBMS', 'choiceLabel': 'G1'}),
      row('2', {'choiceKey': 'group:DBMS', 'choiceLabel': 'G2'}),
      row('3', {'choiceKey': 'room:x', 'choiceLabel': '601', 'weekday': 2, 'startTime': '11:00'}),
      row('4', {'choiceKey': 'group:OS', 'choiceLabel': 'G1', 'include': false}),
    ];
    final groups = choiceGroupsOf(rows, {});
    expect(groups.map((g) => g.title), ['DBMS: which group are you in?', 'DBMS on Tuesday at 11:00: which room?']);
    expect(groups.first.options.keys, ['G1', 'G2']);
  });

  test('batch sessions become tutorials for maths and labs otherwise', () {
    expect(importSubjectKind(row('1', {'component': null, 'baseLabel': 'EM-III', 'label': 'EM-III'}), []), 'tutorial');
    expect(importSubjectKind(row('2', {'component': null, 'baseLabel': 'DBMS', 'label': 'DBMS'}), []), 'lab');
    expect(importSubjectKind(row('3'), []), 'theory');
    expect(normalized('Data & Structures-1'), 'dataandstructures1');
  });
}
