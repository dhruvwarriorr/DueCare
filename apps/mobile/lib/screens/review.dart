import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/ist.dart';
import '../core/models.dart';
import '../core/query.dart';
import '../state/data.dart';
import '../state/services.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'sources.dart';

const _titles = {
  'confirm_applicability': 'Is this for you?',
  'choose_subject': 'Choose a subject',
  'timing_unresolved': 'Timing not settled',
  'possible_duplicate': 'Possible duplicate',
  'association': 'Which task is this about?',
  'conflict': 'Sources disagree',
  'confirm_completion': 'Submission found',
  'receipt_unverified': 'Unverified submission evidence',
  'returned_ambiguous': 'Returned work',
  'unsubmission': 'Work was unsubmitted',
  'withdrawal': 'Requirement withdrawn',
};
const _timeFields = [
  ('dueAt', 'Deadline / cutoff'),
  ('startsAt', 'Test starts'),
  ('reportingAt', 'Report at'),
  ('availabilityClosesAt', 'Online window closes'),
];
const _sourceLabel = {
  'gmail_message': 'Gmail',
  'classroom_coursework': 'Classroom coursework',
  'classroom_announcement': 'Classroom announcement',
  'classroom_submission': 'Classroom submission',
};

/// Imported work DueCare could not settle on its own (apps/web needs-attention.tsx).
class ReviewScreen extends StatelessWidget {
  const ReviewScreen({super.key, this.targetId});

  /// Show one item (opened from Activity) instead of the list.
  final String? targetId;

  @override
  Widget build(BuildContext context) {
    final api = AppScope.of(context).api;
    final body = QueryView(
      queryKey: Keys.subjects,
      fetch: () => loadSubjects(api),
      builder: (context, sq) => QueryView(
        queryKey: const ['tasks', 'review-picker'],
        pager: (cursor) => api.get('/tasks?limit=100${cursor != null ? '&cursor=${Uri.encodeQueryComponent(cursor)}' : ''}'),
        builder: (context, tq) {
          final subjects = subjectsOf(sq);
          final tasks = pageOf(tq.data).items.map(Task.new).toList();
          final header = SectionHeader(
            title: 'Needs attention',
            subtitle: 'Imported work DueCare could not settle on its own. Nothing here is a task until you confirm it. '
                'Work for another division or batch is ignored, not shown here.',
          );
          Widget list(List<ReviewItem> items, Query q) => RefreshIndicator(
                onRefresh: q.refetch,
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
                  children: [
                    header,
                    ErrorNotice(q.error, retry: q.refetch),
                    if (q.isPending)
                      const Loading('Loading items…')
                    else if (items.isEmpty)
                      const EmptyState(
                        icon: Icons.inbox_outlined,
                        title: 'Nothing needs your attention',
                        body: 'Questions about imported work will appear here.',
                      )
                    else
                      for (final item in items)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 14),
                          child: ReviewCard(key: ValueKey('${item.id}${item.revision}'), item: item, subjects: subjects, tasks: tasks),
                        ),
                    if (q.hasMore) DueButton(label: 'Load more', variant: Variant.outline, onPressed: q.loadMore),
                    if (tq.hasMore) DueButton(label: 'Load more tasks for linking', variant: Variant.ghost, onPressed: tq.loadMore),
                  ],
                ),
              );
          if (targetId != null) {
            return QueryView(
              queryKey: ['review-item', targetId],
              fetch: () => api.get('/review-items/$targetId'),
              builder: (context, q) => list(q.data is Map ? [ReviewItem((q.data as Map).cast<String, dynamic>())] : [], q),
            );
          }
          return QueryView(
            queryKey: const ['review-items'],
            pager: (cursor) => api.get('/review-items${cursor != null ? '?cursor=${Uri.encodeQueryComponent(cursor)}' : ''}'),
            builder: (context, q) => list(pageOf(q.data).items.map(ReviewItem.new).toList(), q),
          );
        },
      ),
    );
    if (targetId == null) return body;
    return Scaffold(appBar: AppBar(title: const Text('Needs attention')), body: body);
  }
}

class ReviewCard extends StatefulWidget {
  const ReviewCard({super.key, required this.item, required this.subjects, required this.tasks});

  final ReviewItem item;
  final List<Subject> subjects;
  final List<Task> tasks;

  @override
  State<ReviewCard> createState() => _ReviewCardState();
}

class _ReviewCardState extends State<ReviewCard> {
  late final ReviewItem item = widget.item;
  late final List<Subject> choices =
      item.subjectChoices.isNotEmpty ? widget.subjects.where((s) => item.subjectChoices.contains(s.id)).toList() : widget.subjects;
  late String subjectId = '${item.proposal['subjectId'] ?? (choices.length == 1 ? choices.first.id : '')}';
  late String type = '${item.proposal['type'] ?? ''}';
  late bool remember = item.courseLabel != null;
  late String taskId = item.taskId ?? '';
  final Map<String, ({String date, String time})> times = {};
  bool pending = false;
  Object? error;

  Future<void> resolve(Map<String, dynamic> body) async {
    final services = AppScope.of(context);
    setState(() {
      pending = true;
      error = null;
    });
    try {
      await services.api.send('POST', '/review-items/${item.id}/resolve', body: {'revision': item.revision, ...body});
      await services.queries.invalidate(['review-items', 'review-item', 'tasks', 'overview', 'task', 'subjects', 'approved-faculty', 'me']);
    } on ApiError catch (e) {
      error = e;
    }
    if (mounted) setState(() => pending = false);
  }

  void accept() {
    final fields = <String, String?>{};
    if (type.isNotEmpty) fields['type'] = type;
    for (final e in times.entries) {
      final (:date, :time) = e.value;
      // A deadline with only a date is due by 23:59 that day; a test start needs its time.
      final value = date.isNotEmpty && time.isNotEmpty ? '${date}T$time' : (date.isNotEmpty && e.key == 'dueAt' ? '${date}T23:59' : '');
      if (value.isNotEmpty) fields[e.key] = utcTime(value);
    }
    resolve({
      'action': 'accept',
      'subjectId': subjectId.isEmpty ? null : subjectId,
      'rememberAlias': remember && item.courseLabel != null,
      'fields': fields,
    });
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final p = item.proposal;
    final creates = const ['confirm_applicability', 'choose_subject', 'timing_unresolved'].contains(item.issueType);
    final title = item.taskTitle ?? (p['title'] as String?);
    final disabled = pending;
    return Panel(
      hatched: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Printed(_titles[item.issueType] ?? item.issueType),
          const SizedBox(height: 4),
          Text(
            '${_sourceLabel[item.sourceKind] ?? 'Source'}${item.senderEmail != null ? ' · ${item.senderEmail}' : ''} · ${formatTime(item.createdAt)}',
            style: TextStyle(fontSize: 12.5, color: c.graphite2),
          ),
          const SizedBox(height: 8),
          Text(item.question, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
          if (title != null)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text.rich(TextSpan(children: [
                TextSpan(text: title, style: const TextStyle(fontWeight: FontWeight.w700)),
                if (p['type'] != null) TextSpan(text: ' · ${p['type']}'),
                if (item.sourceTitle != null && item.sourceTitle != p['title']) TextSpan(text: ' — from “${item.sourceTitle}”'),
              ])),
            ),
          if (item.excerpt != null)
            Container(
              margin: const EdgeInsets.only(top: 10),
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
              decoration: BoxDecoration(color: c.sheet, border: Border(left: BorderSide(color: c.ink, width: 3))),
              child: Text(item.excerpt!, style: TextStyle(color: c.graphite2, fontSize: 14)),
            ),
          if (item.issueType == 'confirm_applicability') _Targeting(item: item),
          if (item.window != null && item.window!.length == 2)
            _Line('Date window: ${item.window![0]} to ${item.window![1]}. Accepting keeps the window without a precise cutoff.'),
          if (item.alternatives.isNotEmpty) _Line('Tentative alternatives: ${item.alternatives.join(' or ')}'),
          for (final (k, label) in _timeFields)
            if (p[k] != null)
              _Line('$label: ${formatTime('${p[k]}')}${k == 'dueAt' && p['dueDate'] != null ? '\nDate only; default 11:59 pm IST' : ''}'),
          if (item.conflicts != null) _Conflicts(conflicts: item.conflicts!),
          if (item.evidenceCount > 1) _Line('${item.evidenceCount} source messages ask the same question.'),
          if (creates) ...[
            const SizedBox(height: 12),
            Field(
              label: 'Subject',
              child: SelectField<String>(
                value: subjectId.isEmpty ? null : subjectId,
                placeholder: 'Choose a subject',
                title: 'Subject',
                options: [for (final s in choices) (s.id, s.label)],
                onChanged: (v) => setState(() => subjectId = v),
              ),
            ),
            if (p['type'] == null)
              Field(
                label: 'Type',
                child: BubbleChoice<String>(
                  value: type,
                  options: const [('assignment', 'Assignment'), ('test', 'Test')],
                  onChanged: (v) => setState(() => type = v),
                ),
              ),
            if (item.issueType == 'timing_unresolved')
              for (final k in ['dueAt', 'startsAt'])
                Field(
                  label: '${k == 'dueAt' ? 'Deadline' : 'Test start'} (IST, optional)',
                  child: _DateTime(
                    initial: localTime(p[k] as String?),
                    onChanged: (v) => times[k] = v,
                  ),
                ),
            if (item.courseLabel != null)
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                value: remember,
                title: Text('Remember “${item.courseLabel}” for this subject'),
                onChanged: (v) => setState(() => remember = v ?? false),
              ),
          ],
          if (item.issueType == 'association')
            Field(
              label: 'Task',
              child: SelectField<String>(
                value: taskId.isEmpty ? null : taskId,
                placeholder: 'Choose a task',
                title: 'Task',
                options: [for (final t in widget.tasks) (t.id, t.title)],
                onChanged: (v) => setState(() => taskId = v),
              ),
            ),
          if (item.sourceKind == 'gmail_message' && item.senderEmail != null) FacultyApproval(emails: [item.senderEmail!]),
          ErrorNotice(error),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              if (creates)
                DueButton(
                  label: item.issueType == 'timing_unresolved' ? 'Accept with this timing' : 'Add task',
                  icon: Icons.check,
                  onPressed: disabled || type.isEmpty ? null : accept,
                ),
              if (item.issueType == 'possible_duplicate') ...[
                DueButton(label: 'Same work', icon: Icons.link, onPressed: disabled ? null : () => resolve({'action': 'link'})),
                DueButton(
                  label: 'Separate task',
                  variant: Variant.outline,
                  onPressed: disabled ? null : () => resolve({'action': 'accept', 'subjectId': p['subjectId']}),
                ),
              ],
              if (item.issueType == 'association')
                DueButton(label: 'Link', icon: Icons.link, onPressed: disabled || taskId.isEmpty ? null : () => resolve({'action': 'link', 'taskId': taskId})),
              if (item.issueType == 'conflict') ...[
                DueButton(label: 'Use source values', onPressed: disabled ? null : () => resolve({'action': 'apply_update'})),
                DueButton(label: 'Keep current', variant: Variant.outline, onPressed: disabled ? null : () => resolve({'action': 'keep_current'})),
              ],
              if (const ['confirm_completion', 'receipt_unverified', 'returned_ambiguous'].contains(item.issueType))
                DueButton(label: 'Mark completed', icon: Icons.check, onPressed: disabled ? null : () => resolve({'action': 'complete'})),
              if (item.issueType == 'unsubmission') ...[
                DueButton(label: 'Reopen', onPressed: disabled ? null : () => resolve({'action': 'reopen'})),
                DueButton(label: 'Keep completed', variant: Variant.outline, onPressed: disabled ? null : () => resolve({'action': 'keep_current'})),
              ],
              if (item.issueType == 'withdrawal') ...[
                DueButton(label: 'Delete task', variant: Variant.destructive, onPressed: disabled ? null : () => resolve({'action': 'delete_task'})),
                DueButton(label: 'Keep task', variant: Variant.outline, onPressed: disabled ? null : () => resolve({'action': 'keep_task'})),
              ],
              DueButton(label: 'Dismiss', icon: Icons.close, variant: Variant.ghost, onPressed: disabled ? null : () => resolve({'action': 'dismiss'})),
            ],
          ),
        ],
      ),
    );
  }
}

class _Line extends StatelessWidget {
  const _Line(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(padding: const EdgeInsets.only(top: 8), child: Text(text, style: const TextStyle(fontSize: 14)));
}

/// What the source says it targets, beside the student's own profile.
class _Targeting extends StatelessWidget {
  const _Targeting({required this.item});

  final ReviewItem item;

  @override
  Widget build(BuildContext context) {
    final observed = {...?(item.observed?['course'] as Map?), ...?(item.observed?['activity'] as Map?)};
    final shown = [
      for (final k in ['branches', 'classYears', 'semesters', 'divisions', 'batches'])
        if (observed[k] is List && (observed[k] as List).isNotEmpty) '${k.replaceFirst(RegExp(r's$'), '')}: ${(observed[k] as List).join(', ')}',
    ];
    final s = item.student ?? {};
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Printed('Source mentions'),
          Text('${shown.isEmpty ? 'No branch, class, division, or batch stated' : shown.join(' · ')}${observed['allBatches'] == true ? ' · all batches' : ''}'),
          const SizedBox(height: 6),
          const Printed('Your profile'),
          Text('${s['branchCode'] != null ? '${s['branchCode']} · ' : ''}${s['classYear']} · Semester ${s['currentSemester']} · '
              'Division ${s['division']} · Batch ${s['generalBatch']}'),
        ],
      ),
    );
  }
}

class _Conflicts extends StatelessWidget {
  const _Conflicts({required this.conflicts});

  final Json conflicts;

  String _show(Object? v) {
    final s = '${v ?? '—'}';
    return s.contains('T') && DateTime.tryParse(s) != null ? formatTime(s) : s;
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Container(
      margin: const EdgeInsets.only(top: 10),
      decoration: BoxDecoration(border: Border.all(color: c.inkLine), color: c.sheet),
      child: Table(
        border: TableBorder.symmetric(inside: BorderSide(color: c.inkRule)),
        children: [
          const TableRow(children: [_Cell('Field', head: true), _Cell('Current', head: true), _Cell('Source says', head: true)]),
          for (final e in conflicts.entries)
            TableRow(children: [
              _Cell(e.key),
              _Cell(_show((e.value as Map)['current'])),
              _Cell(_show((e.value as Map)['proposed'])),
            ]),
        ],
      ),
    );
  }
}

class _Cell extends StatelessWidget {
  const _Cell(this.text, {this.head = false});

  final String text;
  final bool head;

  @override
  Widget build(BuildContext context) =>
      Padding(padding: const EdgeInsets.all(8), child: head ? Printed(text, size: 10.5) : Text(text, style: const TextStyle(fontSize: 13)));
}

/// A date and a time for a review answer, both IST.
class _DateTime extends StatefulWidget {
  const _DateTime({required this.initial, required this.onChanged});

  final String initial;
  final ValueChanged<({String date, String time})> onChanged;

  @override
  State<_DateTime> createState() => _DateTimeState();
}

class _DateTimeState extends State<_DateTime> {
  late String date = widget.initial.length >= 10 ? widget.initial.substring(0, 10) : '';
  late String time = widget.initial.length >= 16 ? widget.initial.substring(11, 16) : '';

  void emit() {
    setState(() {});
    widget.onChanged((date: date, time: time));
  }

  @override
  Widget build(BuildContext context) => Column(
        children: [
          DateField(value: date, onChanged: (v) {
            date = v;
            emit();
          }),
          const SizedBox(height: 6),
          TimeField(value: time, enabled: date.isNotEmpty, onChanged: (v) {
            time = v;
            emit();
          }),
        ],
      );
}
