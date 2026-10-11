import 'dart:async';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/ist.dart';
import '../core/models.dart';
import '../core/query.dart';
import '../state/data.dart';
import '../state/services.dart';
import '../ui/task_tiles.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'subjects.dart';
import 'workspace.dart';

const _kindShort = {'theory': 'Theory', 'lab': 'Lab', 'tutorial': 'Tutorial'};

/// Home: this week's deadlines and classes laid out together (apps/web week-sheet.tsx, at the
/// web app's phone layout): the next-due band, summary counts, a seven-day strip and the agenda.
class WeekScreen extends StatefulWidget {
  const WeekScreen({super.key, required this.onTasks, required this.onReview});

  final ValueChanged<String> onTasks;
  final VoidCallback onReview;

  @override
  State<WeekScreen> createState() => _WeekScreenState();
}

class _WeekScreenState extends State<WeekScreen> with WidgetsBindingObserver {
  late String monday = mondayOf(todayKey());
  String selected = todayKey();
  bool month = false;
  Timer? _clock;
  Timer? _cutoff;
  String? _lastVisit;
  static const _lastVisitKey = 'duecare.lastVisit';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _clock = Timer.periodic(const Duration(seconds: 30), (_) => setState(() {}));
    _readLastVisit();
  }

  /// When the student last left the app: read once per launch, saved when they leave.
  Future<void> _readLastVisit() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final previous = prefs.getString(_lastVisitKey);
      if (previous == null) await prefs.setString(_lastVisitKey, DateTime.now().toUtc().toIso8601String());
      if (mounted) setState(() => _lastVisit = previous);
    } catch (_) {}
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused) {
      SharedPreferences.getInstance().then((p) => p.setString(_lastVisitKey, DateTime.now().toUtc().toIso8601String()));
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _clock?.cancel();
    _cutoff?.cancel();
    super.dispose();
  }

  /// Refresh at the next status boundary, so due work turns missed on time.
  void _watchCutoffs(List<Task> tasks) {
    final now = DateTime.now();
    final next = tasks
        .where((t) => t.completedAt == null)
        .map((t) => parseTime(t.dueAt))
        .whereType<DateTime>()
        .where((t) => t.isAfter(now))
        .fold<DateTime?>(null, (a, b) => a == null || b.isBefore(a) ? b : a);
    _cutoff?.cancel();
    if (next == null) return;
    _cutoff = Timer(next.difference(now) + const Duration(milliseconds: 25), () {
      AppScope.of(context).queries.invalidate(['tasks', 'task', 'overview']);
    });
  }

  @override
  Widget build(BuildContext context) {
    final api = AppScope.of(context).api;
    final today = todayKey();
    return QueryView(
      queryKey: Keys.overview,
      fetch: () => api.get('/overview'),
      builder: (context, overview) => QueryView(
        queryKey: ['tasks', 'week', monday],
        fetch: () => allPages(api, '/tasks?limit=100&dateFrom=${Uri.encodeQueryComponent(istMidnight(monday))}'
            '&dateTo=${Uri.encodeQueryComponent(istMidnight(addDays(monday, 7)))}'),
        builder: (context, week) {
          final tasks = week.data is List ? (week.data as List).cast<Map>().map((m) => Task(m.cast<String, dynamic>())).toList() : <Task>[];
          final o = overview.data is Map ? (overview.data as Map).cast<String, dynamic>() : null;
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted) _watchCutoffs([...tasks, ...(o?['tasks'] as List? ?? []).cast<Map>().map((m) => Task(m.cast<String, dynamic>()))]);
          });
          return RefreshIndicator(
            onRefresh: () => AppScope.of(context).queries.invalidate(['overview', 'tasks', 'timetable', 'subjects']),
            child: ListView(
              padding: EdgeInsets.zero,
              children: [
                _NextBand(overview: o, week: tasks, loading: overview.isPending || week.isPending),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
                  child: month
                      ? _Month(onMode: () => setState(() => month = false), summary: _summary(o, overview))
                      : _week(context, today, tasks, week, o, overview),
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _summary(Map<String, dynamic>? o, Query overview) {
    final c = Palette.of(context);
    if (o == null) {
      return overview.error != null
          ? ErrorNotice(overview.error, retry: overview.refetch)
          : Text('Counting your work…', style: TextStyle(color: c.graphite2));
    }
    final counts = (o['counts'] as Map?) ?? {};
    final items = [
      ('due', (counts['due'] as num? ?? 0).toInt(), () => widget.onTasks('due'), 'due'),
      ('missed', (counts['missed'] as num? ?? 0).toInt(), () => widget.onTasks('missed'), 'alert'),
      ('without a date', (o['undated'] as num? ?? 0).toInt(), () => widget.onTasks('undated'), ''),
      ('to review', (o['reviewCount'] as num? ?? 0).toInt(), widget.onReview, 'review'),
    ];
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final (label, value, go, tone) in items)
          if (label == 'due' || value > 0)
            InkWell(
              onTap: go,
              child: Container(
                height: 36,
                padding: const EdgeInsets.fromLTRB(4, 4, 12, 4),
                decoration: BoxDecoration(color: c.sheet, border: Border.all(color: c.inkRule)),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      constraints: const BoxConstraints(minWidth: 28),
                      height: 28,
                      alignment: Alignment.center,
                      padding: const EdgeInsets.symmetric(horizontal: 6),
                      color: switch (tone) {
                        'due' => c.due,
                        'alert' => value > 0 ? c.bad : c.inkWash,
                        'review' => c.graphite,
                        _ => c.inkWash,
                      },
                      child: Text(
                        '$value',
                        style: display(
                          context,
                          16,
                          color: switch (tone) {
                            'due' => c.onDue,
                            'alert' => value > 0 ? c.onBad : c.graphite,
                            'review' => c.onGraphite,
                            _ => c.graphite,
                          },
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(label, style: const TextStyle(fontSize: 14)),
                  ],
                ),
              ),
            ),
      ],
    );
  }

  Widget _week(BuildContext context, String today, List<Task> tasks, Query week, Map<String, dynamic>? o, Query overview) {
    final c = Palette.of(context);
    final days = [for (var i = 0; i < 7; i++) addDays(monday, i)];
    final offset = (DateTime.parse(monday).difference(DateTime.parse(mondayOf(today))).inDays / 7).round();
    final title = switch (offset) {
      0 => 'This week',
      1 => 'Next week',
      -1 => 'Last week',
      _ => 'Week of ${formatDay(monday)}',
    };
    final dues = tasks.where((t) => t.dueAt != null).toList()..sort((a, b) => a.dueAt!.compareTo(b.dueAt!));
    List<Task> dueOn(String date) => dues.where((t) => dayKey(DateTime.parse(t.dueAt!)) == date).toList();
    final day = days.contains(selected) ? selected : (days.contains(today) ? today : monday);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: display(context, 40)),
        Text('${weekRange(monday)} · times in IST', style: TextStyle(color: c.graphite2, fontSize: 15)),
        const SizedBox(height: 14),
        Wrap(
          alignment: WrapAlignment.spaceBetween,
          spacing: 8,
          runSpacing: 8,
          children: [
            _Segment(children: [
              _SegmentButton(icon: Icons.chevron_left, label: 'Previous week', onTap: () => setState(() => monday = addDays(monday, -7))),
              _SegmentButton(
                text: 'Today',
                pressed: offset == 0,
                onTap: () => setState(() {
                  monday = mondayOf(today);
                  selected = today;
                }),
              ),
              _SegmentButton(icon: Icons.chevron_right, label: 'Next week', onTap: () => setState(() => monday = addDays(monday, 7))),
            ]),
            _Segment(children: [
              _SegmentButton(text: 'Week', pressed: true, onTap: () {}),
              _SegmentButton(text: 'Month', pressed: false, onTap: () => setState(() => month = true)),
            ]),
          ],
        ),
        const SizedBox(height: 14),
        if (offset == 0 && week.data != null) _Digest(tasks: tasks, since: _lastVisit),
        _summary(o, overview),
        ErrorNotice(week.error, retry: week.refetch),
        const SizedBox(height: 16),
        Row(
          children: [
            for (final (i, date) in days.indexed)
              Expanded(
                child: _DayButton(
                  name: dayNames[i],
                  date: date,
                  today: date == today,
                  pressed: date == day,
                  statuses: dueOn(date).take(3).map((t) => t.status).toList(),
                  count: dueOn(date).length,
                  onTap: () => setState(() => selected = date),
                ),
              ),
          ],
        ),
        const SizedBox(height: 18),
        _AgendaHead(day == today ? 'Due today' : 'Due · ${weekdayNames[weekdayOf(day) - 1]} ${formatDay(day)}'),
        if (dueOn(day).isEmpty)
          _AgendaEmpty(week.isPending ? 'Loading…' : 'Nothing due this day.')
        else
          for (final t in dueOn(day)) DueItem(task: t, onOpen: () => openTask(context, t.id)),
        const SizedBox(height: 18),
        const _AgendaHead('Classes'),
        _Classes(day: day),
        if (dues.isEmpty && !week.isPending) ...[
          const SizedBox(height: 20),
          Row(
            children: [
              Text('Nothing due this week.', style: TextStyle(color: c.graphite2)),
              const SizedBox(width: 12),
              DueButton(label: 'Add a task', icon: Icons.add, small: true, variant: Variant.outline, onPressed: () => openEditor(context)),
            ],
          ),
        ],
      ],
    );
  }
}

/// The single-message strip under the header: the next due item and a countdown.
class _NextBand extends StatelessWidget {
  const _NextBand({required this.overview, required this.week, required this.loading});

  final Map<String, dynamic>? overview;
  final List<Task> week;
  final bool loading;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final now = DateTime.now();
    final candidates = [
      ...((overview?['tasks'] as List?) ?? []).cast<Map>().map((m) => Task(m.cast<String, dynamic>())),
      ...week,
    ].where((t) => t.dueAt != null && t.status == 'due' && DateTime.parse(t.dueAt!).isAfter(now)).toList()
      ..sort((a, b) => a.dueAt!.compareTo(b.dueAt!));
    final next = candidates.firstOrNull;
    final light = Theme.of(context).brightness == Brightness.dark ? c.graphite : c.sheet;
    return Material(
      color: c.band,
      child: InkWell(
        onTap: next == null ? null : () => openTask(context, next.id),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                color: c.due,
                child: Text('NEXT DUE', style: printed(context, color: c.onDue, size: 11)),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      next?.title ?? (loading ? 'Loading…' : 'Nothing due. You’re all caught up.'),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(color: light, fontWeight: FontWeight.w600, fontSize: 16),
                    ),
                    if (next != null)
                      Text(
                        '${next.subjectName != null ? '${next.subjectName} · ' : ''}${formatTime(next.dueAt)}',
                        style: TextStyle(color: light.withValues(alpha: 0.8), fontSize: 13),
                      ),
                  ],
                ),
              ),
              if (next != null) ...[
                const SizedBox(width: 10),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text('in', style: TextStyle(color: light.withValues(alpha: 0.8), fontSize: 12)),
                    Text(countdown(DateTime.parse(next.dueAt!).difference(now)), style: display(context, 22, color: light)),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// This week at a glance, and what arrived since the last visit.
class _Digest extends StatelessWidget {
  const _Digest({required this.tasks, required this.since});

  final List<Task> tasks;
  final String? since;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final api = AppScope.of(context).api;
    int count(String s) => tasks.where((t) => t.status == s).length;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text.rich(TextSpan(children: [
            const TextSpan(text: 'This week: ', style: TextStyle(fontWeight: FontWeight.w700)),
            TextSpan(text: '${count('due')} due · ${count('missed')} missed · ${count('completed')} done'),
          ])),
          if (since != null)
            QueryView(
              queryKey: ['tasks', 'new-since', since],
              fetch: () => api.get('/tasks?limit=5&createdAfter=${Uri.encodeQueryComponent(since!)}'),
              builder: (context, q) {
                final page = pageOf(q.data);
                if (page.items.isEmpty) return const SizedBox.shrink();
                return Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Wrap(
                    spacing: 8,
                    runSpacing: 4,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      Text('New since your last visit${page.nextCursor != null ? ' (latest 5)' : ''}:',
                          style: TextStyle(color: c.graphite2, fontSize: 13)),
                      for (final t in page.items.map(Task.new))
                        InkWell(
                          onTap: () => openTask(context, t.id),
                          child: Padding(
                            padding: const EdgeInsets.symmetric(vertical: 6),
                            child: Text(t.title, style: TextStyle(decoration: TextDecoration.underline, decorationColor: c.ink, fontSize: 13)),
                          ),
                        ),
                    ],
                  ),
                );
              },
            ),
        ],
      ),
    );
  }
}

class _DayButton extends StatelessWidget {
  const _DayButton({
    required this.name,
    required this.date,
    required this.today,
    required this.pressed,
    required this.statuses,
    required this.count,
    required this.onTap,
  });

  final String name, date;
  final bool today, pressed;
  final List<String> statuses;
  final int count;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final fg = today ? c.onGraphite : c.graphite;
    return Semantics(
      button: true,
      selected: pressed,
      label: '$name ${formatDay(date)}, $count due',
      child: InkWell(
        onTap: onTap,
        child: Container(
          height: 74,
          decoration: BoxDecoration(
            color: today ? c.graphite : (pressed ? c.inkWash : c.sheet),
            border: Border.all(color: pressed ? c.graphite : c.inkRule, width: pressed ? 2 : 1),
          ),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(name.toUpperCase(), style: printed(context, color: today ? c.onGraphite : c.ink, size: 10.5)),
              Text('${dayOfMonth(date)}', style: display(context, 22, color: fg)),
              const SizedBox(height: 4),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  for (final s in statuses)
                    Container(
                      width: 6,
                      height: 6,
                      margin: const EdgeInsets.symmetric(horizontal: 1),
                      color: s == 'completed' ? c.good : (s == 'missed' ? c.bad : c.due),
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _AgendaHead extends StatelessWidget {
  const _AgendaHead(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Container(
        width: double.infinity,
        padding: const EdgeInsets.only(bottom: 6),
        margin: const EdgeInsets.only(bottom: 8),
        decoration: BoxDecoration(border: Border(bottom: BorderSide(color: Palette.of(context).graphite))),
        child: Printed(text, size: 12),
      );
}

class _AgendaEmpty extends StatelessWidget {
  const _AgendaEmpty(this.text);

  final String text;

  @override
  Widget build(BuildContext context) =>
      Padding(padding: const EdgeInsets.symmetric(vertical: 6), child: Text(text, style: TextStyle(color: Palette.of(context).graphite2)));
}

/// The selected day's classes from every subject's weekly timetable.
class _Classes extends StatelessWidget {
  const _Classes({required this.day});

  final String day;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final api = AppScope.of(context).api;
    return QueryView(
      queryKey: Keys.subjects,
      fetch: () => loadSubjects(api),
      builder: (context, sq) {
        final subjects = subjectsOf(sq);
        return QueryView(
          queryKey: ['timetable', 'all', subjects.map((s) => s.id).join(',')],
          staleTime: const Duration(minutes: 5),
          fetch: () async => {
            for (final s in subjects) s.id: ((await api.get('/subjects/${s.id}/timetable')) as Map)['slots'],
          },
          builder: (context, tq) {
            final bySubject = tq.data is Map ? (tq.data as Map).cast<String, dynamic>() : <String, dynamic>{};
            final slots = <(Slot, Subject)>[];
            for (final s in subjects) {
              for (final raw in (bySubject[s.id] as List? ?? []).cast<Map>()) {
                final slot = Slot(raw.cast<String, dynamic>());
                if (slot.weekday != weekdayOf(day) || slot.startTime.isEmpty || slot.endTime.isEmpty) continue;
                if (slot.validFrom != null && slot.validFrom!.substring(0, 10).compareTo(day) > 0) continue;
                if (slot.validUntil != null && slot.validUntil!.substring(0, 10).compareTo(day) < 0) continue;
                slots.add((slot, s));
              }
            }
            slots.sort((a, b) => a.$1.startTime.compareTo(b.$1.startTime));
            if (sq.isPending || (tq.isPending && subjects.isNotEmpty)) return const _AgendaEmpty('Loading…');
            if (slots.isEmpty) {
              final none = bySubject.values.every((v) => (v as List?)?.isEmpty ?? true);
              if (!none) return const _AgendaEmpty('No classes this day.');
              return Align(
                alignment: Alignment.centerLeft,
                child: DueButton(
                  label: 'Add your timetable',
                  small: true,
                  variant: Variant.outline,
                  onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const SubjectsScreen())),
                ),
              );
            }
            return Column(
              children: [
                for (final (slot, subject) in slots)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SizedBox(
                          width: 56,
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(hhmm(slot.startTime), style: display(context, 15)),
                              Text(hhmm(slot.endTime), style: display(context, 12, weight: FontWeight.w500, color: c.graphite2)),
                            ],
                          ),
                        ),
                        Expanded(child: SlotBox(subject: subject, location: slot.location)),
                      ],
                    ),
                  ),
              ],
            );
          },
        );
      },
    );
  }
}

/// A class slot: rose outline, lab slots tinted, tutorial slots dashed (shown as a lighter rule).
class SlotBox extends StatelessWidget {
  const SlotBox({super.key, required this.subject, this.location});

  final Subject subject;
  final String? location;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: subject.kind == 'lab' ? c.inkTint : c.sheet,
        border: Border.all(color: subject.kind == 'tutorial' ? c.inkRule : c.inkLine, width: subject.kind == 'tutorial' ? 2 : 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(subject.code ?? subject.name, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14)),
          Text(
            '${_kindShort[subject.kind] ?? subject.kind}${location != null && location!.isNotEmpty ? ' · $location' : ''}',
            style: TextStyle(color: c.graphite2, fontSize: 12.5),
          ),
        ],
      ),
    );
  }
}

class _Segment extends StatelessWidget {
  const _Segment({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Container(
        decoration: BoxDecoration(border: Border.all(color: Palette.of(context).graphite)),
        child: Row(mainAxisSize: MainAxisSize.min, children: children),
      );
}

class _SegmentButton extends StatelessWidget {
  const _SegmentButton({this.text, this.icon, this.label, this.pressed = false, required this.onTap});

  final String? text;
  final IconData? icon;
  final String? label;
  final bool pressed;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Semantics(
      button: true,
      selected: pressed,
      label: label,
      child: Material(
        color: pressed ? c.graphite : c.sheet,
        child: InkWell(
          onTap: onTap,
          child: Container(
            height: 42,
            constraints: const BoxConstraints(minWidth: 42),
            padding: const EdgeInsets.symmetric(horizontal: 12),
            alignment: Alignment.center,
            child: icon != null
                ? Icon(icon, size: 20, color: pressed ? c.onGraphite : c.graphite)
                : Text(text!, style: TextStyle(fontWeight: FontWeight.w600, color: pressed ? c.onGraphite : c.graphite)),
          ),
        ),
      ),
    );
  }
}

/// The month view: a 6-week grid with each day's deadlines as status ticks, and the chosen
/// day's work listed below.
class _Month extends StatefulWidget {
  const _Month({required this.onMode, required this.summary});

  final VoidCallback onMode;
  final Widget summary;

  @override
  State<_Month> createState() => _MonthState();
}

class _MonthState extends State<_Month> {
  late String month = todayKey().substring(0, 7);
  late String selected = todayKey();

  void move(int delta) {
    final y = int.parse(month.substring(0, 4)), m = int.parse(month.substring(5, 7));
    final d = DateTime.utc(y, m + delta, 1);
    setState(() {
      month = '${d.year}-${d.month.toString().padLeft(2, '0')}';
      selected = '$month-01';
    });
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final api = AppScope.of(context).api;
    final first = '$month-01';
    final y = int.parse(month.substring(0, 4)), m = int.parse(month.substring(5, 7));
    final next = DateTime.utc(y, m + 1, 1);
    final nextKey = '${next.year}-${next.month.toString().padLeft(2, '0')}-01';
    final start = addDays(first, -(weekdayOf(first) - 1));
    final today = todayKey();
    return QueryView(
      queryKey: ['tasks', 'calendar', month],
      fetch: () => allPages(api, '/tasks?limit=100&dateFrom=${Uri.encodeQueryComponent(istMidnight(first))}'
          '&dateTo=${Uri.encodeQueryComponent(istMidnight(nextKey))}'),
      builder: (context, q) {
        final tasks = q.data is List ? (q.data as List).cast<Map>().map((m) => Task(m.cast<String, dynamic>())).toList() : <Task>[];
        List<Task> on(String date) => tasks.where((t) => t.dueAt != null && dayKey(DateTime.parse(t.dueAt!)) == date).toList();
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(monthTitle(month), style: display(context, 40)),
            Text('Times in IST', style: TextStyle(color: c.graphite2)),
            const SizedBox(height: 14),
            Wrap(
              alignment: WrapAlignment.spaceBetween,
              spacing: 8,
              runSpacing: 8,
              children: [
                _Segment(children: [
                  _SegmentButton(icon: Icons.chevron_left, label: 'Previous month', onTap: () => move(-1)),
                  _SegmentButton(
                    text: 'Today',
                    pressed: month == today.substring(0, 7),
                    onTap: () => setState(() {
                      month = today.substring(0, 7);
                      selected = today;
                    }),
                  ),
                  _SegmentButton(icon: Icons.chevron_right, label: 'Next month', onTap: () => move(1)),
                ]),
                _Segment(children: [
                  _SegmentButton(text: 'Week', onTap: widget.onMode),
                  _SegmentButton(text: 'Month', pressed: true, onTap: () {}),
                ]),
              ],
            ),
            const SizedBox(height: 14),
            widget.summary,
            ErrorNotice(q.error, retry: q.refetch),
            const SizedBox(height: 14),
            Container(
              decoration: BoxDecoration(border: Border.all(color: c.graphite), color: c.sheet),
              child: Column(
                children: [
                  Row(children: [
                    for (final d in dayNames)
                      Expanded(child: Padding(padding: const EdgeInsets.all(6), child: Center(child: Printed(d, size: 10)))),
                  ]),
                  for (var w = 0; w < 6; w++)
                    Row(
                      children: [
                        for (var i = 0; i < 7; i++)
                          Expanded(child: _monthCell(context, addDays(start, w * 7 + i), on, today)),
                      ],
                    ),
                ],
              ),
            ),
            const SizedBox(height: 16),
            _AgendaHead('${weekdayNames[weekdayOf(selected) - 1]} ${formatDay(selected, withYear: true)}'),
            if (on(selected).isEmpty)
              _AgendaEmpty(q.isPending ? 'Loading…' : 'Nothing due this day.')
            else
              for (final t in on(selected)) DueItem(task: t, onOpen: () => openTask(context, t.id)),
          ],
        );
      },
    );
  }

  Widget _monthCell(BuildContext context, String date, List<Task> Function(String) on, String today) {
    final c = Palette.of(context);
    final inMonth = date.startsWith(month);
    final items = on(date);
    final cell = Container(
      height: 58,
      decoration: BoxDecoration(
        border: Border(top: BorderSide(color: c.inkRule), left: BorderSide(color: c.inkRule)),
        color: date == selected ? c.inkWash : null,
      ),
      padding: const EdgeInsets.all(4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 3),
            color: date == today ? c.graphite : null,
            child: Text(
              '${dayOfMonth(date)}',
              style: display(context, 14, color: date == today ? c.onGraphite : (inMonth ? c.graphite : c.graphite2)),
            ),
          ),
          const Spacer(),
          Wrap(
            spacing: 2,
            runSpacing: 2,
            children: [
              for (final t in items.take(4))
                Container(width: 7, height: 7, color: t.status == 'completed' ? c.good : (t.status == 'missed' ? c.bad : c.due)),
              if (items.length > 4) Text('+${items.length - 4}', style: display(context, 9, color: c.graphite2)),
            ],
          ),
        ],
      ),
    );
    return Semantics(
      button: true,
      label: '${formatDay(date)}, ${items.length} due',
      child: InkWell(
        onTap: () => setState(() => selected = date),
        // Days outside the month take the hatch (the Hatch Rule).
        child: inMonth ? cell : CustomPaint(painter: HatchPainter(c.inkTint), child: cell),
      ),
    );
  }
}
