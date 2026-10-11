import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
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
  'manual': 'Marked done by you',
  'lms_assignment_receipt': 'LMS submission confirmation',
  'classroom_turned_in': 'Classroom shows turned in',
  'student_confirmed_evidence': 'Confirmed by you from submission evidence',
};
const _sourceNames = {'manual': 'Added by you', 'gmail': 'Gmail', 'classroom': 'Google Classroom'};
const _timeLabels = {
  'submissionOpensAt': ('Submission opens', Icons.lock_open_outlined),
  'availabilityOpensAt': ('Quiz window opens', Icons.lock_open_outlined),
  'availabilityClosesAt': ('Quiz window closes', Icons.lock_clock_outlined),
  'loginByAt': ('Log in by', Icons.login_rounded),
  'reportingAt': ('Report at', Icons.how_to_reg_outlined),
  'startsAt': ('Test starts', Icons.play_circle_outline),
  'endsAt': ('Test ends', Icons.stop_circle_outlined),
};
const _detailLabels = {
  'assessmentLabel': ('Assessment', Icons.assignment_outlined),
  'deliverableLabel': ('Deliverable', Icons.inventory_2_outlined),
  'location': ('Location', Icons.place_outlined),
  'estimatedEffortMinutes': ('Estimated effort (minutes)', Icons.timer_outlined),
  'durationMinutes': ('Duration (minutes)', Icons.hourglass_bottom_rounded),
  'syllabus': ('Syllabus', Icons.menu_book_outlined),
  'permittedTools': ('Permitted tools', Icons.handyman_outlined),
  'preparationInstructions': ('Preparation', Icons.lightbulb_outline),
};

/// Everything about one task: when it is due, where it came from, and its history.
class TaskDetailScreen extends StatefulWidget {
  const TaskDetailScreen({super.key, required this.id});

  final String id;

  @override
  State<TaskDetailScreen> createState() => _TaskDetailScreenState();
}

class _TaskDetailScreenState extends State<TaskDetailScreen> {
  bool pending = false;
  Object? error;

  Future<void> _toggle(Task t) async {
    final services = AppScope.of(context);
    setState(() {
      pending = true;
      error = null;
    });
    try {
      await services.api.send('PATCH', '/tasks/${t.id}', body: {'revision': t.revision, 'status': t.status == 'completed' ? 'due' : 'completed'});
      HapticFeedback.mediumImpact();
      await services.queries.invalidate(taskRoots);
    } on ApiError catch (e) {
      error = e;
    }
    if (mounted) setState(() => pending = false);
  }

  Future<void> _delete(Task t) async {
    if (!await confirm(context, title: 'Delete this task?', body: 'The task and its history are deleted.', action: 'Delete', cancel: 'Keep')) {
      return;
    }
    if (!mounted) return;
    final services = AppScope.of(context);
    try {
      await services.api.send('DELETE', '/tasks/${t.id}?revision=${t.revision}');
      await services.queries.invalidate(taskRoots);
      if (mounted) Navigator.pop(context);
    } on ApiError catch (e) {
      if (mounted) setState(() => error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final api = AppScope.of(context).api;
    return QueryView(
      queryKey: Keys.task(widget.id),
      fetch: () => api.get('/tasks/${widget.id}'),
      builder: (context, q) {
        final t = q.data is Map ? Task((q.data as Map).cast<String, dynamic>()) : null;
        final done = t?.status == 'completed';
        return Scaffold(
          appBar: AppBar(
            actions: t == null
                ? null
                : [
                    IconButton(tooltip: 'Edit', icon: const Icon(Icons.edit_outlined), onPressed: () => openEditor(context, t)),
                    PopupMenuButton<String>(
                      tooltip: 'More',
                      onSelected: (v) => v == 'delete' ? _delete(t) : null,
                      itemBuilder: (_) => [
                        PopupMenuItem(
                          value: 'delete',
                          child: Row(children: [Icon(Icons.delete_outline, color: c.bad), const SizedBox(width: 12), const Text('Delete task')]),
                        ),
                      ],
                    ),
                  ],
          ),
          bottomNavigationBar: t == null
              ? null
              : Container(
                  decoration: BoxDecoration(color: c.paper, border: Border(top: BorderSide(color: c.inkRule))),
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
                  child: SafeArea(
                    top: false,
                    child: FilledButton.icon(
                      style: FilledButton.styleFrom(
                        minimumSize: const Size.fromHeight(54),
                        backgroundColor: done ? c.inkTint : c.good,
                        foregroundColor: done ? c.graphite : c.onGood,
                      ),
                      onPressed: pending ? null : () => _toggle(t),
                      icon: Icon(done ? Icons.replay_rounded : Icons.check_rounded),
                      label: Text(done ? 'Reopen task' : 'Mark as done'),
                    ),
                  ),
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

class _Body extends StatelessWidget {
  const _Body({required this.task, required this.error});

  final Task task;
  final Object? error;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final t = task;
    final d = deadline(t);
    final due = parseTime(t.dueAt);
    final left = due?.difference(DateTime.now());
    final link = t.subjectLink;
    final subjectNote = link != null && link['method'] != 'none'
        ? 'Linked automatically${link['method'] == 'ai' ? ' by AI' : ''} from the course name'
        : link?['method'] == 'none' && t.subjectName == null
            ? (link?['reason'] == 'ai_unavailable' ? 'Couldn’t be linked automatically right now' : 'None of your subjects matched')
            : null;
    final times = [
      for (final e in _timeLabels.entries)
        if (t[e.key] is String)
          SettingTile(
            icon: e.value.$2,
            title: formatTime(t[e.key] as String),
            subtitle: [
              e.value.$1,
              if (!const ['source-exact', 'student-entered', 'student-date-only', null].contains(t.basisOf(e.key))) t.basisOf(e.key)!.replaceFirst('-', ' '),
            ].join(' · '),
          ),
    ];
    final details = [
      for (final e in _detailLabels.entries)
        if (t[e.key] != null && '${t[e.key]}'.isNotEmpty) SettingTile(icon: e.value.$2, title: '${t[e.key]}', subtitle: e.value.$1),
    ];
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 32),
      children: [
        Text(t.title, style: display(context, 28)),
        if (t.sourceTitle != null && t.sourceTitle != t.title)
          Padding(padding: const EdgeInsets.only(top: 6), child: Text('Originally “${t.sourceTitle}”', style: TextStyle(color: c.graphite2))),
        const SizedBox(height: 12),
        Wrap(spacing: 8, runSpacing: 8, children: [
          StatusPill(t.status),
          Tag(t.isTest ? 'Test' : 'Assignment', icon: t.isTest ? Icons.quiz_outlined : Icons.assignment_outlined),
          Tag('${t.priority} priority', icon: Icons.flag_outlined),
        ]),
        if (t.hiddenByRule != null)
          Notice('Hidden from your lists by the rule “${t.hiddenByRule!['name'] ?? 'a rule'}”. Turn it off in More → Rules to show it again.', warn: true),
        const SizedBox(height: 16),
        // When it is due, front and centre.
        Container(
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(color: t.status == 'missed' ? c.badTint : c.sheet, borderRadius: BorderRadius.circular(Radii.card)),
          child: Row(children: [
            Container(
              width: 48,
              height: 48,
              decoration: BoxDecoration(color: statusColors(context, t.status).bg, borderRadius: BorderRadius.circular(14)),
              child: Icon(t.dueAt == null ? Icons.event_busy_outlined : Icons.event_rounded, color: statusColors(context, t.status).fg),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(d.main, style: display(context, 19)),
                if (d.note != null) Text(d.note!, style: TextStyle(color: c.graphite2, fontSize: 13)),
                if (left != null && t.status == 'due' && !left.isNegative)
                  Text('in ${countdown(left)}', style: TextStyle(color: c.ink, fontWeight: FontWeight.w700, fontSize: 13.5)),
                if (t.timingTentative?['question'] != null)
                  Text('${t.timingTentative!['question']}', style: TextStyle(color: c.graphite2, fontSize: 12.5)),
              ]),
            ),
          ]),
        ),
        GroupCard(
          label: 'Details',
          children: [
            SettingTile(
              icon: Icons.class_outlined,
              title: '${t.subjectName ?? 'No subject'}${t.subjectKind != null ? ' · ${t.subjectKind}' : ''}',
              subtitle: subjectNote ?? 'Subject',
            ),
            SettingTile(
              icon: t.completedAt != null ? Icons.task_alt_rounded : Icons.radio_button_unchecked,
              title: t.completedAt != null ? (_origins[t.completionOrigin ?? 'manual'] ?? 'Completed') : 'Not done yet',
              subtitle: [
                if (t.completedAt != null) formatTime(t.completedAt),
                if (classroomNote(t) != null) 'Classroom: ${classroomNote(t)}',
              ].join(' · ').ifEmpty,
            ),
            SettingTile(
              icon: Icons.source_outlined,
              title: (t.sources.isEmpty ? ['manual'] : t.sources).map((s) => _sourceNames[s] ?? s).join(', '),
              subtitle: 'Source',
            ),
            if (t.generalBatch != null) SettingTile(icon: Icons.groups_outlined, title: 'Batch ${t.generalBatch}', subtitle: 'Applies to your batch'),
            if (t.dateWindowStart != null)
              SettingTile(
                icon: Icons.date_range_outlined,
                title: formatRange(t.dateWindowStart!, t.dateWindowEnd ?? t.dateWindowStart!),
                subtitle: dueWindow(t) != null ? 'Date window · exact day not announced' : 'Date window',
              ),
            ...details,
          ],
        ),
        if (times.isNotEmpty) GroupCard(label: 'Timing (IST)', children: times),
        if (t.instructions.isNotEmpty) _TextCard('Instructions', t.instructions),
        if (t.notes.isNotEmpty) _TextCard('Your notes', t.notes),
        _Sources(taskId: t.id),
        _History(taskId: t.id),
        ErrorNotice(error),
      ],
    );
  }
}

extension on String {
  String? get ifEmpty => isEmpty ? null : this;
}

class _TextCard extends StatelessWidget {
  const _TextCard(this.title, this.text);

  final String title, text;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionLabel(title),
          SizedBox(width: double.infinity, child: Panel(child: SelectableText(text, style: const TextStyle(fontSize: 15, height: 1.5)))),
        ],
      );
}

const _kindNames = {
  'gmail_message': ('Email', Icons.mail_outline),
  'classroom_announcement': ('Classroom post', Icons.campaign_outlined),
  'classroom_coursework': ('Classroom assignment', Icons.school_outlined),
  'classroom_submission': ('Classroom turn-in', Icons.upload_file_outlined),
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
        return GroupCard(
          label: sources.length == 1 ? 'Source' : 'Sources',
          children: [
            for (final e in sources)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 14, 8, 8),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon((_kindNames[e.sourceKind] ?? ('Source', Icons.source_outlined)).$2, color: c.ink, size: 22),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '${(_kindNames[e.sourceKind] ?? ('Source', Icons.source_outlined)).$1}'
                            '${e.sourceKind == 'gmail_message' ? ((e.senderName ?? e.sender) != null ? ' from ${e.senderName ?? e.sender}' : '') : '${e.postedBy != null ? ' by ${e.postedBy}' : ''}${e.courseName != null ? ' in ${e.courseName}' : ''}'}',
                            style: const TextStyle(fontWeight: FontWeight.w700),
                          ),
                          if (e.postedAt != null) Text('Posted ${formatTime(e.postedAt)}', style: TextStyle(fontSize: 12.5, color: c.graphite2)),
                          if (e.sourceTitle != null || e.excerpt != null)
                            Padding(
                              padding: const EdgeInsets.only(top: 4),
                              child: Text(e.sourceTitle ?? '“${e.excerpt}”', style: TextStyle(color: c.graphite2, fontSize: 13.5)),
                            ),
                          if (e.openUrl != null)
                            TextButton.icon(
                              style: TextButton.styleFrom(padding: EdgeInsets.zero),
                              onPressed: () => launchUrl(Uri.parse(e.openUrl!), mode: LaunchMode.externalApplication),
                              icon: const Icon(Icons.open_in_new_rounded, size: 17),
                              label: Text(e.sourceKind == 'gmail_message' ? 'Open in Gmail' : 'Open in Classroom'),
                            ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
          ],
        );
      },
    );
  }
}

const _actions = {
  'created': 'Created',
  'edited': 'Edited',
  'completed': 'Marked done',
  'reopened': 'Reopened',
  'subject_removed': 'Subject removed',
  'source_update': 'Updated from the source',
  'evidence_added': 'Evidence added',
};

/// Every recorded change, newest first.
class _History extends StatelessWidget {
  const _History({required this.taskId});

  final String taskId;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final api = AppScope.of(context).api;
    return Padding(
      padding: const EdgeInsets.only(top: 16),
      child: Container(
        decoration: BoxDecoration(color: c.sheet, borderRadius: BorderRadius.circular(Radii.card)),
        clipBehavior: Clip.antiAlias,
        child: ExpansionTile(
          leading: Icon(Icons.history_rounded, color: c.ink),
          title: const Text('Change history', style: TextStyle(fontWeight: FontWeight.w700)),
          childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
          children: [
            QueryView(
              queryKey: ['history', taskId],
              pager: (cursor) => api.get('/tasks/$taskId/history${cursor != null ? '?cursor=${Uri.encodeQueryComponent(cursor)}' : ''}'),
              builder: (context, q) {
                if (q.isPending) return const Loading('Loading history…');
                final items = pageOf(q.data).items.map(HistoryItem.new).toList();
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    ErrorNotice(q.error, retry: q.refetch),
                    for (final h in items)
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 8),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Padding(
                              padding: const EdgeInsets.only(top: 6),
                              child: Container(width: 8, height: 8, decoration: BoxDecoration(color: c.ink, shape: BoxShape.circle)),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    '${_actions[h.action] ?? h.action.replaceAll('_', ' ')}${h.actor != 'student' ? ' · by ${h.actor}' : ''}',
                                    style: const TextStyle(fontWeight: FontWeight.w600),
                                  ),
                                  Text(formatTime(h.recordedAt), style: TextStyle(fontSize: 12.5, color: c.graphite2)),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                    if (q.hasMore) TextButton(onPressed: q.loadMore, child: const Text('Show older')),
                  ],
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}
