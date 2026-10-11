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

List<Task> _tasksOf(Object? data) =>
    data is List ? data.cast<Map>().map((m) => Task(m.cast<String, dynamic>())).toList() : <Task>[];

Future<dynamic> _range(Services s, String from, String to) => allPages(
      s.api,
      '/tasks?limit=100&dateFrom=${Uri.encodeQueryComponent(istMidnight(from))}&dateTo=${Uri.encodeQueryComponent(istMidnight(to))}',
    );

/// Home: the next deadline, this week's days and the chosen day's work and classes.
class WeekScreen extends StatefulWidget {
  const WeekScreen({super.key, required this.profile, required this.onTasks, required this.onReview});

  final Profile profile;
  final ValueChanged<String> onTasks;
  final VoidCallback onReview;

  @override
  State<WeekScreen> createState() => _WeekScreenState();
}

class _WeekScreenState extends State<WeekScreen> with WidgetsBindingObserver {
  late String monday = mondayOf(todayKey());
  String selected = todayKey();
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
      if (mounted) AppScope.of(context).queries.invalidate(['tasks', 'task', 'overview']);
    });
  }

  void _week(int delta) => setState(() {
        monday = addDays(monday, 7 * delta);
        final today = todayKey();
        selected = mondayOf(today) == monday ? today : monday;
      });

  String get _greeting {
    final h = ist(DateTime.now()).hour;
    final part = h < 12 ? 'Good morning' : (h < 17 ? 'Good afternoon' : 'Good evening');
    final name = widget.profile.name?.split(' ').first;
    return name == null || name.isEmpty ? part : '$part, $name';
  }

  @override
  Widget build(BuildContext context) {
    final services = AppScope.of(context);
    final c = Palette.of(context);
    final today = todayKey();
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        heroTag: 'add-week',
        onPressed: () => openEditor(context),
        icon: const Icon(Icons.add_rounded),
        label: const Text('Add task'),
      ),
      body: QueryView(
        queryKey: Keys.overview,
        fetch: () => services.api.get('/overview'),
        builder: (context, overview) => QueryView(
          queryKey: ['tasks', 'week', monday],
          fetch: () => _range(services, monday, addDays(monday, 7)),
          builder: (context, week) {
            final tasks = _tasksOf(week.data);
            final o = overview.data is Map ? (overview.data as Map).cast<String, dynamic>() : null;
            final upcoming = ((o?['tasks'] as List?) ?? []).cast<Map>().map((m) => Task(m.cast<String, dynamic>())).toList();
            WidgetsBinding.instance.addPostFrameCallback((_) {
              if (mounted) _watchCutoffs([...tasks, ...upcoming]);
            });
            final dues = tasks.where((t) => t.dueAt != null).toList()..sort((a, b) => a.dueAt!.compareTo(b.dueAt!));
            List<Task> dueOn(String date) => dues.where((t) => dayKey(DateTime.parse(t.dueAt!)) == date).toList();
            final days = [for (var i = 0; i < 7; i++) addDays(monday, i)];
            final day = days.contains(selected) ? selected : monday;
            return RefreshIndicator(
              onRefresh: () => services.queries.invalidate(['overview', 'tasks', 'timetable', 'subjects']),
              child: CustomScrollView(
                physics: const AlwaysScrollableScrollPhysics(parent: BouncingScrollPhysics()),
                slivers: [
                  SliverAppBar(
                    floating: true,
                    toolbarHeight: 64,
                    titleSpacing: 20,
                    title: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(_greeting, style: TextStyle(fontSize: 13.5, color: c.graphite2, fontWeight: FontWeight.w600)),
                        Text(
                          '${weekdayNames[weekdayOf(today) - 1]}, ${formatDay(today)}',
                          style: display(context, 24),
                        ),
                      ],
                    ),
                    actions: [
                      IconButton(
                        tooltip: 'Month',
                        icon: const Icon(Icons.calendar_month_outlined),
                        onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const MonthScreen())),
                      ),
                      const ActivityBell(),
                      const SizedBox(width: 6),
                    ],
                  ),
                  SliverPadding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 110),
                    sliver: SliverList.list(children: [
                      _NextCard(upcoming: upcoming, week: tasks, loading: overview.isPending || week.isPending),
                      const SizedBox(height: 14),
                      _Stats(overview: o, error: overview.error, retry: overview.refetch, onTasks: widget.onTasks, onReview: widget.onReview),
                      const SizedBox(height: 14),
                      _WeekStrip(
                        monday: monday,
                        selected: day,
                        today: today,
                        statuses: {for (final d in days) d: dueOn(d).map((t) => t.status).toList()},
                        onSelect: (d) => setState(() => selected = d),
                        onWeek: _week,
                      ),
                      if (monday == mondayOf(today) && _lastVisit != null) _NewSince(since: _lastVisit!),
                      ErrorNotice(week.error, retry: week.refetch),
                      SectionLabel(
                        day == today ? 'Due today' : 'Due ${weekdayNames[weekdayOf(day) - 1]}, ${formatDay(day)}',
                        trailing: Text('${dueOn(day).length}', style: display(context, 15, color: c.graphite2)),
                      ),
                      if (dueOn(day).isEmpty)
                        _Quiet(week.isPending ? 'Loading…' : 'Nothing due. Enjoy the free time.', icon: Icons.wb_sunny_outlined)
                      else
                        for (final t in dueOn(day)) DueItem(task: t, onOpen: () => openTask(context, t.id)),
                      const SectionLabel('Classes'),
                      _Classes(day: day),
                    ]),
                  ),
                ],
              ),
            );
          },
        ),
      ),
    );
  }
}

class _Quiet extends StatelessWidget {
  const _Quiet(this.text, {required this.icon});

  final String text;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      decoration: BoxDecoration(color: c.sheet, borderRadius: BorderRadius.circular(Radii.medium)),
      child: Row(children: [
        Icon(icon, color: c.graphite2, size: 20),
        const SizedBox(width: 12),
        Expanded(child: Text(text, style: TextStyle(color: c.graphite2))),
      ]),
    );
  }
}

/// The next due item and a live countdown.
class _NextCard extends StatelessWidget {
  const _NextCard({required this.upcoming, required this.week, required this.loading});

  final List<Task> upcoming;
  final List<Task> week;
  final bool loading;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final now = DateTime.now();
    final candidates = {for (final t in [...upcoming, ...week]) t.id: t}
        .values
        .where((t) => t.dueAt != null && t.status == 'due' && DateTime.parse(t.dueAt!).isAfter(now))
        .toList()
      ..sort((a, b) => a.dueAt!.compareTo(b.dueAt!));
    final next = candidates.firstOrNull;
    final light = Theme.of(context).brightness == Brightness.dark ? c.graphite : c.sheet;
    return Material(
      color: c.band,
      borderRadius: BorderRadius.circular(Radii.card + 4),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: next == null ? null : () => openTask(context, next.id),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(18, 16, 18, 18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(color: c.due, borderRadius: BorderRadius.circular(20)),
                  child: Text('Next due', style: TextStyle(color: c.onDue, fontWeight: FontWeight.w800, fontSize: 12.5)),
                ),
                const Spacer(),
                if (next != null)
                  Text.rich(TextSpan(children: [
                    TextSpan(text: 'in ', style: TextStyle(color: light.withValues(alpha: 0.75), fontSize: 13)),
                    TextSpan(text: countdown(DateTime.parse(next.dueAt!).difference(now)), style: display(context, 20, color: light)),
                  ])),
              ]),
              const SizedBox(height: 12),
              Text(
                next?.title ?? (loading ? 'Loading…' : 'Nothing due. You’re all caught up.'),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: display(context, 21, weight: FontWeight.w700, color: light),
              ),
              if (next != null) ...[
                const SizedBox(height: 4),
                Text(
                  '${next.subjectName != null ? '${next.subjectName} · ' : ''}${formatTime(next.dueAt)}',
                  style: TextStyle(color: light.withValues(alpha: 0.78), fontSize: 13.5),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// Counts that open the matching task list.
class _Stats extends StatelessWidget {
  const _Stats({required this.overview, required this.error, required this.retry, required this.onTasks, required this.onReview});

  final Map<String, dynamic>? overview;
  final Object? error;
  final VoidCallback retry;
  final ValueChanged<String> onTasks;
  final VoidCallback onReview;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final o = overview;
    if (o == null) return error != null ? ErrorNotice(error, retry: retry) : const SizedBox(height: 74);
    final counts = (o['counts'] as Map?) ?? {};
    int n(Object? v) => (v as num? ?? 0).toInt();
    final items = [
      ('Due', n(counts['due']), c.due, c.onDue, () => onTasks('due')),
      ('Missed', n(counts['missed']), c.bad, c.onBad, () => onTasks('missed')),
      ('No date', n(o['undated']), c.inkTint, c.graphite, () => onTasks('undated')),
      ('To review', n(o['reviewCount']), c.graphite, c.onGraphite, onReview),
    ];
    return Row(
      children: [
        for (final (i, (label, value, bg, fg, go)) in items.indexed) ...[
          if (i > 0) const SizedBox(width: 8),
          Expanded(
            child: Material(
              color: c.sheet,
              borderRadius: BorderRadius.circular(Radii.medium),
              child: InkWell(
                borderRadius: BorderRadius.circular(Radii.medium),
                onTap: go,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Container(
                        constraints: const BoxConstraints(minWidth: 30),
                        height: 30,
                        padding: const EdgeInsets.symmetric(horizontal: 7),
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                          color: value > 0 || i == 0 ? bg : c.inkWash,
                          borderRadius: BorderRadius.circular(9),
                        ),
                        child: Text('$value', style: display(context, 16, color: value > 0 || i == 0 ? fg : c.graphite2)),
                      ),
                      const SizedBox(height: 6),
                      FittedBox(
                        fit: BoxFit.scaleDown,
                        alignment: Alignment.centerLeft,
                        child: Text(label, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: c.graphite2)),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ],
    );
  }
}

/// Seven day pills with status dots; swipe sideways to change week.
class _WeekStrip extends StatelessWidget {
  const _WeekStrip({
    required this.monday,
    required this.selected,
    required this.today,
    required this.statuses,
    required this.onSelect,
    required this.onWeek,
  });

  final String monday, selected, today;
  final Map<String, List<String>> statuses;
  final ValueChanged<String> onSelect;
  final ValueChanged<int> onWeek;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final offset = (DateTime.parse(monday).difference(DateTime.parse(mondayOf(today))).inDays / 7).round();
    final title = switch (offset) {
      0 => 'This week',
      1 => 'Next week',
      -1 => 'Last week',
      _ => 'Week of ${formatDay(monday)}',
    };
    return GestureDetector(
      onHorizontalDragEnd: (d) {
        final v = d.primaryVelocity ?? 0;
        if (v.abs() > 250) onWeek(v < 0 ? 1 : -1);
      },
      child: Container(
        padding: const EdgeInsets.fromLTRB(8, 6, 8, 12),
        decoration: BoxDecoration(color: c.sheet, borderRadius: BorderRadius.circular(Radii.card)),
        child: Column(
          children: [
            Row(children: [
              IconButton(tooltip: 'Previous week', onPressed: () => onWeek(-1), icon: const Icon(Icons.chevron_left_rounded)),
              Expanded(
                child: GestureDetector(
                  onTap: offset == 0 ? null : () => onWeek(-offset),
                  child: Column(children: [
                    Text(title, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15)),
                    Text(weekRange(monday), style: display(context, 12.5, weight: FontWeight.w500, color: c.graphite2)),
                  ]),
                ),
              ),
              IconButton(tooltip: 'Next week', onPressed: () => onWeek(1), icon: const Icon(Icons.chevron_right_rounded)),
            ]),
            const SizedBox(height: 6),
            Row(
              children: [
                for (var i = 0; i < 7; i++)
                  Expanded(child: _day(context, addDays(monday, i), dayNames[i])),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _day(BuildContext context, String date, String name) {
    final c = Palette.of(context);
    final isSelected = date == selected;
    final isToday = date == today;
    final fg = isSelected ? c.onGraphite : c.graphite;
    final dots = statuses[date] ?? [];
    return Semantics(
      button: true,
      selected: isSelected,
      label: '$name ${formatDay(date)}, ${dots.length} due',
      child: GestureDetector(
        onTap: () => onSelect(date),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 180),
          margin: const EdgeInsets.symmetric(horizontal: 2.5),
          padding: const EdgeInsets.symmetric(vertical: 9),
          decoration: BoxDecoration(
            color: isSelected ? c.graphite : (isToday ? c.inkWash : Colors.transparent),
            borderRadius: BorderRadius.circular(Radii.medium),
            border: isToday && !isSelected ? Border.all(color: c.ink, width: 1.4) : null,
          ),
          child: Column(children: [
            Text(name.substring(0, 1), style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: isSelected ? fg : c.graphite2)),
            const SizedBox(height: 2),
            Text('${dayOfMonth(date)}', style: display(context, 18, color: fg)),
            const SizedBox(height: 5),
            SizedBox(
              height: 6,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  for (final s in dots.take(3))
                    Container(
                      width: 6,
                      height: 6,
                      margin: const EdgeInsets.symmetric(horizontal: 1),
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: s == 'completed' ? c.good : (s == 'missed' ? c.bad : c.due),
                      ),
                    ),
                ],
              ),
            ),
          ]),
        ),
      ),
    );
  }
}

/// What arrived since the last visit.
class _NewSince extends StatelessWidget {
  const _NewSince({required this.since});

  final String since;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final api = AppScope.of(context).api;
    return QueryView(
      queryKey: ['tasks', 'new-since', since],
      fetch: () => api.get('/tasks?limit=5&createdAfter=${Uri.encodeQueryComponent(since)}'),
      builder: (context, q) {
        final page = pageOf(q.data);
        if (page.items.isEmpty) return const SizedBox.shrink();
        return Padding(
          padding: const EdgeInsets.only(top: 14),
          child: Panel(
            padding: const EdgeInsets.fromLTRB(16, 14, 8, 6),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  Icon(Icons.auto_awesome_outlined, size: 18, color: c.ink),
                  const SizedBox(width: 8),
                  Text('New since your last visit', style: TextStyle(fontWeight: FontWeight.w800, color: c.ink)),
                ]),
                for (final t in page.items.map(Task.new))
                  ListTile(
                    dense: true,
                    contentPadding: const EdgeInsets.only(left: 26, right: 4),
                    title: Text(t.title, maxLines: 1, overflow: TextOverflow.ellipsis),
                    subtitle: t.subjectName == null ? null : Text(t.subjectName!),
                    trailing: Icon(Icons.chevron_right, color: c.graphite2),
                    onTap: () => openTask(context, t.id),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// The selected day's classes, as a timeline.
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
            if (sq.isPending || (tq.isPending && subjects.isNotEmpty)) return const _Quiet('Loading…', icon: Icons.schedule);
            if (slots.isEmpty) {
              final none = bySubject.values.every((v) => (v as List?)?.isEmpty ?? true);
              if (!none) return const _Quiet('No classes this day.', icon: Icons.event_available_outlined);
              return Panel(
                child: Row(children: [
                  Icon(Icons.calendar_month_outlined, color: c.ink),
                  const SizedBox(width: 12),
                  const Expanded(child: Text('Add your timetable to see classes next to your deadlines.')),
                  TextButton(
                    onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const SubjectsScreen())),
                    child: const Text('Add'),
                  ),
                ]),
              );
            }
            final now = minutesOf(DateTime.now());
            final isToday = day == todayKey();
            return Column(
              children: [
                for (final (slot, subject) in slots)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SizedBox(
                          width: 54,
                          child: Padding(
                            padding: const EdgeInsets.only(top: 10),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(hhmm(slot.startTime), style: display(context, 15)),
                                Text(hhmm(slot.endTime), style: display(context, 12, weight: FontWeight.w500, color: c.graphite2)),
                              ],
                            ),
                          ),
                        ),
                        Expanded(
                          child: SlotBox(
                            subject: subject,
                            location: slot.location,
                            live: isToday && now >= toMinutes(slot.startTime) && now < toMinutes(slot.endTime),
                          ),
                        ),
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

/// A class: subject, kind and room, edged by its kind; "Now" while it runs.
class SlotBox extends StatelessWidget {
  const SlotBox({super.key, required this.subject, this.location, this.live = false});

  final Subject subject;
  final String? location;
  final bool live;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final edge = switch (subject.kind) {
      'lab' => c.ink,
      'tutorial' => c.inkLine,
      _ => c.graphite2,
    };
    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: subject.kind == 'lab' ? c.inkWash : c.sheet,
        borderRadius: BorderRadius.circular(Radii.medium),
        border: live ? Border.all(color: c.ink, width: 1.6) : null,
      ),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(width: 4, color: edge),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(subject.code ?? subject.name, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
                    Text(
                      '${_kindShort[subject.kind] ?? subject.kind}${location != null && location!.isNotEmpty ? ' · $location' : ''}',
                      style: TextStyle(color: c.graphite2, fontSize: 13),
                    ),
                  ],
                ),
              ),
            ),
            if (live)
              Padding(
                padding: const EdgeInsets.only(right: 12),
                child: Center(
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(color: c.ink, borderRadius: BorderRadius.circular(20)),
                    child: Text('Now', style: TextStyle(color: c.sheet, fontWeight: FontWeight.w800, fontSize: 12)),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// The month: each day's deadlines as dots, and the chosen day's work below.
class MonthScreen extends StatefulWidget {
  const MonthScreen({super.key});

  @override
  State<MonthScreen> createState() => _MonthState();
}

class _MonthState extends State<MonthScreen> {
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
    final services = AppScope.of(context);
    final first = '$month-01';
    final y = int.parse(month.substring(0, 4)), m = int.parse(month.substring(5, 7));
    final next = DateTime.utc(y, m + 1, 1);
    final nextKey = '${next.year}-${next.month.toString().padLeft(2, '0')}-01';
    final start = addDays(first, -(weekdayOf(first) - 1));
    final today = todayKey();
    return QueryView(
      queryKey: ['tasks', 'calendar', month],
      fetch: () => _range(services, first, nextKey),
      builder: (context, q) {
        final tasks = _tasksOf(q.data);
        List<Task> on(String date) => tasks.where((t) => t.dueAt != null && dayKey(DateTime.parse(t.dueAt!)) == date).toList();
        return PageScaffold(
          title: monthTitle(month),
          onRefresh: q.refetch,
          actions: [
            IconButton(tooltip: 'Previous month', onPressed: () => move(-1), icon: const Icon(Icons.chevron_left_rounded)),
            if (month != today.substring(0, 7))
              TextButton(
                onPressed: () => setState(() {
                  month = today.substring(0, 7);
                  selected = today;
                }),
                child: const Text('Today'),
              ),
            IconButton(tooltip: 'Next month', onPressed: () => move(1), icon: const Icon(Icons.chevron_right_rounded)),
          ],
          children: [
            ErrorNotice(q.error, retry: q.refetch),
            GestureDetector(
              onHorizontalDragEnd: (d) {
                final v = d.primaryVelocity ?? 0;
                if (v.abs() > 250) move(v < 0 ? 1 : -1);
              },
              child: Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(color: c.sheet, borderRadius: BorderRadius.circular(Radii.card)),
                child: Column(
                  children: [
                    Row(children: [
                      for (final d in dayNames)
                        Expanded(
                          child: Padding(
                            padding: const EdgeInsets.symmetric(vertical: 6),
                            child: Center(child: Text(d.substring(0, 1), style: TextStyle(color: c.graphite2, fontWeight: FontWeight.w700))),
                          ),
                        ),
                    ]),
                    for (var w = 0; w < 6; w++)
                      Row(children: [
                        for (var i = 0; i < 7; i++) Expanded(child: _cell(context, addDays(start, w * 7 + i), on, today)),
                      ]),
                  ],
                ),
              ),
            ),
            SectionLabel('${weekdayNames[weekdayOf(selected) - 1]}, ${formatDay(selected, withYear: true)}'),
            if (on(selected).isEmpty)
              _Quiet(q.isPending ? 'Loading…' : 'Nothing due this day.', icon: Icons.wb_sunny_outlined)
            else
              for (final t in on(selected)) DueItem(task: t, onOpen: () => openTask(context, t.id)),
          ],
        );
      },
    );
  }

  Widget _cell(BuildContext context, String date, List<Task> Function(String) on, String today) {
    final c = Palette.of(context);
    final inMonth = date.startsWith(month);
    final items = on(date);
    final isSelected = date == selected;
    return Semantics(
      button: true,
      label: '${formatDay(date)}, ${items.length} due',
      child: GestureDetector(
        onTap: () => setState(() => selected = date),
        child: Container(
          height: 50,
          margin: const EdgeInsets.all(2),
          decoration: BoxDecoration(
            color: isSelected ? c.graphite : (date == today ? c.inkWash : null),
            borderRadius: BorderRadius.circular(12),
            border: date == today && !isSelected ? Border.all(color: c.ink) : null,
          ),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(
                '${dayOfMonth(date)}',
                style: display(
                  context,
                  15,
                  weight: FontWeight.w700,
                  color: isSelected ? c.onGraphite : (inMonth ? c.graphite : c.graphite2.withValues(alpha: 0.5)),
                ),
              ),
              const SizedBox(height: 4),
              SizedBox(
                height: 6,
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    for (final t in items.take(3))
                      Container(
                        width: 6,
                        height: 6,
                        margin: const EdgeInsets.symmetric(horizontal: 1),
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: t.status == 'completed' ? c.good : (t.status == 'missed' ? c.bad : c.due),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
