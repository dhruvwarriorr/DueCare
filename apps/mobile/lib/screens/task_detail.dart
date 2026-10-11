import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/api.dart';
import '../core/deadline.dart';
import '../core/ist.dart';
import '../core/models.dart';
import '../core/query.dart';
import '../state/data.dart';
import '../state/services.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'workspace.dart';

const _origins = {
  'manual': 'Marked completed by you',
  'lms_assignment_receipt': 'LMS submission confirmation',
  'classroom_turned_in': 'Classroom shows turned in',
  'student_confirmed_evidence': 'Confirmed by you from submission evidence',
};
const _sourceNames = {'manual': 'Student entered', 'gmail': 'Gmail', 'classroom': 'Google Classroom'};
const _timeLabels = {
  'dueAt': 'Applicable cutoff',
  'submissionOpensAt': 'Submission opens',
  'availabilityOpensAt': 'Quiz window opens',
  'availabilityClosesAt': 'Quiz window closes',
  'loginByAt': 'Login by',
  'reportingAt': 'Report at',
  'startsAt': 'Test starts',
  'endsAt': 'Test ends',
};
const _detailLabels = {
  'assessmentLabel': 'Assessment',
  'deliverableLabel': 'Deliverable',
  'location': 'Location',
  'estimatedEffortMinutes': 'Estimated effort (minutes)',
  'durationMinutes': 'Duration (minutes)',
  'syllabus': 'Syllabus',
  'permittedTools': 'Permitted tools',
  'preparationInstructions': 'Preparation',
};

/// Instructions, timing, status and where a task came from (apps/web task-detail.tsx).
class TaskDetailScreen extends StatefulWidget {
  const TaskDetailScreen({super.key, required this.id});

  final String id;

  @override
  State<TaskDetailScreen> createState() => _TaskDetailScreenState();
}

class _TaskDetailScreenState extends State<TaskDetailScreen> {
  bool pending = false;
  Object? error;

  Future<void> _act(Task t, {required bool remove}) async {
    final services = AppScope.of(context);
    if (remove &&
        !await confirm(context, title: 'Delete this task?', body: 'The task and its history are deleted.', action: 'Confirm deletion', cancel: 'Keep task')) {
      return;
    }
    setState(() {
      pending = true;
      error = null;
    });
    try {
      if (remove) {
        await services.api.send('DELETE', '/tasks/${t.id}?revision=${t.revision}');
      } else {
        await services.api.send('PATCH', '/tasks/${t.id}', body: {
          'revision': t.revision,
          'status': t.status == 'completed' ? 'due' : 'completed',
        });
      }
      await services.queries.invalidate(taskRoots);
      if (remove && mounted) Navigator.pop(context);
    } on ApiError catch (e) {
      error = e;
    }
    if (mounted) setState(() => pending = false);
  }

  @override
  Widget build(BuildContext context) {
    final api = AppScope.of(context).api;
    return QueryView(
      queryKey: Keys.task(widget.id),
      fetch: () => api.get('/tasks/${widget.id}'),
      builder: (context, q) {
        final t = q.data is Map ? Task((q.data as Map).cast<String, dynamic>()) : null;
        return Scaffold(
          appBar: AppBar(title: const Text('Task details')),
          bottomNavigationBar: t == null
              ? null
              : _Footer(
                  children: [
                    DueButton(label: 'Delete', variant: Variant.ghost, onPressed: pending ? null : () => _act(t, remove: true)),
                    DueButton(label: 'Edit', variant: Variant.outline, onPressed: () => openEditor(context, t)),
                    Expanded(
                      child: DueButton(
                        label: t.status == 'completed' ? 'Reopen task' : 'Mark completed',
                        expand: true,
                        onPressed: pending ? null : () => _act(t, remove: false),
                      ),
                    ),
                  ],
                ),
          body: t == null
              ? (q.error != null ? Padding(padding: const EdgeInsets.all(16), child: ErrorNotice(q.error, retry: q.refetch)) : const Loading('Loading task…'))
              : RefreshIndicator(
                  onRefresh: () => AppScope.of(context).queries.invalidate(['task', 'evidence', 'history']),
                  child: _Body(task: t, error: error),
                ),
        );
      },
    );
  }
}

class _Footer extends StatelessWidget {
  const _Footer({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Container(
      decoration: BoxDecoration(color: c.sheet, border: Border(top: BorderSide(color: c.graphite))),
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      child: SafeArea(top: false, child: Row(spacing: 8, children: children)),
    );
  }
}

class _Body extends StatelessWidget {
  const _Body({required this.task, required this.error});

  final Task task;
  final Object? error;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final t = task;
    final link = t.subjectLink;
    final rows = <(String, Widget)>[
      (
        'Subject',
        _Value(
          '${t.subjectName ?? 'No subject'}${t.subjectKind != null ? ' · ${t.subjectKind}' : ''}',
          note: link != null && link['method'] != 'none'
              ? 'Linked automatically${link['method'] == 'ai' ? ' by AI from the course name' : ' from the course name'}. Edit the task to change it.'
              : link?['method'] == 'none' && t.subjectName == null
                  ? '${link?['reason'] == 'ai_unavailable' ? 'Couldn’t be linked automatically right now.' : 'None of your subjects matched.'} Edit the task to set one.'
                  : null,
        ),
      ),
      ('Batch', _Value(t.generalBatch ?? 'Not set')),
      ('Source', _Value((t.sources.isEmpty ? ['manual'] : t.sources).map((s) => _sourceNames[s] ?? s).join(', '))),
      (
        'Completion',
        _Value(
          t.completedAt != null
              ? '${_origins[t.completionOrigin ?? 'manual'] ?? 'Completed'} · ${formatTime(t.completedAt)}'
              : 'Not completed',
          note: classroomNote(t) != null ? 'Classroom: ${classroomNote(t)}' : null,
        ),
      ),
      for (final e in _timeLabels.entries)
        if (t[e.key] is String)
          (
            '${e.value} (IST)',
            _Value(
              formatTime(t[e.key] as String),
              note: [
                if (!const ['source-exact', 'student-entered', 'student-date-only', null].contains(t.basisOf(e.key)))
                  t.basisOf(e.key)!.replaceFirst('-', ' '),
                if (e.key == 'dueAt' && t.dueDate != null) 'Date only; default 23:59 IST',
              ].join('\n').ifEmpty,
            ),
          ),
      if (t.dueDate != null && t.isTest) ('Test date', _Value('${t.dueDate} · exact start not entered')),
      if (t.dateWindowStart != null)
        (
          'Date window',
          _Value(
            formatRange(t.dateWindowStart!, t.dateWindowEnd ?? t.dateWindowStart!),
            note: dueWindow(t) != null ? 'Exact day not announced; due by the last day' : null,
          ),
        ),
      if (t.timingTentative != null) ('Timing', _Value('Tentative', note: t.timingTentative?['question'] as String?)),
      for (final e in _detailLabels.entries)
        if (t[e.key] != null && '${t[e.key]}'.isNotEmpty) (e.value, _Value('${t[e.key]}')),
    ];
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
      children: [
        Text(t.title, style: display(context, 30)),
        if (t.sourceTitle != null && t.sourceTitle != t.title)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text('Original title: ${t.sourceTitle}', style: TextStyle(color: c.graphite2)),
          ),
        const SizedBox(height: 12),
        if (t.hiddenByRule != null)
          Notice(
            'Hidden from your lists by the rule “${t.hiddenByRule!['name'] ?? 'a rule'}”. '
            'Turn the rule off in More → Rules to show it again.',
            warn: true,
          ),
        Wrap(spacing: 8, runSpacing: 8, children: [StatusPill(t.status), Tag(t.type), Tag('${t.priority} priority')]),
        const SizedBox(height: 16),
        Container(
          decoration: BoxDecoration(border: Border.all(color: c.inkLine), color: c.sheet),
          child: Column(
            children: [
              for (final (label, value) in rows)
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(border: Border(bottom: BorderSide(color: c.inkRule))),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Printed(label), const SizedBox(height: 4), value]),
                ),
            ],
          ),
        ),
        _Sources(taskId: t.id),
        if (t.instructions.isNotEmpty) _Section('Instructions', SelectableText(t.instructions)),
        if (t.notes.isNotEmpty) _Section('Personal notes', SelectableText(t.notes)),
        _History(taskId: t.id),
        ErrorNotice(error),
      ],
    );
  }
}

extension on String {
  String? get ifEmpty => isEmpty ? null : this;
}

class _Value extends StatelessWidget {
  const _Value(this.text, {this.note});

  final String text;
  final String? note;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(text, style: const TextStyle(fontSize: 15)),
          if (note != null) Text(note!, style: TextStyle(fontSize: 12.5, color: Palette.of(context).graphite2)),
        ],
      );
}

class _Section extends StatelessWidget {
  const _Section(this.title, this.child);

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [Text(title, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)), const SizedBox(height: 6), child],
        ),
      );
}

const _kindNames = {
  'gmail_message': 'Email',
  'classroom_announcement': 'Classroom post',
  'classroom_coursework': 'Classroom assignment',
  'classroom_submission': 'Classroom turn-in',
};

/// Where the task came from: who posted it, when, and a link back to the original.
class _Sources extends StatelessWidget {
  const _Sources({required this.taskId});

  final String taskId;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final api = AppScope.of(context).api;
    return QueryView(
      queryKey: ['evidence', taskId],
      fetch: () => api.get('/tasks/$taskId/evidence'),
      builder: (context, q) {
        final seen = <String>{};
        // One row per original item; a turn-in only matters as proof of completion.
        final sources = pageOf(q.data).items.map(Evidence.new).where((e) {
          final key = e.openUrl ?? e.id;
          if (e.state != 'active' || e.eventType == 'submission' || seen.contains(key)) return false;
          seen.add(key);
          return true;
        }).toList();
        if (sources.isEmpty) return const SizedBox.shrink();
        return _Section(
          sources.length == 1 ? 'Source' : 'Sources',
          Column(
            children: [
              for (final e in sources)
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.symmetric(vertical: 10),
                  decoration: BoxDecoration(border: Border(bottom: BorderSide(color: c.inkRule))),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text.rich(TextSpan(children: [
                        TextSpan(text: _kindNames[e.sourceKind] ?? 'Source', style: const TextStyle(fontWeight: FontWeight.w700)),
                        TextSpan(
                          text: e.sourceKind == 'gmail_message'
                              ? (e.senderName ?? e.sender) != null
                                  ? ' from ${e.senderName ?? e.sender}'
                                  : ''
                              : '${e.postedBy != null ? ' by ${e.postedBy}' : ''}${e.courseName != null ? ' in ${e.courseName}' : ''}',
                        ),
                        if (e.postedAt != null) TextSpan(text: ' · posted ${formatTime(e.postedAt)}', style: TextStyle(color: c.graphite2)),
                      ])),
                      if (e.senderName != null && e.sender != null) Text(e.sender!, style: TextStyle(fontSize: 12.5, color: c.graphite2)),
                      if (e.sourceTitle != null || e.excerpt != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 4),
                          child: Text(e.sourceTitle ?? '“${e.excerpt}”', style: TextStyle(color: c.graphite2)),
                        ),
                      if (e.openUrl != null)
                        Align(
                          alignment: Alignment.centerLeft,
                          child: DueButton(
                            label: e.sourceKind == 'gmail_message' ? 'Open in Gmail ↗' : 'Open in Classroom ↗',
                            small: true,
                            variant: Variant.ghost,
                            onPressed: () => launchUrl(Uri.parse(e.openUrl!), mode: LaunchMode.externalApplication),
                          ),
                        ),
                    ],
                  ),
                ),
            ],
          ),
        );
      },
    );
  }
}

const _actions = {
  'created': 'Created',
  'edited': 'Edited',
  'completed': 'Marked completed',
  'reopened': 'Reopened',
  'subject_removed': 'Subject removed',
};

/// Every recorded change, newest first: evidence behind each task.
class _History extends StatefulWidget {
  const _History({required this.taskId});

  final String taskId;

  @override
  State<_History> createState() => _HistoryState();
}

class _HistoryState extends State<_History> {
  bool open = false;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final api = AppScope.of(context).api;
    return Padding(
      padding: const EdgeInsets.only(top: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            onTap: () => setState(() => open = !open),
            child: SizedBox(
              height: 44,
              child: Row(children: [
                AnimatedRotation(turns: open ? 0.25 : 0, duration: const Duration(milliseconds: 260), child: Icon(Icons.chevron_right, color: c.ink)),
                const Text('Change history', style: TextStyle(fontWeight: FontWeight.w600)),
              ]),
            ),
          ),
          if (open)
            QueryView(
              queryKey: ['history', widget.taskId],
              pager: (cursor) => api.get('/tasks/${widget.taskId}/history${cursor != null ? '?cursor=${Uri.encodeQueryComponent(cursor)}' : ''}'),
              builder: (context, q) {
                if (q.isPending) return const Loading('Loading history…');
                final items = pageOf(q.data).items.map(HistoryItem.new).toList();
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    ErrorNotice(q.error, retry: q.refetch),
                    for (final h in items)
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.symmetric(vertical: 8),
                        decoration: BoxDecoration(border: Border(bottom: BorderSide(color: c.inkRule))),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '${_actions[h.action] ?? h.action.replaceAll('_', ' ')}${h.actor != 'student' ? ' · by ${h.actor}' : ''}',
                              style: const TextStyle(fontWeight: FontWeight.w600),
                            ),
                            Text(formatTime(h.recordedAt), style: TextStyle(fontSize: 12.5, color: c.graphite2)),
                            if (h.changes.isNotEmpty)
                              Text(
                                h.changes.keys.where((k) => k != 'academicContext' && k != 'manualFieldOverrides').join(', '),
                                style: TextStyle(fontSize: 12.5, color: c.graphite2),
                              ),
                          ],
                        ),
                      ),
                    if (q.hasMore) DueButton(label: 'Load more', small: true, variant: Variant.ghost, onPressed: q.loadMore),
                  ],
                );
              },
            ),
        ],
      ),
    );
  }
}
