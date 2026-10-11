import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/ist.dart';
import '../core/models.dart';
import '../core/query.dart';
import '../state/data.dart';
import '../state/services.dart';
import '../state/sync.dart';
import '../ui/icons.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

const _permissionLabels = {
  'https://www.googleapis.com/auth/gmail.readonly': 'Read Gmail messages',
  'https://www.googleapis.com/auth/classroom.courses.readonly':
      'See Classroom courses',
  'https://www.googleapis.com/auth/classroom.coursework.me.readonly':
      'See your coursework and submissions',
  'https://www.googleapis.com/auth/classroom.announcements.readonly':
      'See course announcements',
  'https://www.googleapis.com/auth/classroom.rosters.readonly':
      'See your teachers’ names',
};

String _jobSummary(Json? job) {
  if (job == null) return '';
  final p = (job['progress'] as Map?) ?? {};
  String? count(String key, String one, String many) {
    final n = (p[key] as num?)?.toInt() ?? 0;
    return n > 0 ? '$n ${n == 1 ? one : many}' : null;
  }

  final parts = [
    count('stored', 'imported', 'imported'),
    count('updated', 'updated', 'updated'),
    count('duplicates', 'duplicate', 'duplicates'),
    count('blocked', 'blocked', 'blocked'),
    count('ignored', 'not academic', 'not academic'),
    count('courses', 'course found', 'courses found'),
    count('tasksCreated', 'task added', 'tasks added'),
    count('tasksUpdated', 'task updated', 'tasks updated'),
    count('completed', 'completed from evidence', 'completed from evidence'),
    count('reviews', 'needs attention', 'need attention'),
  ].whereType<String>();
  return parts.isEmpty ? 'Nothing new' : parts.join(' · ');
}

/// Gmail and Classroom, read-only, with the access granted at Google sign-in
/// (apps/web connections.tsx).
class SourcesScreen extends StatefulWidget {
  const SourcesScreen({super.key});

  @override
  State<SourcesScreen> createState() => _SourcesScreenState();
}

class _SourcesScreenState extends State<SourcesScreen> {
  bool granting = false;
  Object? error;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    AppScope.of(context).sync.refresh();
  }

  /// Gmail and Classroom access is granted at Google sign-in; re-asking means signing in with consent.
  Future<void> grant() async {
    final services = AppScope.of(context);
    setState(() {
      granting = true;
      error = null;
    });
    try {
      if (await services.signIn(consent: true)) {
        await services.sync.start(trigger: 'manual');
        if (mounted) {
          toast(
            context,
            'Gmail and Classroom access updated. Syncing will start now.',
          );
        }
      }
    } on ApiError catch (e) {
      error = e;
    } catch (_) {
      error = ApiError(
        'Google could not complete the connection. Try again.',
        0,
      );
    }
    if (mounted) setState(() => granting = false);
  }

  @override
  Widget build(BuildContext context) {
    final sync = AppScope.of(context).sync;
    return ListenableBuilder(
      listenable: sync,
      builder: (context, _) {
        final c = Palette.of(context);
        final visible = sync.connections
            .where((c) => c.status != 'disconnected')
            .toList();
        final disconnected = sync.connections
            .where((c) => c.status == 'disconnected')
            .toList();
        String? status(String service) =>
            visible.where((c) => c.service == service).firstOrNull?.status;
        final allActive =
            status('gmail') == 'active' && status('classroom') == 'active';
        final namesMissing = visible.any(
          (c) =>
              c.status == 'active' && c.optionalPermissionsMissing.isNotEmpty,
        );
        return PageScaffold(
          title: 'Sources',
          subtitle: 'Read-only Gmail and Google Classroom, using the access you granted at sign-in.',
          onRefresh: sync.refresh,
          children: [
            if (sync.loaded)
              Panel(
                padding: const EdgeInsets.all(18),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      allActive
                          ? 'Gmail and Classroom are connected'
                          : 'Gmail and Classroom access is needed',
                      style: const TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      allActive
                          ? 'Granted at sign-in for ${visible.first.accountEmail}. Sync continues in the background, including when you close DueCare.'
                          : 'Allow read-only access on Google’s sign-in screen so your assignments and tests appear automatically. '
                                'Your password is never shared with DueCare.',
                      style: TextStyle(color: c.graphite2, fontSize: 14),
                    ),
                    const SizedBox(height: 10),
                    for (final (service, label, icon) in [
                      ('gmail', 'Gmail', DueIcons.mail),
                      ('classroom', 'Google Classroom', DueIcons.classroom),
                    ])
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 4),
                        child: Row(
                          children: [
                            glyph(icon, size: 16, color: c.ink),
                            const SizedBox(width: 8),
                            Expanded(child: Text(label)),
                            Text(
                              switch (status(service)) {
                                'active' => 'Connected',
                                'needs_reauth' => 'Reconnect needed',
                                _ => 'Not connected',
                              },
                              style: const TextStyle(
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ],
                        ),
                      ),
                    if (!allActive) ...[
                      const SizedBox(height: 10),
                      DueButton(
                        label: 'Allow Gmail and Classroom access',
                        onPressed: granting ? null : grant,
                      ),
                    ],
                    if (allActive && namesMissing) ...[
                      const SizedBox(height: 10),
                      const Text(
                        'Show which teacher posted Classroom work.',
                        style: TextStyle(fontWeight: FontWeight.w700),
                      ),
                      Text(
                        'Sign in again and allow DueCare to see your teachers’ names. Everything else keeps working without it.',
                        style: TextStyle(color: c.graphite2, fontSize: 13),
                      ),
                      const SizedBox(height: 8),
                      DueButton(
                        label: 'Allow teacher names',
                        variant: Variant.outline,
                        onPressed: granting ? null : grant,
                      ),
                    ],
                  ],
                ),
              ),
            ErrorNotice(error),
            ErrorNotice(sync.error, retry: sync.refresh),
            const SizedBox(height: 14),
            if (!sync.loaded)
              const Loading('Loading connections…')
            else if (visible.isEmpty)
              Text(
                'Manual tasks keep working without Gmail or Classroom.',
                style: TextStyle(color: c.graphite2),
              )
            else
              for (final conn in visible)
                Padding(
                  padding: const EdgeInsets.only(bottom: 14),
                  child: _ConnectionCard(c: conn, sync: sync, onConnect: grant),
                ),
            if (disconnected.isNotEmpty)
              ExpansionTile(
                tilePadding: EdgeInsets.zero,
                shape: const Border(),
                title: Text(
                  '${disconnected.length} disconnected source${disconnected.length == 1 ? '' : 's'}',
                ),
                children: [
                  for (final conn in disconnected)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 14),
                      child: _ConnectionCard(
                        c: conn,
                        sync: sync,
                        onConnect: grant,
                      ),
                    ),
                ],
              ),
            const SizedBox(height: 8),
            const FacultyApproval(manage: true),
            const SizedBox(height: 14),
            const _SenderPreferences(),
          ],
        );
      },
    );
  }
}

class _ConnectionCard extends StatefulWidget {
  const _ConnectionCard({
    required this.c,
    required this.sync,
    required this.onConnect,
  });

  final Connection c;
  final SyncController sync;
  final VoidCallback onConnect;

  @override
  State<_ConnectionCard> createState() => _ConnectionCardState();
}

class _ConnectionCardState extends State<_ConnectionCard> {
  bool pending = false;
  Object? error;

  Future<void> _run(Future<void> Function() action) async {
    setState(() {
      pending = true;
      error = null;
    });
    try {
      await action();
    } on ApiError catch (e) {
      error = e;
    }
    if (mounted) setState(() => pending = false);
  }

  Future<void> disconnect() async {
    final conn = widget.c;
    if (!await confirm(
      context,
      title: 'Disconnect ${conn.label}?',
      body:
          'DueCare stops syncing this service. Your tasks and imported records are kept. '
          'Google access is revoked when no other DueCare service uses ${conn.accountEmail}.',
      action: 'Disconnect',
      cancel: 'Keep connected',
    )) {
      return;
    }
    if (!mounted) return;
    final services = AppScope.of(context);
    await _run(() async {
      await services.api.send(
        'DELETE',
        '/connections/${conn.id}?revision=${conn.revision}',
      );
      await services.queries.invalidate(['overview']);
      await widget.sync.refresh();
    });
  }

  Widget _status(BuildContext context) {
    final p = Palette.of(context);
    final conn = widget.c;
    final job = conn.activeJob;
    final driving = widget.sync.driving.contains(conn.id);
    if (conn.status == 'needs_reauth') {
      return Notice(
        conn.lastError?['message'] as String? ??
            'Reconnect this account to keep syncing.',
        warn: true,
      );
    }
    if (conn.status == 'disconnected') {
      return const Text(
        'Disconnected. Imported records and your tasks were kept.',
      );
    }
    if (job?['status'] == 'waiting_retry') {
      return Notice(
        '${job?['error']?['message'] ?? 'Google is temporarily unavailable.'} Retrying at ${formatTime(job?['nextRetryAt'] as String?)}.',
        warn: true,
      );
    }
    if (job != null) {
      return Row(
        children: [
          SizedBox(
            width: 14,
            height: 14,
            child: CircularProgressIndicator(strokeWidth: 2, color: p.ink),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              '${driving || job['leased'] == true ? (job['phase'] == 'interpreting' ? 'Adding tasks' : 'Syncing and adding tasks') : 'Waiting to continue'}'
              ' · ${_jobSummary(job)}',
            ),
          ),
        ],
      );
    }
    final last = conn.lastJob;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${conn.lastSuccessAt != null ? 'Last synced ${formatTime(conn.lastSuccessAt)}' : 'Not synced yet'}'
          '${last?['status'] == 'completed' ? ' · ${_jobSummary(last)}' : ''}',
        ),
        if (conn.lastError != null && last?['status'] == 'failed')
          Text(
            '${conn.lastError!['message']}',
            style: TextStyle(color: p.dueText),
          ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = Palette.of(context);
    final conn = widget.c;
    final driving = widget.sync.driving.contains(conn.id);
    final r = conn.records;
    int n(String k) => (r[k] as num?)?.toInt() ?? 0;
    final waiting = n('awaitingInterpretation') - n('aiPaused');
    final recordLine = [
      if (n('interpreted') > 0) '${n('interpreted')} interpreted',
      if (n('needsReview') > 0) '${n('needsReview')} need your attention',
      if (waiting > 0) '$waiting waiting to be interpreted',
      if (n('aiPaused') > 0)
        '${n('aiPaused')} waiting for AI interpretation (retries automatically in the background)',
      if (n('ignored') > 0) '${n('ignored')} not academic or not for you',
      if (n('blocked') > 0) '${n('blocked')} from blocked senders',
    ].join(' · ');
    return Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              glyph(
                conn.service == 'gmail'
                    ? DueIcons.mail
                    : DueIcons.classroom,
                color: p.ink,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      conn.label,
                      style: const TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    Text(
                      conn.accountEmail,
                      style: TextStyle(color: p.graphite2, fontSize: 13),
                    ),
                  ],
                ),
              ),
              Tag(switch (conn.status) {
                'needs_reauth' => 'Reconnect needed',
                'active' => 'Connected',
                _ => 'Disconnected',
              }),
            ],
          ),
          const SizedBox(height: 10),
          _status(context),
          if (conn.privacyJobId != null)
            const Notice(
              'A privacy operation is in progress. Open Profile & privacy to follow it.',
            ),
          ErrorNotice(widget.sync.failures[conn.id] ?? error),
          if (conn.status != 'disconnected') ...[
            const SizedBox(height: 8),
            for (final perm in conn.permissions)
              Text(
                '• ${_permissionLabels[perm] ?? perm}',
                style: const TextStyle(fontSize: 13),
              ),
            const SizedBox(height: 6),
            Text(
              recordLine.isEmpty ? 'Nothing imported yet.' : recordLine,
              style: TextStyle(color: p.graphite2, fontSize: 12.5),
            ),
          ],
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              if (conn.status == 'active')
                DueButton(
                  label: 'Sync now',
                  icon: DueIcons.sources,
                  small: true,
                  onPressed:
                      conn.privacyJobId != null ||
                          driving ||
                          conn.activeJob?['leased'] == true
                      ? null
                      : () => widget.sync.syncNow(conn.id),
                ),
              if (conn.status != 'active')
                DueButton(
                  label: 'Reconnect',
                  small: true,
                  onPressed: conn.privacyJobId != null
                      ? null
                      : widget.onConnect,
                ),
              if (conn.status == 'active')
                DueButton(
                  label: 'Reprocess',
                  icon: DueIcons.reopen,
                  small: true,
                  variant: Variant.outline,
                  onPressed: conn.privacyJobId != null || driving || pending
                      ? null
                      : () => _run(() => widget.sync.reprocess(conn.id)),
                ),
              if (conn.status != 'disconnected')
                DueButton(
                  label: 'Disconnect',
                  icon: Icons.link_off,
                  small: true,
                  variant: Variant.ghost,
                  onPressed: conn.privacyJobId != null || pending
                      ? null
                      : disconnect,
                ),
            ],
          ),
          if (conn.service == 'classroom' && conn.status == 'active')
            _CourseLinks(connection: conn),
        ],
      ),
    );
  }
}

/// Link Classroom courses to subjects; only linked courses are imported.
class _CourseLinks extends StatefulWidget {
  const _CourseLinks({required this.connection});

  final Connection connection;

  @override
  State<_CourseLinks> createState() => _CourseLinksState();
}

class _CourseLinksState extends State<_CourseLinks> {
  final Map<String, String> choice = {};
  bool pending = false;
  Object? error;

  Future<void> change(
    String subjectId,
    String courseId, {
    bool remove = false,
  }) async {
    final services = AppScope.of(context);
    setState(() {
      pending = true;
      error = null;
    });
    try {
      await services.api.send(
        remove ? 'DELETE' : 'PUT',
        '/subjects/$subjectId/classroom-mappings/${widget.connection.id}/${Uri.encodeComponent(courseId)}',
      );
      await services.queries.invalidate(['classroom-courses', 'subjects']);
    } on ApiError catch (e) {
      error = e;
    }
    if (mounted) setState(() => pending = false);
  }

  @override
  Widget build(BuildContext context) {
    final p = Palette.of(context);
    final api = AppScope.of(context).api;
    return Padding(
      padding: const EdgeInsets.only(top: 16),
      child: QueryView(
        queryKey: Keys.subjects,
        fetch: () => loadSubjects(api),
        builder: (context, sq) => QueryView(
          queryKey: ['classroom-courses', widget.connection.id],
          fetch: () => api.get(
            '/connections/${widget.connection.id}/classroom-courses?limit=100',
          ),
          builder: (context, q) {
            final subjects = subjectsOf(sq);
            final courses = pageOf(q.data).items;
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Link Classroom courses to your subjects',
                  style: TextStyle(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 4),
                Text(
                  'Courses link to your subjects automatically on each sync, by name or short form and with AI when needed (marked “auto”). '
                  'Change or add links here; a course you unlink stays unlinked. Only linked courses are imported, and courses are never added as subjects.',
                  style: TextStyle(color: p.graphite2, fontSize: 12.5),
                ),
                ErrorNotice(q.error ?? error, retry: q.refetch),
                if (q.isPending)
                  const Loading('Loading courses…')
                else if (courses.isEmpty)
                  Text(
                    'Sync this connection to discover your courses.',
                    style: TextStyle(color: p.graphite2),
                  )
                else
                  for (final course in courses)
                    _course(context, course, subjects),
              ],
            );
          },
        ),
      ),
    );
  }

  Widget _course(BuildContext context, Json course, List<Subject> subjects) {
    final p = Palette.of(context);
    final id = course['externalCourseId'] as String;
    final mappings = ((course['mappings'] as List?) ?? []).cast<Map>();
    final linked = mappings.map((m) => m['subjectId']).toSet();
    final options = subjects.where((s) => !linked.contains(s.id)).toList();
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(vertical: 10),
      decoration: BoxDecoration(
        border: Border(top: BorderSide(color: p.inkRule)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${course['name']}',
            style: const TextStyle(fontWeight: FontWeight.w600),
          ),
          Text(
            '${course['section'] ?? 'No section'}${course['available'] == false ? ' · No longer available from Google' : ''}',
            style: TextStyle(color: p.graphite2, fontSize: 12.5),
          ),
          const SizedBox(height: 6),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final m in mappings)
                Container(
                  padding: const EdgeInsets.only(left: 8),
                  decoration: BoxDecoration(
                    color: p.inkWash,
                    border: Border.all(color: p.inkRule),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        '${m['subjectName']} · ${m['subjectKind']}${m['automatic'] == true ? ' · auto' : ''}',
                        style: const TextStyle(fontSize: 13),
                      ),
                      IconButton(
                        tooltip:
                            'Unlink ${m['subjectName']} from ${course['name']}',
                        visualDensity: VisualDensity.compact,
                        icon: const Icon(Icons.close, size: 14),
                        onPressed: pending
                            ? null
                            : () =>
                                  change('${m['subjectId']}', id, remove: true),
                      ),
                    ],
                  ),
                ),
            ],
          ),
          if (options.isNotEmpty) ...[
            const SizedBox(height: 6),
            Row(
              children: [
                Expanded(
                  child: SelectField<String>(
                    value: choice[id],
                    placeholder: 'Choose a subject',
                    title: 'Subject for ${course['name']}',
                    options: [for (final s in options) (s.id, s.label)],
                    onChanged: (v) => setState(() => choice[id] = v),
                  ),
                ),
                const SizedBox(width: 8),
                DueButton(
                  label: 'Link',
                  icon: DueIcons.link,
                  small: true,
                  variant: Variant.outline,
                  onPressed: choice[id] == null || pending
                      ? null
                      : () => change(choice[id]!, id),
                ),
              ],
            ),
          ],
          if (subjects.isEmpty)
            Text(
              'Add subjects first to link this course.',
              style: TextStyle(color: p.graphite2, fontSize: 12.5),
            ),
        ],
      ),
    );
  }
}

/// Approve faculty senders, inline for given emails or as the full managed list.
class FacultyApproval extends StatefulWidget {
  const FacultyApproval({
    super.key,
    this.emails = const [],
    this.manage = false,
  });

  final List<String> emails;
  final bool manage;

  @override
  State<FacultyApproval> createState() => _FacultyApprovalState();
}

class _FacultyApprovalState extends State<FacultyApproval> {
  bool pending = false;
  Object? error;

  Future<void> change(String email, {required bool remove}) async {
    final services = AppScope.of(context);
    setState(() {
      pending = true;
      error = null;
    });
    try {
      await services.api.send(
        remove ? 'DELETE' : 'PUT',
        '/approved-faculty/${Uri.encodeComponent(email)}',
      );
      await services.queries.invalidate([
        'approved-faculty',
        'review-items',
        'tasks',
        'task',
        'overview',
        'connections',
        'me',
      ]);
    } on ApiError catch (e) {
      error = e;
    }
    if (mounted) setState(() => pending = false);
  }

  @override
  Widget build(BuildContext context) {
    final p = Palette.of(context);
    final api = AppScope.of(context).api;
    if (!widget.manage && widget.emails.isEmpty) return const SizedBox.shrink();
    return QueryView(
      queryKey: const ['approved-faculty'],
      staleTime: const Duration(seconds: 30),
      fetch: () => api.get('/approved-faculty'),
      builder: (context, q) {
        final approved = pageOf(q.data).items
            .map((i) => i['email'] as String)
            .toSet();
        final visible = widget.manage
            ? approved.toList()
            : widget.emails.toSet().toList();
        final rows = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            ErrorNotice(q.error ?? error, retry: q.refetch),
            if (widget.manage && q.isPending)
              const Loading('Loading approved faculty…'),
            if (widget.manage && q.data != null && visible.isEmpty)
              Text(
                'No faculty approved yet. Approve a sender from Needs attention or a task.',
                style: TextStyle(color: p.graphite2, fontSize: 13),
              ),
            for (final email in visible)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Wrap(
                  spacing: 8,
                  runSpacing: 4,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(
                      email,
                      style: TextStyle(color: p.graphite2, fontSize: 13),
                    ),
                    if (approved.contains(email)) ...[
                      Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.check, size: 14, color: p.good),
                          const Text(
                            ' Approved faculty',
                            style: TextStyle(fontSize: 13),
                          ),
                        ],
                      ),
                      DueButton(
                        label: 'Remove approval',
                        small: true,
                        variant: Variant.ghost,
                        onPressed: pending
                            ? null
                            : () => change(email, remove: true),
                      ),
                    ] else
                      DueButton(
                        label: 'Approve faculty',
                        icon: DueIcons.done,
                        small: true,
                        variant: Variant.outline,
                        onPressed: pending || q.data == null
                            ? null
                            : () => change(email, remove: false),
                      ),
                  ],
                ),
              ),
          ],
        );
        if (!widget.manage) {
          return Padding(padding: const EdgeInsets.only(top: 8), child: rows);
        }
        return Panel(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Approved faculty', style: display(context, 22)),
              const SizedBox(height: 6),
              Text(
                'Accepted academic mail remembers the exact faculty address. Missing class or division details from approved faculty will not '
                'need confirmation. Other class, batch, and nonacademic mail checks still apply.',
                style: TextStyle(color: p.graphite2, fontSize: 13),
              ),
              rows,
            ],
          ),
        );
      },
    );
  }
}

class _SenderPreferences extends StatefulWidget {
  const _SenderPreferences();

  @override
  State<_SenderPreferences> createState() => _SenderPreferencesState();
}

class _SenderPreferencesState extends State<_SenderPreferences> {
  final email = TextEditingController();
  String action = 'include';
  bool pending = false;
  Object? error;

  @override
  void dispose() {
    email.dispose();
    super.dispose();
  }

  Future<void> _run(Future<dynamic> Function(Api api) call) async {
    final services = AppScope.of(context);
    setState(() {
      pending = true;
      error = null;
    });
    try {
      await call(services.api);
      await services.queries.invalidate(['sender-preferences', 'connections']);
    } on ApiError catch (e) {
      error = e;
    }
    if (mounted) setState(() => pending = false);
  }

  Future<void> save(String address, String act, {int? revision}) =>
      _run((api) async {
        await api.send(
          'PUT',
          '/sender-preferences/${Uri.encodeComponent(address.trim())}',
          body: {'action': act, 'revision': revision},
        );
        if (revision == null) email.clear();
      });

  @override
  Widget build(BuildContext context) {
    final p = Palette.of(context);
    final api = AppScope.of(context).api;
    return Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Sender preferences', style: display(context, 22)),
          const SizedBox(height: 6),
          Text(
            'Match exact sender addresses. Including a sender makes their mail eligible for academic checks. A complete block stops all processing '
            'of that sender, including submission receipts, and takes precedence over every include and rule.',
            style: TextStyle(color: p.graphite2, fontSize: 13),
          ),
          const SizedBox(height: 12),
          Field(
            label: 'Sender email',
            child: TextField(
              controller: email,
              keyboardType: TextInputType.emailAddress,
              autocorrect: false,
              decoration: const InputDecoration(
                hintText: 'faculty@somaiya.edu',
              ),
            ),
          ),
          Field(
            label: 'Preference',
            child: BubbleChoice<String>(
              value: action,
              options: const [
                ('include', 'Include sender'),
                ('block', 'Block completely'),
              ],
              onChanged: (v) => setState(() => action = v),
            ),
          ),
          DueButton(
            label: 'Save sender',
            onPressed: pending
                ? null
                : () => email.text.trim().isEmpty
                      ? null
                      : save(email.text, action),
          ),
          ErrorNotice(error),
          QueryView(
            queryKey: const ['sender-preferences'],
            fetch: () => api.get('/sender-preferences?limit=100'),
            builder: (context, q) {
              final items = pageOf(q.data).items;
              if (q.isPending) {
                return const Loading('Loading sender preferences…');
              }
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  ErrorNotice(q.error, retry: q.refetch),
                  if (items.isEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 10),
                      child: Text(
                        'No sender preferences yet. College and faculty addresses are already considered.',
                        style: TextStyle(color: p.graphite2),
                      ),
                    ),
                  for (final pref in items)
                    Container(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      decoration: BoxDecoration(
                        border: Border(top: BorderSide(color: p.inkRule)),
                      ),
                      child: Row(
                        children: [
                          glyph(
                            pref['action'] == 'block'
                                ? Icons.block
                                : DueIcons.profile,
                            size: 16,
                            color: pref['action'] == 'block'
                                ? p.bad
                                : p.graphite,
                          ),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              '${pref['email']}',
                              style: const TextStyle(fontSize: 13),
                            ),
                          ),
                          Tag(
                            pref['action'] == 'block' ? 'Blocked' : 'Included',
                          ),
                          PopupMenuButton<String>(
                            tooltip: 'Change ${pref['email']}',
                            onSelected: (v) => v == 'remove'
                                ? _run(
                                    (api) => api.send(
                                      'DELETE',
                                      '/sender-preferences/${Uri.encodeComponent('${pref['email']}')}?revision=${pref['revision']}',
                                    ),
                                  )
                                : save(
                                    '${pref['email']}',
                                    pref['action'] == 'block'
                                        ? 'include'
                                        : 'block',
                                    revision: pref['revision'] as int,
                                  ),
                            itemBuilder: (_) => [
                              PopupMenuItem(
                                value: 'toggle',
                                child: Text(
                                  pref['action'] == 'block'
                                      ? 'Include instead'
                                      : 'Block',
                                ),
                              ),
                              const PopupMenuItem(
                                value: 'remove',
                                child: Text('Remove'),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                ],
              );
            },
          ),
          const SizedBox(height: 10),
          Text(
            'Blocking applies inside DueCare only; it does not change Gmail. Unblocking affects future mail. Use “Reprocess” on a source to reconsider '
            'earlier items with your current senders, profile, subjects, and rules.',
            style: TextStyle(color: p.graphite2, fontSize: 12.5),
          ),
        ],
      ),
    );
  }
}
