import 'dart:async';

import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/models.dart';
import '../core/query.dart';
import '../state/data.dart';
import '../state/services.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'subjects.dart';

/// First run: six details tell DueCare which notices and classes apply to the student.
class Onboarding extends StatelessWidget {
  const Onboarding({super.key, required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(titleSpacing: 16, title: const Logo(size: 26)),
        body: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text('Fill in your answer sheet', style: display(context, 36)),
            const SizedBox(height: 8),
            Text('Six details tell DueCare which notices and classes apply to you.',
                style: TextStyle(color: Palette.of(context).graphite2, fontSize: 15)),
            const SizedBox(height: 16),
            ProfileForm(
              key: ValueKey(profile.revision),
              profile: profile,
              onSaved: (addTimetable) {
                if (addTimetable) {
                  Navigator.push(context, MaterialPageRoute(builder: (_) => const SubjectsScreen(startImport: true)));
                }
              },
            ),
            const SizedBox(height: 16),
            const PrivacyControls(),
          ],
        ),
      );
}

/// Profile & privacy (apps/web workspace.tsx › settings view).
class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final api = AppScope.of(context).api;
    return Scaffold(
      appBar: AppBar(title: const Text('Profile & privacy')),
      body: QueryView(
        queryKey: Keys.me,
        fetch: () => api.get('/me'),
        builder: (context, q) {
          final p = profileOf(q);
          if (p == null) return Padding(padding: const EdgeInsets.all(16), child: q.error != null ? ErrorNotice(q.error, retry: q.refetch) : const Loading('Loading…'));
          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
            children: [
              const SectionHeader(title: 'Profile & privacy', subtitle: 'Your academic details, notice preferences, and what DueCare keeps.'),
              ProfileForm(key: ValueKey(p.revision), profile: p),
              const SizedBox(height: 16),
              KtPreference(profile: p),
              const SizedBox(height: 16),
              const ReminderPreference(),
              const SizedBox(height: 16),
              const PrivacyControls(),
            ],
          );
        },
      ),
    );
  }
}

const _classYears = [('FY', 'First'), ('SY', 'Second'), ('TY', 'Third'), ('LY', 'Final')];

class ProfileForm extends StatefulWidget {
  const ProfileForm({super.key, required this.profile, this.onSaved});

  final Profile profile;
  final void Function(bool addTimetable)? onSaved;

  @override
  State<ProfileForm> createState() => _ProfileFormState();
}

class _ProfileFormState extends State<ProfileForm> {
  late String branch = widget.profile.branchCode ?? '';
  late String? classYear = _classYears.map((y) => y.$1).where((y) => y == widget.profile.classYear?.toUpperCase()).firstOrNull;
  late final semester = TextEditingController(text: widget.profile.currentSemester?.toString() ?? '');
  late final division = TextEditingController(text: widget.profile.division ?? '');
  late final batch = TextEditingController(text: widget.profile.generalBatch ?? '');
  late final roll = TextEditingController(text: widget.profile.rollNumber ?? '');
  late String theme = widget.profile.theme;
  bool addTimetable = false;
  bool pending = false;
  bool saved = false;
  Object? error;
  Map<String, String> errors = {};

  @override
  void dispose() {
    for (final c in [semester, division, batch, roll]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> save() async {
    final sem = int.tryParse(semester.text.trim());
    final missing = <String, String>{
      if (branch.isEmpty) 'branchCode': 'Choose your branch',
      if (classYear == null) 'classYear': 'Choose your class / year',
      if (sem == null || sem < 1 || sem > 30) 'currentSemester': 'Enter a semester from 1 to 30',
      if (division.text.trim().isEmpty) 'division': 'Required',
      if (batch.text.trim().isEmpty) 'generalBatch': 'Required',
      if (roll.text.trim().isEmpty) 'rollNumber': 'Required',
    };
    setState(() {
      errors = missing;
      saved = false;
    });
    if (missing.isNotEmpty) return;
    final services = AppScope.of(context);
    setState(() {
      pending = true;
      error = null;
    });
    try {
      final p = await services.api.send('PATCH', '/me', body: {
        'branchCode': branch,
        'classYear': classYear,
        'currentSemester': sem,
        'division': division.text.trim(),
        'generalBatch': batch.text.trim(),
        'rollNumber': roll.text.trim(),
        'theme': theme,
        'revision': widget.profile.revision,
      });
      services.queries.peek(Keys.me)?.set(p);
      widget.onSaved?.call(addTimetable);
      saved = true;
      await services.queries.invalidate(['overview', 'tasks']);
    } on ApiError catch (e) {
      error = e;
      errors = e.fields;
    }
    if (mounted) setState(() => pending = false);
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final p = widget.profile;
    Widget text(String key, String label, TextEditingController controller, {bool number = false}) => Field(
          label: label,
          error: errors[key],
          child: TextField(controller: controller, keyboardType: number ? TextInputType.number : TextInputType.text),
        );
    return Panel(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(p.onboardingComplete ? 'Academic profile' : 'Set up your academic profile', style: display(context, 24)),
          const SizedBox(height: 6),
          Text('Your branch, class, semester, division, and batch give your work the right context.',
              style: TextStyle(color: c.graphite2)),
          const SizedBox(height: 14),
          Row(
            children: [
              Container(width: 40, height: 40, alignment: Alignment.center, color: c.inkTint, child: Text(p.initial, style: display(context, 18))),
              const SizedBox(width: 10),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(p.name ?? 'Somaiya student', style: const TextStyle(fontWeight: FontWeight.w700)),
                  Text(p.email, style: TextStyle(color: c.graphite2, fontSize: 13)),
                ]),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Field(
            label: 'Branch',
            error: errors['branchCode'],
            child: SelectField<String>(
              value: branch.isEmpty ? null : branch,
              placeholder: 'Choose your branch',
              title: 'Branch',
              options: [for (final b in p.branchOptions) (b.code, '${b.code} · ${b.name}')],
              onChanged: (v) => setState(() => branch = v),
            ),
          ),
          Field(
            label: 'Class / year',
            error: errors['classYear'],
            child: BubbleChoice<String>(
              value: classYear,
              options: [for (final (y, n) in _classYears) (y, '$y\n$n year')],
              onChanged: (v) => setState(() => classYear = v),
            ),
          ),
          text('currentSemester', 'Current semester', semester, number: true),
          text('division', 'Division', division),
          text('generalBatch', 'Batch', batch),
          text('rollNumber', 'Roll number', roll),
          Field(
            label: 'Appearance',
            child: BubbleChoice<String>(
              value: theme,
              options: const [('system', 'System'), ('light', 'Light'), ('dark', 'Dark')],
              onChanged: (v) => setState(() => theme = v),
            ),
          ),
          Text('Enter your batch once. It applies to every theory, lab, and tutorial subject. Roll numbers retain leading zeros.',
              style: TextStyle(color: c.graphite2, fontSize: 13)),
          if (!p.onboardingComplete)
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              value: addTimetable,
              onChanged: (v) => setState(() => addTimetable = v ?? false),
              title: const Text('Add your timetable for better accuracy', style: TextStyle(fontWeight: FontWeight.w700)),
              subtitle: const Text('Helps DueCare understand your subjects and class timings. Upload it after saving your '
                  'profile, or add it later from Subjects.'),
            ),
          ErrorNotice(error),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(child: Text(saved ? 'Profile saved' : '', style: TextStyle(color: c.good, fontWeight: FontWeight.w600))),
              DueButton(
                label: pending ? 'Saving…' : (addTimetable ? 'Save and add timetable' : 'Save profile'),
                onPressed: pending ? null : save,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// KT (ATKT/backlog) notices only concern students re-taking a failed subject.
class KtPreference extends StatefulWidget {
  const KtPreference({super.key, required this.profile});

  final Profile profile;

  @override
  State<KtPreference> createState() => _KtPreferenceState();
}

class _KtPreferenceState extends State<KtPreference> {
  // The choice shows at once and reverts if saving fails.
  late bool ignore = widget.profile.ignoreKtNotices;
  bool pending = false;
  bool saved = false;
  Object? error;

  Future<void> choose(bool value) async {
    final services = AppScope.of(context);
    setState(() {
      ignore = value;
      pending = true;
      error = null;
      saved = false;
    });
    try {
      // Save against the profile as it is now, so another change in between cannot fail this one-tap choice.
      final current = Profile(((await services.api.get('/me')) as Map).cast<String, dynamic>());
      final p = await services.api.send('PATCH', '/me', body: {'revision': current.revision, 'ignoreKtNotices': value});
      services.queries.peek(Keys.me)?.set(p);
      saved = true;
    } on ApiError catch (e) {
      error = e;
      ignore = widget.profile.ignoreKtNotices;
    }
    if (mounted) setState(() => pending = false);
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    Widget option(bool value, String title, String body) => InkWell(
          onTap: pending ? null : () => choose(value),
          child: Container(
            padding: const EdgeInsets.symmetric(vertical: 10),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Bubble(fill: ignore == value ? c.graphite : null, stroke: ignore == value ? c.graphite : null),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
                    Text(body, style: TextStyle(color: c.graphite2, fontSize: 13)),
                  ]),
                ),
              ],
            ),
          ),
        );
    return Panel(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('KT notices', style: display(context, 24)),
          const SizedBox(height: 6),
          Text('Emails and Classroom posts meant only for students with a KT (ATKT exams, KT forms and fees, KT results) can be skipped.',
              style: TextStyle(color: c.graphite2)),
          option(false, 'Show KT notices', 'I have a KT subject, or I want to see them.'),
          option(true, 'Ignore KT notices', 'Gmail and Classroom items only for KT students create no tasks or reviews.'),
          Text(
            'Notices for regular and KT students together are always kept, and work you already track keeps receiving updates. '
            'The choice applies to newly processed messages; after switching to Show, use Reprocess on Sources to bring back earlier KT notices.',
            style: TextStyle(color: c.graphite2, fontSize: 13),
          ),
          if (saved) Text('Saved', style: TextStyle(color: c.good, fontSize: 13, fontWeight: FontWeight.w600)),
          ErrorNotice(error),
        ],
      ),
    );
  }
}

/// Deadline reminders on this phone (a day and an hour before).
class ReminderPreference extends StatefulWidget {
  const ReminderPreference({super.key});

  @override
  State<ReminderPreference> createState() => _ReminderPreferenceState();
}

class _ReminderPreferenceState extends State<ReminderPreference> {
  bool? on;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    AppScope.of(context).reminders.enabled.then((v) {
      if (mounted) setState(() => on = v);
    });
  }

  Future<void> toggle(bool value) async {
    final services = AppScope.of(context);
    final result = await services.reminders.setEnabled(value);
    if (result) unawaited(services.reminders.refresh(services.api));
    if (mounted) setState(() => on = result);
    if (value && !result && mounted) toast(context, 'Allow notifications for DueCare in your phone’s settings to get reminders.');
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Panel(
      padding: const EdgeInsets.all(20),
      child: Row(
        children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Deadline reminders', style: display(context, 24)),
              const SizedBox(height: 6),
              Text(
                'A notification a day before and an hour before each due task, scheduled on this phone. '
                'New work gets reminders the next time you open DueCare.',
                style: TextStyle(color: c.graphite2, fontSize: 13),
              ),
            ]),
          ),
          Switch(value: on ?? false, onChanged: on == null ? null : toggle),
        ],
      ),
    );
  }
}

/// Delete imported data per source, reimport, follow privacy operations, delete the account
/// (apps/web privacy.tsx).
class PrivacyControls extends StatefulWidget {
  const PrivacyControls({super.key});

  @override
  State<PrivacyControls> createState() => _PrivacyControlsState();
}

class _PrivacyControlsState extends State<PrivacyControls> {
  bool busy = false;
  Object? error;
  String notice = '';
  Timer? _poll;

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _run(Future<void> Function() action) async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await action();
    } on ApiError catch (e) {
      error = e;
    }
    if (mounted) setState(() => busy = false);
  }

  Future<void> deleteImported(Connection c) async {
    if (!await confirm(
      context,
      title: 'Delete imported data?',
      body: 'Source-only tasks are removed. Student-created and edited work, and tasks with another source, stay. '
          'Removed imports stay deleted during future syncs.',
      action: 'Confirm deletion',
    )) {
      return;
    }
    if (!mounted) return;
    final services = AppScope.of(context);
    await _run(() async {
      await services.api.send('POST', '/privacy/source-data-deletions', body: {'connectionId': c.id, 'revision': c.revision});
      await services.queries.invalidateAll();
    });
  }

  Future<void> reimport(Connection c) async {
    final services = AppScope.of(context);
    await _run(() async {
      await services.api.send('POST', '/connections/${c.id}/reimport');
      notice = 'Reimport queued. Open Sources to follow its progress.';
      await services.queries.invalidateAll();
    });
  }

  Future<void> deleteAccount() async {
    final word = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialog) => AlertDialog(
          title: Text('Delete your DueCare account?', style: display(context, 24)),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('This cannot be undone. Processing stops immediately. Deletion continues in saved steps and can be resumed if interrupted.'),
              const SizedBox(height: 12),
              const Printed('Type DELETE to confirm'),
              const SizedBox(height: 6),
              TextField(controller: word, autocorrect: false, onChanged: (_) => setDialog(() {})),
            ],
          ),
          actions: [
            DueButton(label: 'Cancel', variant: Variant.ghost, onPressed: () => Navigator.pop(context, false)),
            DueButton(
              label: 'Permanently delete account',
              variant: Variant.destructive,
              onPressed: word.text == 'DELETE' ? () => Navigator.pop(context, true) : null,
            ),
          ],
        ),
      ),
    );
    word.dispose();
    if (ok != true || !mounted) return;
    final services = AppScope.of(context);
    await _run(() async {
      final job = (await services.api.send('POST', '/privacy/account-deletion', body: {'confirmation': 'DELETE'})) as Map;
      await services.queries.clear();
      // The app now shows only the deletion's progress, using its resume token.
      await services.session.deleting(job['resumeToken'] as String);
    });
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final api = AppScope.of(context).api;
    return QueryView(
      queryKey: Keys.connections,
      fetch: () => api.get('/connections'),
      builder: (context, cq) => QueryView(
        queryKey: const ['privacy-jobs'],
        pager: (cursor) => api.get('/privacy/jobs${cursor != null ? '?cursor=${Uri.encodeQueryComponent(cursor)}' : ''}'),
        builder: (context, jq) {
          final connections = pageOf(cq.data).items.map(Connection.new).toList();
          final jobs = pageOf(jq.data).items.map(PrivacyJob.new).toList();
          final running = jobs.any((j) => j.status != 'completed');
          // Follow a running operation until it completes.
          if (running && _poll == null) {
            final queries = AppScope.of(context).queries;
            _poll = Timer.periodic(const Duration(seconds: 2), (_) async {
              await jq.refetch();
              if (!pageOf(jq.data).items.map(PrivacyJob.new).any((j) => j.status != 'completed')) {
                _poll?.cancel();
                _poll = null;
                await queries.invalidate(syncRoots);
              }
            });
          }
          return Panel(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Privacy and your data', style: display(context, 24)),
                const SizedBox(height: 6),
                Text(
                  'Disconnect in Sources to stop syncing while keeping your work. Deleting imported data removes its evidence and reviews. '
                  'Student-created tasks, student edits, and work supported by another source are preserved.',
                  style: TextStyle(color: c.graphite2),
                ),
                ErrorNotice(cq.error ?? jq.error ?? error, retry: () => AppScope.of(context).queries.invalidate(['connections', 'privacy-jobs'])),
                if (notice.isNotEmpty) Notice(notice),
                const SizedBox(height: 8),
                if (cq.isPending)
                  const Loading('Loading sources…')
                else if (connections.isEmpty)
                  const Text('No imported sources to delete.')
                else
                  for (final conn in connections)
                    _Row(
                      title: conn.service == 'gmail' ? 'Gmail' : 'Classroom',
                      subtitle: conn.accountEmail,
                      actions: [
                        DueButton(
                          label: 'Delete imported data',
                          small: true,
                          variant: Variant.outline,
                          onPressed: busy || conn.privacyJobId != null ? null : () => deleteImported(conn),
                        ),
                        DueButton(
                          label: 'Reimport',
                          small: true,
                          variant: Variant.ghost,
                          onPressed: busy || conn.privacyJobId != null || conn.status != 'active' ? null : () => reimport(conn),
                        ),
                      ],
                    ),
                Text(
                  'Deleted imports stay deleted during future syncs. Reimport fetches the normal source history window again; '
                  'it does not restore deleted data from a backup.',
                  style: TextStyle(color: c.graphite2, fontSize: 13),
                ),
                for (final j in jobs)
                  _Row(
                    title: j.kind == 'disconnect' ? 'Disconnect' : 'Imported data deletion',
                    subtitle: '${j.status == 'completed' ? 'Complete' : 'Step: ${j.stage}'}${j.errorCode != null ? ' · Retrying automatically' : ''}'
                        '${j.status == 'completed' ? '\n${j.progress['deletedTasks'] ?? 0} tasks removed · ${j.progress['preservedTasks'] ?? 0} preserved' : ''}',
                  ),
                if (jq.hasMore) DueButton(label: 'Load more privacy operations', small: true, variant: Variant.ghost, onPressed: jq.loadMore),
                const SizedBox(height: 8),
                _Row(
                  title: 'Delete your account',
                  subtitle: 'Permanently remove your workspace, source credentials, and DueCare login. '
                      'Google mail and Classroom work remain in Google.',
                  actions: [DueButton(label: 'Delete account', small: true, variant: Variant.outline, onPressed: busy ? null : deleteAccount)],
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.title, required this.subtitle, this.actions = const []});

  final String title, subtitle;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(vertical: 12),
      decoration: BoxDecoration(border: Border(top: BorderSide(color: c.inkRule))),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(fontWeight: FontWeight.w700)),
          Text(subtitle, style: TextStyle(color: c.graphite2, fontSize: 13)),
          if (actions.isNotEmpty) ...[const SizedBox(height: 8), Wrap(spacing: 8, runSpacing: 8, children: actions)],
        ],
      ),
    );
  }
}
