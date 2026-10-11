import '../core/api.dart';
import '../core/models.dart';
import '../core/query.dart';

/// Query keys and loaders shared by several screens.
abstract final class Keys {
  static const me = ['me'];
  static const subjects = ['subjects'];
  static const overview = ['overview'];
  static const connections = ['connections'];
  static const rules = ['rules'];
  static const activityCount = ['activity', 'count'];
  static List<Object?> task(String id) => ['task', id];
  static List<Object?> timetable(String id) => ['timetable', id];
}

/// What a change on the server can affect; reloaded when the change stamp moves.
const reloadRoots = [
  'tasks', 'task', 'overview', 'review-items', 'review-item', 'activity', //
  'evidence', 'history', 'rules', 'subjects', 'me',
];

/// Everything a finished sync or privacy step can change.
const syncRoots = [
  'connections', 'overview', 'classroom-courses', 'subjects', 'activity', 'review-items', //
  'review-item', 'tasks', 'task', 'history', 'evidence', 'approved-faculty', 'me',
];

const taskRoots = ['tasks', 'overview', 'task', 'history'];

Future<dynamic> loadSubjects(Api api) => allPages(api, '/subjects?limit=100');

List<Subject> subjectsOf(Query q) =>
    q.data is List ? (q.data as List).cast<Map>().map((m) => Subject(m.cast<String, dynamic>())).toList() : [];

Profile? profileOf(Query q) => q.data is Map ? Profile((q.data as Map).cast<String, dynamic>()) : null;
