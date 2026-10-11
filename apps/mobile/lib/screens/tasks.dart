import 'dart:async';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/api.dart';
import '../core/models.dart';
import '../core/query.dart';
import '../state/data.dart';
import '../state/services.dart';
import '../ui/task_tiles.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'workspace.dart';

/// All tasks, with search, the status bubbles, more filters, sorting and bulk actions
/// (apps/web workspace.tsx › TaskList).
class TasksScreen extends StatefulWidget {
  const TasksScreen({super.key, this.initialStatus = '', this.batch});

  final String initialStatus;
  final String? batch;

  @override
  State<TasksScreen> createState() => _TasksScreenState();
}

class _TasksScreenState extends State<TasksScreen> {
  final search = TextEditingController();
  Timer? _debounce;
  String q = '';
  late String status = widget.initialStatus == 'undated' ? '' : widget.initialStatus;
  late bool undated = widget.initialStatus == 'undated';
  bool hidden = false;
  String source = '', batch = '', type = '', subject = '', kind = '', priority = '', date = '';
  String sort = 'date';
  Set<String>? selected;
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
    super.dispose();
  }

  int get extra => [source, batch, type, subject, kind, priority, date].where((v) => v.isNotEmpty).length + (undated ? 1 : 0) + (hidden ? 1 : 0);

  String get params {
    final p = <String, String>{'sort': sort};
    if (q.isNotEmpty) p['q'] = q;
    if (undated) p['undated'] = 'true';
    if (hidden) p['hidden'] = 'true';
    if (status.isNotEmpty) p['status'] = status;
    if (source.isNotEmpty) p['source'] = source;
    if (batch.isNotEmpty) p['batch'] = batch;
    if (type.isNotEmpty) p['type'] = type;
    if (subject.isNotEmpty) p['subjectId'] = subject;
    if (kind.isNotEmpty) p['subjectKind'] = kind;
    if (priority.isNotEmpty) p['priority'] = priority;
    if (date.isNotEmpty) {
      final next = DateTime.parse(date).add(const Duration(days: 1));
      p['dateFrom'] = '${date}T00:00:00+05:30';
      p['dateTo'] = '${next.year}-${next.month.toString().padLeft(2, '0')}-${next.day.toString().padLeft(2, '0')}T00:00:00+05:30';
    }
    return Uri(queryParameters: p).query;
  }

  void reset() => setState(() {
        search.clear();
        q = status = source = batch = type = subject = kind = priority = date = '';
        undated = hidden = false;
      });

  void chooseSort(String value) {
    setState(() => sort = value);
    SharedPreferences.getInstance().then((p) => p.setString(_sortKey, value));
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
            return RefreshIndicator(
              onRefresh: tq.refetch,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
                children: [
                  SectionHeader(
                    title: 'All tasks',
                    subtitle: sort == 'date'
                        ? 'Upcoming work soonest first, then missed, undated and completed.'
                        : 'Upcoming work by priority, then missed and completed.',
                    actions: [
                      DueButton(
                        label: selected != null ? 'Done selecting' : 'Select',
                        small: true,
                        variant: Variant.outline,
                        onPressed: () => setState(() => selected = selected == null ? {} : null),
                      ),
                      SizedBox(
                        width: 190,
                        child: SelectField<String>(
                          value: sort,
                          title: 'Sort by',
                          options: const [('date', 'Sort by due date'), ('priority', 'Sort by priority')],
                          onChanged: chooseSort,
                        ),
                      ),
                    ],
                  ),
                  TextField(
                    controller: search,
                    decoration: InputDecoration(
                      hintText: 'Search tasks or notes',
                      prefixIcon: Icon(Icons.search, color: c.ink),
                    ),
                    onChanged: (v) {
                      _debounce?.cancel();
                      _debounce = Timer(const Duration(milliseconds: 250), () => setState(() => q = v.trim()));
                    },
                  ),
                  const SizedBox(height: 10),
                  BubbleChoice<String>(
                    value: status,
                    options: const [('', 'All'), ('due', 'Due'), ('missed', 'Missed'), ('completed', 'Completed')],
                    onChanged: (v) => setState(() => status = v),
                  ),
                  _MoreFilters(
                    count: extra,
                    children: [
                      _filter('Type', type, [('', 'All types'), ('assignment', 'Assignment'), ('test', 'Test')], (v) => type = v),
                      _filter('Subject', subject, [('', 'All subjects'), for (final s in subjects) (s.id, s.label)], (v) => subject = v),
                      _filter('Kind', kind, [('', 'All subject kinds'), ('theory', 'Theory'), ('lab', 'Lab'), ('tutorial', 'Tutorial')], (v) => kind = v),
                      _filter('Priority', priority,
                          [('', 'All priorities'), ('critical', 'Critical'), ('high', 'High'), ('medium', 'Medium'), ('low', 'Low')], (v) => priority = v),
                      Field(label: 'Cutoff date', child: DateField(value: date, placeholder: 'Any date', onChanged: (v) => setState(() => date = v))),
                      _filter('Source', source, [('', 'All sources'), ('manual', 'Student entered'), ('gmail', 'Gmail'), ('classroom', 'Classroom')],
                          (v) => source = v),
                      _filter('Batch', batch, [('', 'All applicable batches'), if (widget.batch != null) (widget.batch!, 'Batch ${widget.batch}')],
                          (v) => batch = v),
                      CheckboxListTile(
                        contentPadding: EdgeInsets.zero,
                        controlAffinity: ListTileControlAffinity.leading,
                        value: undated,
                        title: const Text('No due date yet'),
                        onChanged: (v) => setState(() => undated = v ?? false),
                      ),
                      CheckboxListTile(
                        contentPadding: EdgeInsets.zero,
                        controlAffinity: ListTileControlAffinity.leading,
                        value: hidden,
                        title: const Text('Only work hidden by rules'),
                        onChanged: (v) => setState(() => hidden = v ?? false),
                      ),
                      Align(alignment: Alignment.centerLeft, child: DueButton(label: 'Reset filters', variant: Variant.ghost, onPressed: reset)),
                    ],
                  ),
                  ErrorNotice(tq.error, retry: tq.refetch),
                  if (selected != null && items.isNotEmpty)
                    _BulkBar(
                      selected: selected!,
                      visible: items,
                      subjects: subjects,
                      onSelect: (s) => setState(() => selected = s),
                      onDone: () => setState(() => selected = {}),
                    ),
                  if (tq.isPending)
                    const Loading('Loading tasks…')
                  else if (items.isEmpty)
                    const EmptyState(
                      icon: Icons.checklist,
                      title: 'No tasks in this view',
                      body: 'Try another filter, or add something you need to do.',
                    )
                  else
                    Container(
                      decoration: BoxDecoration(border: Border.all(color: c.inkLine)),
                      child: Column(
                        children: [
                          for (final t in items)
                            TaskRow(
                              task: t,
                              onOpen: () => openTask(context, t.id),
                              selected: selected?.contains(t.id),
                              onToggle: () => setState(() {
                                selected!.contains(t.id) ? selected!.remove(t.id) : selected!.add(t.id);
                              }),
                            ),
                        ],
                      ),
                    ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Text(items.isEmpty ? '' : '${items.length}${tq.hasMore ? '+' : ''} shown', style: TextStyle(color: c.graphite2)),
                      const Spacer(),
                      if (tq.hasMore)
                        DueButton(
                          label: tq.fetchingMore ? 'Loading…' : 'Load more tasks',
                          variant: Variant.outline,
                          onPressed: tq.fetchingMore ? null : tq.loadMore,
                        ),
                    ],
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }

  Widget _filter(String label, String value, List<(String, String)> options, void Function(String) set) => Field(
        label: label,
        child: SelectField<String>(value: value, title: label, options: options, onChanged: (v) => setState(() => set(v))),
      );
}

/// "More filters" disclosure with the count of active filters.
class _MoreFilters extends StatefulWidget {
  const _MoreFilters({required this.count, required this.children});

  final int count;
  final List<Widget> children;

  @override
  State<_MoreFilters> createState() => _MoreFiltersState();
}

class _MoreFiltersState extends State<_MoreFilters> {
  late bool open = widget.count > 0;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        InkWell(
          onTap: () => setState(() => open = !open),
          child: SizedBox(
            height: 44,
            child: Row(
              children: [
                AnimatedRotation(
                  turns: open ? 0.25 : 0,
                  duration: const Duration(milliseconds: 260),
                  curve: const Cubic(0.16, 1, 0.3, 1),
                  child: Icon(Icons.chevron_right, color: c.ink),
                ),
                const Text('More filters', style: TextStyle(fontWeight: FontWeight.w600)),
                if (widget.count > 0)
                  Container(
                    margin: const EdgeInsets.only(left: 8),
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                    color: c.graphite,
                    child: Text('${widget.count}', style: display(context, 12, color: c.onGraphite)),
                  ),
              ],
            ),
          ),
        ),
        AnimatedSize(
          duration: const Duration(milliseconds: 300),
          curve: const Cubic(0.16, 1, 0.3, 1),
          child: open ? Padding(padding: const EdgeInsets.only(top: 6), child: Column(children: widget.children)) : const SizedBox(width: double.infinity),
        ),
        const SizedBox(height: 8),
      ],
    );
  }
}

/// Actions on every selected task at once, applied together by the server.
class _BulkBar extends StatefulWidget {
  const _BulkBar({required this.selected, required this.visible, required this.subjects, required this.onSelect, required this.onDone});

  final Set<String> selected;
  final List<Task> visible;
  final List<Subject> subjects;
  final ValueChanged<Set<String>> onSelect;
  final VoidCallback onDone;

  @override
  State<_BulkBar> createState() => _BulkBarState();
}

class _BulkBarState extends State<_BulkBar> {
  String subject = '';
  bool pending = false;
  Object? error;

  Future<void> run(Map<String, dynamic> body) async {
    final services = AppScope.of(context);
    setState(() {
      pending = true;
      error = null;
    });
    try {
      await services.api.send('POST', '/tasks/bulk', body: {'taskIds': widget.selected.toList(), ...body});
      await services.queries.invalidate(['tasks', 'overview']);
      widget.onDone();
    } on ApiError catch (e) {
      error = e;
    }
    if (mounted) setState(() => pending = false);
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final count = widget.selected.length;
    final none = count == 0 || pending;
    final all = count == widget.visible.length && count > 0;
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: c.inkWash, border: Border.all(color: c.graphite)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text('$count selected', style: const TextStyle(fontWeight: FontWeight.w700)),
              const Spacer(),
              DueButton(
                label: all ? 'Clear' : 'Select all shown',
                small: true,
                variant: Variant.ghost,
                onPressed: () => widget.onSelect(all ? {} : widget.visible.map((t) => t.id).toSet()),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              DueButton(label: 'Mark done', small: true, onPressed: none ? null : () => run({'action': 'complete'})),
              DueButton(label: 'Reopen', small: true, variant: Variant.outline, onPressed: none ? null : () => run({'action': 'reopen'})),
              DueButton(
                label: 'Delete',
                small: true,
                variant: Variant.ghost,
                onPressed: none
                    ? null
                    : () async {
                        if (await confirm(context,
                            title: 'Delete $count ${count == 1 ? 'task' : 'tasks'}?',
                            body: 'Their history is deleted too. Imported work stays deleted during future syncs.',
                            action: 'Delete')) {
                          await run({'action': 'delete'});
                        }
                      },
              ),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: SelectField<String>(
                  value: subject.isEmpty ? null : subject,
                  placeholder: 'Move to subject…',
                  title: 'Move to subject',
                  options: [for (final s in widget.subjects) (s.id, s.label)],
                  onChanged: (v) => setState(() => subject = v),
                ),
              ),
              const SizedBox(width: 8),
              DueButton(
                label: 'Move',
                variant: Variant.outline,
                onPressed: none || subject.isEmpty ? null : () => run({'action': 'subject', 'subjectId': subject}),
              ),
            ],
          ),
          ErrorNotice(error),
        ],
      ),
    );
  }
}
