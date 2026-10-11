import 'package:duecare/core/ist.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('IST dates follow India, not the phone or UTC', () {
    // 20:00 UTC is 01:30 the next day in India.
    final late = DateTime.utc(2026, 10, 11, 20, 0);
    expect(dayKey(late), '2026-10-12');
    expect(minutesOf(late), 90);
    expect(formatTime('2026-10-11T20:00:00Z'), '12 Oct 2026, 1:30 am');
    expect(formatTime('2026-10-12T06:45:00+00:00'), '12 Oct 2026, 12:15 pm');
    expect(formatTime(null), 'No due date yet');
  });

  test('weeks start on Monday and ranges read like the web', () {
    expect(mondayOf('2026-10-11'), '2026-10-05'); // A Sunday belongs to the week before.
    expect(mondayOf('2026-10-12'), '2026-10-12');
    expect(addDays('2026-12-30', 3), '2027-01-02');
    expect(weekdayOf('2026-10-12'), 1);
    expect(weekRange('2026-10-12'), '12 – 18 Oct 2026');
    expect(weekRange('2026-09-28'), '28 Sep – 4 Oct 2026');
    expect(formatRange('2026-12-30', '2027-01-02'), '30 Dec 2026 – 2 Jan 2027');
    expect(istMidnight('2026-10-12'), '2026-10-12T00:00:00+05:30');
  });

  test('editor values round-trip through IST', () {
    final iso = utcTime('2026-10-12T23:59')!;
    expect(DateTime.parse(iso), DateTime.utc(2026, 10, 12, 18, 29));
    expect(localTime(iso), '2026-10-12T23:59');
    expect(utcTime(''), isNull);
    expect(localTime(null), '');
  });

  test('countdowns and clock strings', () {
    expect(countdown(const Duration(minutes: 42)), '42 min');
    expect(countdown(const Duration(hours: 5, minutes: 3)), '5 h 3 min');
    expect(countdown(const Duration(days: 2, hours: 4)), '2 d 4 h');
    expect(countdown(const Duration(minutes: -5)), '0 min');
    expect(clock(9 * 60 + 5), '09:05');
    expect(hhmm('09:00:00'), '09:00');
    expect(toMinutes('13:30'), 810);
  });
}
