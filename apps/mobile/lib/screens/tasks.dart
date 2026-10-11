import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/api.dart';
import '../core/ist.dart';
import '../core/models.dart';
import '../core/query.dart';
import '../state/data.dart';
import '../state/services.dart';
import '../ui/task_tiles.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'workspace.dart';

/// Filters beyond the status chips, edited together in a sheet.
class _Filters {
  const _Filters({this.type = '', this.subject = '', this.kind = '', this.priority = '', this.date = '', this.source = '', this.batch = ''});

  final String type, subject, kind, priority, date, source, batch;

  int get count => [type, subject, kind, priority, date, source, batch].where((v) => v.isNotEmpty).length;

  _Filters copy({String? type, String? subject, String? kind, String? priority, String? date, String? source, String? batch}) => _Filters(
        type: type ?? this.type,
        subject: subject ?? this.subject,
        kind: kind ?? this.kind,
        priority: priority ?? this.priority,
        date: date ?? this.date,
        source: source ?? this.source,
        batch: batch ?? this.batch,
      );
}

const _statuses = [('', 'All'), ('due', 'Due'), ('missed', 'Missed'), ('completed', 'Done'), ('undated', 'No date'), ('hidden', 'Hidden')];

/// Every task: search, status chips, filters, sorting, swipe actions and multi-select.
class TasksScreen extends StatefulWidget {
  const TasksScreen({super.key, this.initialStatus = '', this.batch});

  final String initialStatus;
  final String? batch;

  @override
  State<TasksScreen> createState() => _TasksScreenState();
}

class _TasksScreenState extends State<TasksScreen> {
  final search = TextEditingController();
  final scroll = ScrollController();
  bool searching = false;
  Timer? _debounce;
  String q = '';
  late String status = widget.initialStatus;
  _Filters filters = const _Filters();
  String sort = 'date';
  Set<String>? selected;
  bool bulkPending = false;
  static const _sortKey = 'duecare.taskSort';

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((p) {
      if (mounted && p.getString(_sortKey) == 'priority') setState(() => sort = 'priority');
    });
  }

  @override
  void dispose() {
    _debounce?.cancel();
    search.dispose();
    scroll.dispose();
    super.dispose();
  }

  String get params {
    final f = filters;
    final p = <String, String>{'sort': sort};
    if (q.isNotEmpty) p['q'] = q;
    if (status == 'undated') p['undated'] = 'true';
    if (status == 'hidden') p['hidden'] = 'true';
    if (const ['due', 'missed', 'completed'].contains(status)) p['status'] = status;
    if (f.source.isNotEmpty) p['source'] = f.source;
    if (f.batch.isNotEmpty) p['batch'] = f.batch;
    if (f.type.isNotEmpty) p['type'] = f.type;
    if (f.subject.isNotEmpty) p['subjectId'] = f.subject;
    if (f.kind.isNotEmpty) p['subjectKind'] = f.kind;
    if (f.priority.isNotEmpty) p['priority'] = f.priority;
    if (f.date.isNotEmpty) {
      p['dateFrom'] = istMidnight(f.date);
      p['dateTo'] = istMidnight(addDays(f.date, 1));
    }
    return Uri(queryParameters: p).query;
  }

  void chooseSort(String value) {
    setState(() => sort = value);
    SharedPreferences.getInstance().then((p) => p.setString(_sortKey, value));
  }

  Future<void> _complete(Task t) async {
    final services = AppScope.of(context);
    HapticFeedback.mediumImpact();
    final done = t.status != 'completed';
    try {
      await services.api.send('PATCH', '/tasks/${t.id}', body: {'revision': t.revision, 'status': done ? 'completed' : 'due'});
      await services.queries.invalidate(taskRoots);
      if (!mounted) return;
      toast(context, done ? 'Marked done: ${t.title}' : 'Reopened: ${t.title}', action: 'Undo', onAction: () async {
        final fresh = Task((await services.api.get('/tasks/${t.id}')) as Map<String, dynamic>);
        await services.api.send('PATCH', '/tasks/${t.id}', body: {'revision': fresh.revision, 'status': done ? 'due' : 'completed'});
        await services.queries.invalidate(taskRoots);
      });
    } on ApiError catch (e) {
      if (mounted) toast(context, e.message);
    }
  }

  Future<bool> _delete(Task t) async {
    if (!await confirm(context, title: 'Delete this task?', body: '“${t.title}” and its history are deleted.', action: 'Delete')) {
      return false;
    }
    if (!mounted) return false;
    final services = AppScope.of(context);
    try {
      await services.api.send('DELETE', '/tasks/${t.id}?revision=${t.revision}');
      await services.queries.invalidate(taskRoots);
      return true;
    } on ApiError catch (e) {
      if (mounted) toast(context, e.message);
      return false;
    }
  }

  Future<void> _bulk(Map<String, dynamic> body) async {
    final services = AppScope.of(context);
    setState(() => bulkPending = true);
    try {
      final r = (await services.api.send('POST', '/tasks/bulk', body: {'taskIds': selected!.toList(), ...body})) as Map;
      await services.queries.invalidate(['tasks', 'overview', 'task']);
      if (mounted) {
        toast(context, '${r['count']} ${r['count'] == 1 ? 'task' : 'tasks'} updated');
        setState(() => selected = null);
      }
    } on ApiError catch (e) {
      if (mounted) toast(context, e.message);
    }
    if (mounted) setState(() => bulkPending = false);
  }

  Future<void> _openFilters(List<Subject> subjects) async {
    final chosen = await showModalBottomSheet<_Filters>(
      context: context,
      isScrollControlled: true,
      builder: (context) => _FilterSheet(initial: filters, subjects: subjects, batch: widget.batch),
    );
    if (chosen != null) setState(() => filters = chosen);
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final api = AppScope.of(context).api;
    final query = params;
    return QueryView(
      queryKey: Keys.subjects,
      fetch: () => loadSubjects(api),
      builder: (context, sq) {
        final subjects = subjectsOf(sq);
        return QueryView(
          queryKey: ['tasks', query],
          pager: (cursor) => api.get('/tasks?$query${cursor != null ? '&cursor=${Uri.encodeQueryComponent(cursor)}' : ''}'),
          builder: (context, tq) {
            final items = pageOf(tq.data).items.map(Task.new).toList();
            final selecting = selected != null;
            return Scaffold(
              floatingActionButton: selecting
                  ? null
                  : FloatingActionButton(heroTag: 'add-tasks', tooltip: 'Add task', onPressed: () => openEditor(context), child: const Icon(Icons.add_rounded)),
              bottomNavigationBar: selecting ? _bulkBar(subjects) : null,
              body: NotificationListener<ScrollNotification>(
                onNotification: (n) {
                  if (n.metrics.extentAfter < 400 && tq.hasMore && !tq.fetchingMore) tq.loadMore();
                  return false;
                },
                child: RefreshIndicator(
                  onRefresh: tq.refetch,
                  edgeOffset: 110,
                  child: CustomScrollView(
                    controller: scroll,
                    physics: const AlwaysScrollableScrollPhysics(parent: BouncingScrollPhysics()),
                    slivers: [
                      if (selecting)
                        SliverAppBar(
                          pinned: true,
                          backgroundColor: c.inkTint,
                          leading: IconButton(tooltip: 'Done selecting', icon: const Icon(Icons.close), onPressed: () => setState(() => selected = null)),
                          title: Text('${selected!.length} selected'),
                          actions: [
                            TextButton(
                              onPressed: () => setState(() {
                                selected = selected!.length == items.length ? {} : items.map((t) => t.id).toSet();
                              }),
                              child: Text(selected!.length == items.length ? 'Clear' : 'All'),
                            ),
                          ],
                        )
                      else
                        SliverAppBar.medium(
                          pinned: true,
                          title: Text('Tasks', style: display(context, 28)),
                          actions: [
                            IconButton(
                              tooltip: 'Search',
                              icon: Icon(searching ? Icons.search_off_rounded : Icons.search_rounded),
                              onPressed: () => setState(() {
                                searching = !searching;
                                if (!searching && q.isNotEmpty) {
                                  search.clear();
                                  q = '';
                                }
                              }),
                            ),
                            IconButton(
                              tooltip: 'Filters',
                              onPressed: () => _openFilters(subjects),
                              icon: Badge(isLabelVisible: filters.count > 0, label: Text('${filters.count}'), child: const Icon(Icons.tune_rounded)),
                            ),
                            PopupMenuButton<String>(
                              tooltip: 'Sort',
                              icon: const Icon(Icons.sort_rounded),
                              initialValue: sort,
                              onSelected: chooseSort,
                              itemBuilder: (_) => const [
                                PopupMenuItem(value: 'date', child: Text('Sort by due date')),
                                PopupMenuItem(value: 'priority', child: Text('Sort by priority')),
                              ],
                            ),
                            const SizedBox(width: 4),
                          ],
                        ),
                      SliverToBoxAdapter(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (searching)
                              Padding(
                                padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
                                child: TextField(
                                  controller: search,
                                  autofocus: true,
                                  textInputAction: TextInputAction.search,
                                  decoration: InputDecoration(
                                    hintText: 'Search tasks and notes',
                                    prefixIcon: Icon(Icons.search_rounded, color: c.ink),
                                    suffixIcon: search.text.isEmpty
                                        ? null
                                        : IconButton(
                                            tooltip: 'Clear search',
                                            icon: const Icon(Icons.close),
                                            onPressed: () => setState(() {
                                              search.clear();
                                              q = '';
                                            }),
                                          ),
                                  ),
                                  onChanged: (v) {
                                    _debounce?.cancel();
                                    _debounce = Timer(const Duration(milliseconds: 300), () => setState(() => q = v.trim()));
                                  },
                                ),
                              ),
                            SizedBox(
                              height: 44,
                              child: ListView(
                                scrollDirection: Axis.horizontal,
                                padding: const EdgeInsets.symmetric(horizontal: 16),
                                children: [
                                  for (final (value, label) in _statuses)
                                    Padding(
                                      padding: const EdgeInsets.only(right: 8),
                                      child: ChoiceChip(
                                        label: Text(label),
                                        selected: status == value,
                                        onSelected: (_) => setState(() => status = value),
                                      ),
                                    ),
                                ],
                              ),
                            ),
                            if (filters.count > 0)
                              Padding(
                                padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
                                child: Row(children: [
                                  Icon(Icons.filter_alt_outlined, size: 16, color: c.ink),
                                  const SizedBox(width: 6),
                                  Text('${filters.count} ${filters.count == 1 ? 'filter' : 'filters'} on', style: TextStyle(color: c.graphite2, fontWeight: FontWeight.w600)),
                                  const Spacer(),
                                  TextButton(onPressed: () => setState(() => filters = const _Filters()), child: const Text('Clear')),
                                ]),
                              ),
                            Padding(padding: const EdgeInsets.symmetric(horizontal: 16), child: ErrorNotice(tq.error, retry: tq.refetch)),
                          ],
                        ),
                      ),
                      if (tq.isPending)
                        const SliverToBoxAdapter(child: Loading('Loading tasks…'))
                      else if (items.isEmpty)
                        SliverToBoxAdapter(
                          child: EmptyState(
                            icon: q.isNotEmpty ? Icons.search_off_rounded : Icons.task_alt_rounded,
                            title: q.isNotEmpty ? 'No matches' : 'Nothing here',
                            body: q.isNotEmpty ? 'Try other words, or clear the filters.' : 'Try another filter, or add something you need to do.',
                          ),
                        )
                      else
                        SliverPadding(
                          padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                          sliver: SliverList.separated(
                            itemCount: items.length,
                            separatorBuilder: (_, _) => const SizedBox(height: 8),
                            itemBuilder: (context, i) {
                              final t = items[i];
                              final row = TaskRow(
                                task: t,
                                onOpen: () => openTask(context, t.id),
                                selected: selected?.contains(t.id),
                                onToggle: () => setState(() => selected!.contains(t.id) ? selected!.remove(t.id) : selected!.add(t.id)),
                                onLongPress: selecting
                                    ? null
                                    : () {
                                        HapticFeedback.selectionClick();
                                        // The bulk bar takes the bottom of the screen.
                                        ScaffoldMessenger.of(context).hideCurrentSnackBar();
                                        setState(() => selected = {t.id});
                                      },
                              );
                              if (selecting) return row;
                              return _Swipe(task: t, onComplete: () => _complete(t), onDelete: () => _delete(t), child: row);
                            },
                          ),
                        ),
                      SliverToBoxAdapter(
                        child: Padding(
                          padding: const EdgeInsets.fromLTRB(16, 16, 16, 120),
                          child: Center(
                            child: tq.fetchingMore
                                ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.4))
                                : Text(
                                    items.isEmpty || tq.hasMore ? '' : '${items.length} ${items.length == 1 ? 'task' : 'tasks'}',
                                    style: TextStyle(color: c.graphite2),
                                  ),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            );
          },
        );
      },
    );
  }

  Widget _bulkBar(List<Subject> subjects) {
    final c = Palette.of(context);
    final none = (selected?.isEmpty ?? true) || bulkPending;
    Widget action(IconData icon, String label, VoidCallback? onTap, {bool danger = false}) => Expanded(
          child: InkWell(
            onTap: onTap,
            borderRadius: BorderRadius.circular(Radii.medium),
            child: Opacity(
              opacity: onTap == null ? 0.4 : 1,
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 10),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  Icon(icon, color: danger ? c.bad : c.graphite),
                  const SizedBox(height: 4),
                  Text(label, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: danger ? c.bad : c.graphite)),
                ]),
              ),
            ),
          ),
        );
    return Container(
      decoration: BoxDecoration(color: c.sheet, border: Border(top: BorderSide(color: c.inkRule))),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          child: Row(children: [
            action(Icons.check_circle_outline, 'Done', none ? null : () => _bulk({'action': 'complete'})),
            action(Icons.replay_rounded, 'Reopen', none ? null : () => _bulk({'action': 'reopen'})),
            action(Icons.drive_file_move_outline, 'Move', none
                ? null
                : () async {
                    final picked = await pick<String>(context, title: 'Move to subject', options: [for (final s in subjects) (s.id, s.label)]);
                    if (picked != null) await _bulk({'action': 'subject', 'subjectId': picked.$1});
                  }),
            action(Icons.delete_outline, 'Delete', none
                ? null
                : () async {
                    final n = selected!.length;
                    if (await confirm(context,
                        title: 'Delete $n ${n == 1 ? 'task' : 'tasks'}?',
                        body: 'Their history is deleted too. Imported work stays deleted during future syncs.',
                        action: 'Delete')) {
                      await _bulk({'action': 'delete'});
                    }
                  }, danger: true),
          ]),
        ),
      ),
    );
  }
}

/// Swipe right to mark done (or reopen), left to delete.
class _Swipe extends StatelessWidget {
  const _Swipe({required this.task, required this.onComplete, required this.onDelete, required this.child});

  final Task task;
  final VoidCallback onComplete;
  final Future<bool> Function() onDelete;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final done = task.status == 'completed';
    Widget bg(Color color, Color fg, IconData icon, String label, Alignment align) => Container(
          decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(Radii.card)),
          padding: const EdgeInsets.symmetric(horizontal: 24),
          alignment: align,
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(icon, color: fg),
            const SizedBox(width: 8),
            Text(label, style: TextStyle(color: fg, fontWeight: FontWeight.w800)),
          ]),
        );
    return Dismissible(
      key: ValueKey('swipe-${task.id}-${task.revision}'),
      background: done
          ? bg(c.dueTint, c.dueText, Icons.replay_rounded, 'Reopen', Alignment.centerLeft)
          : bg(c.good, c.onGood, Icons.check_rounded, 'Done', Alignment.centerLeft),
      secondaryBackground: bg(c.bad, c.onBad, Icons.delete_outline, 'Delete', Alignment.centerRight),
      confirmDismiss: (direction) async {
        if (direction == DismissDirection.startToEnd) {
          onComplete();
          return false; // The list reloads with the new status.
        }
        return onDelete();
      },
      child: child,
    );
  }
}

class _FilterSheet extends StatefulWidget {
  const _FilterSheet({required this.initial, required this.subjects, required this.batch});

  final _Filters initial;
  final List<Subject> subjects;
  final String? batch;

  @override
  State<_FilterSheet> createState() => _FilterSheetState();
}

class _FilterSheetState extends State<_FilterSheet> {
  late _Filters f = widget.initial;

  Widget _chips(String label, String value, List<(String, String)> options, _Filters Function(String) set) => Padding(
        padding: const EdgeInsets.only(bottom: 14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text(label, style: TextStyle(fontWeight: FontWeight.w700, color: Palette.of(context).graphite2)),
          ),
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final (v, l) in options)
              ChoiceChip(label: Text(l), selected: value == v, onSelected: (_) => setState(() => f = set(value == v ? '' : v))),
          ]),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * 0.85),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(24, 0, 12, 8),
            child: Row(children: [
              Expanded(child: Text('Filters', style: display(context, 24))),
              TextButton(onPressed: () => setState(() => f = const _Filters()), child: const Text('Reset')),
            ]),
          ),
          Flexible(
            child: ListView(
              shrinkWrap: true,
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 8),
              children: [
                _chips('Type', f.type, const [('assignment', 'Assignments'), ('test', 'Tests')], (v) => f.copy(type: v)),
                _chips('Priority', f.priority, const [('critical', 'Critical'), ('high', 'High'), ('medium', 'Medium'), ('low', 'Low')],
                    (v) => f.copy(priority: v)),
                _chips('Subject kind', f.kind, const [('theory', 'Theory'), ('lab', 'Lab'), ('tutorial', 'Tutorial')], (v) => f.copy(kind: v)),
                _chips('Source', f.source, const [('manual', 'Added by me'), ('gmail', 'Gmail'), ('classroom', 'Classroom')],
                    (v) => f.copy(source: v)),
                if (widget.batch != null) _chips('Batch', f.batch, [(widget.batch!, 'Batch ${widget.batch}')], (v) => f.copy(batch: v)),
                Field(
                  label: 'Subject',
                  child: SelectField<String>(
                    value: f.subject,
                    title: 'Subject',
                    options: [('', 'All subjects'), for (final s in widget.subjects) (s.id, s.label)],
                    onChanged: (v) => setState(() => f = f.copy(subject: v)),
                  ),
                ),
                Field(label: 'Due on', child: DateField(value: f.date, placeholder: 'Any day', onChanged: (v) => setState(() => f = f.copy(date: v)))),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(24, 8, 24, 12),
            child: DueButton(label: 'Show tasks', expand: true, onPressed: () => Navigator.pop(context, f)),
          ),
        ]),
      ),
    );
  }
}
