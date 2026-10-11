// All DueCare times are India Standard Time (UTC+05:30, no daylight saving), whatever the
// phone's own time zone. These helpers mirror apps/web/src/lib/api.ts and week-sheet.tsx.

const istOffset = Duration(hours: 5, minutes: 30);

const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const _monthNames = [
  'January', 'February', 'March', 'April', 'May', 'June', //
  'July', 'August', 'September', 'October', 'November', 'December',
];
const dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const weekdayNames = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

/// The IST wall clock of an instant, as a UTC DateTime whose fields read in IST.
DateTime ist(DateTime t) => t.toUtc().add(istOffset);

/// The instant at an IST wall-clock time.
DateTime fromIst(int year, int month, int day, [int hour = 0, int minute = 0]) =>
    DateTime.utc(year, month, day, hour, minute).subtract(istOffset);

String _two(int n) => n.toString().padLeft(2, '0');

/// The IST calendar date of an instant, as YYYY-MM-DD.
String dayKey(DateTime t) {
  final d = ist(t);
  return '${d.year}-${_two(d.month)}-${_two(d.day)}';
}

String todayKey([DateTime? now]) => dayKey(now ?? DateTime.now());

DateTime _keyDate(String key) => DateTime.utc(
      int.parse(key.substring(0, 4)),
      int.parse(key.substring(5, 7)),
      int.parse(key.substring(8, 10)),
    );

String addDays(String key, int n) {
  final d = _keyDate(key).add(Duration(days: n));
  return '${d.year}-${_two(d.month)}-${_two(d.day)}';
}

String mondayOf(String key) => addDays(key, -(_keyDate(key).weekday - 1));

/// 1 (Monday) to 7 (Sunday), as the API's weekly slots number days.
int weekdayOf(String key) => _keyDate(key).weekday;

int dayOfMonth(String key) => _keyDate(key).day;

/// The API filter value for the start of an IST day.
String istMidnight(String key) => '${key}T00:00:00+05:30';

/// Minutes past IST midnight of an instant.
int minutesOf(DateTime t) {
  final d = ist(t);
  return d.hour * 60 + d.minute;
}

String clock(int minutes) => '${_two(minutes ~/ 60)}:${_two(minutes % 60)}';

/// "HH:MM" from an API time ("09:00" or "09:00:00").
String hhmm(String t) => t.length >= 5 ? t.substring(0, 5) : t;

int toMinutes(String t) {
  final parts = t.split(':');
  return int.parse(parts[0]) * 60 + (parts.length > 1 ? int.parse(parts[1]) : 0);
}

DateTime? parseTime(String? iso) => iso == null || iso.isEmpty ? null : DateTime.tryParse(iso);

/// "12 Oct 2026, 5:30 pm", as en-IN formats an IST time.
String formatTime(String? iso, {String empty = 'No due date yet'}) {
  final t = parseTime(iso);
  if (t == null) return empty;
  final d = ist(t);
  final hour = d.hour % 12 == 0 ? 12 : d.hour % 12;
  return '${d.day} ${_months[d.month - 1]} ${d.year}, $hour:${_two(d.minute)} ${d.hour < 12 ? 'am' : 'pm'}';
}

/// "12 Oct", or "12 Oct 2026" with the year, for a calendar date (YYYY-MM-DD).
String formatDay(String key, {bool withYear = false}) {
  final d = _keyDate(key);
  return '${d.day} ${_months[d.month - 1]}${withYear ? ' ${d.year}' : ''}';
}

String monthTitle(String month) {
  final d = _keyDate('$month-01');
  return '${_monthNames[d.month - 1]} ${d.year}';
}

String formatRange(String start, String end) {
  final sameYear = start.substring(0, 4) == end.substring(0, 4);
  return '${formatDay(start, withYear: !sameYear)} – ${formatDay(end, withYear: true)}';
}

/// "12 – 18 Oct 2026" for the week that starts on [monday].
String weekRange(String monday) {
  final sunday = addDays(monday, 6);
  final sameMonth = monday.substring(5, 7) == sunday.substring(5, 7);
  return '${sameMonth ? dayOfMonth(monday) : formatDay(monday)} – ${formatDay(sunday, withYear: true)}';
}

String countdown(Duration left) {
  final min = left.inMinutes < 0 ? 0 : (left.inSeconds / 60).round();
  if (min < 60) return '$min min';
  final h = min ~/ 60;
  if (h < 24) return '$h h ${min % 60} min';
  return '${h ~/ 24} d ${h % 24} h';
}

/// A local "YYYY-MM-DDTHH:MM" IST value (as the editors hold it) as an ISO instant, or null.
String? utcTime(String value) {
  if (value.isEmpty) return null;
  return DateTime.parse('$value:00+05:30').toUtc().toIso8601String();
}

/// An ISO instant as "YYYY-MM-DDTHH:MM" in IST, or "".
String localTime(String? iso) {
  final t = parseTime(iso);
  if (t == null) return '';
  final d = ist(t);
  return '${d.year}-${_two(d.month)}-${_two(d.day)}T${_two(d.hour)}:${_two(d.minute)}';
}
