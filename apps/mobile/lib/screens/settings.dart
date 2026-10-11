import 'dart:async';

import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/models.dart';
import '../core/query.dart';
import '../state/data.dart';
import '../state/services.dart';
import '../ui/icons.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'subjects.dart';

/// First run: six details tell DueCare which notices and classes apply to the student.
class Onboarding extends StatelessWidget {
  const Onboarding({super.key, required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context) => PageScaffold(
        title: 'Welcome',
        subtitle: 'Six details tell DueCare which notices and classes apply to you.',
        leading: const Padding(padding: EdgeInsets.only(left: 16), child: Logo(size: 26, wordmark: false)),
        children: [
          ProfileForm(
            key: ValueKey(profile.revision),
            profile: profile,
            onSaved: (addTimetable) {
              if (addTimetable) {
                Navigator.push(context, MaterialPageRoute(builder: (_) => const SubjectsScreen(startImport: true)));
              }
            },
          ),
          const SizedBox(height: 8),
          Notice('You can delete your imported data or your whole account at any time from More → Privacy & data.', icon: DueIcons.privacy),
        ],
      );
}

/// Academic details, appearance and KT notices.
class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final api = AppScope.of(context).api;
    return QueryView(
      queryKey: Keys.me,
      fetch: () => api.get('/me'),
      builder: (context, q) {
        final p = profileOf(q);
        return PageScaffold(
          title: 'Profile',
          onRefresh: q.refetch,
          children: [
            if (p == null) q.error != null ? ErrorNotice(q.error, retry: q.refetch) : const Loading('Loading…'),
            if (p != null) ...[
              ProfileForm(key: ValueKey(p.revision), profile: p),
              KtPreference(profile: p),
            ],
          ],
        );
      },
    );
  }
}

class PrivacyScreen extends StatelessWidget {
  const PrivacyScreen({super.key});

  @override
  Widget build(BuildContext context) => const PageScaffold(
        title: 'Privacy & data',
        subtitle: 'What DueCare keeps, and how to remove it.',
        children: [PrivacyControls()],
      );
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
      if (classYear == null) 'classYear': 'Choose your year',
      if (sem == null || sem < 1 || sem > 30) 'currentSemester': 'Enter a semester from 1 to 30',
      if (division.text.trim().isEmpty) 'division': 'Required',
      if (batch.text.trim().isEmpty) 'generalBatch': 'Required',
      if (roll.text.trim().isEmpty) 'rollNumber': 'Required',
    };
    setState(() => errors = missing);
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
      if (mounted && widget.profile.onboardingComplete) toast(context, 'Profile saved');
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
    Widget text(String key, String label, TextEditingController controller, {bool number = false, String? hint}) => Field(
          label: label,
          error: errors[key],
          child: TextField(
            controller: controller,
            keyboardType: number ? TextInputType.number : TextInputType.text,
            textCapitalization: TextCapitalization.characters,
            decoration: InputDecoration(hintText: hint),
          ),
        );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Panel(
          child: Row(children: [
            Avatar(p.initial, size: 52),
            const SizedBox(width: 14),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(p.name ?? 'Somaiya student', style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 17)),
                Text(p.email, style: TextStyle(color: c.graphite2, fontSize: 13.5)),
              ]),
            ),
          ]),
        ),
        const SectionLabel('Academic details'),
        Panel(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Field(
                label: 'Branch',
                error: errors['branchCode'],
                child: SelectField<String>(
                  value: branch.isEmpty ? null : branch,
                  placeholder: 'Choose your branch',
                  title: 'Branch',
                  icon: DueIcons.subjects,
                  options: [for (final b in p.branchOptions) (b.code, '${b.code} · ${b.name}')],
                  onChanged: (v) => setState(() => branch = v),
                ),
              ),
              Field(
                label: 'Year',
                error: errors['classYear'],
                child: BubbleChoice<String>(
                  value: classYear,
                  options: [for (final (y, _) in _classYears) (y, y)],
                  onChanged: (v) => setState(() => classYear = v),
                ),
              ),
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(child: text('currentSemester', 'Semester', semester, number: true, hint: '3')),
                const SizedBox(width: 12),
                Expanded(child: text('division', 'Division', division, hint: 'A')),
              ]),
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(child: text('generalBatch', 'Batch', batch, hint: 'A1')),
                const SizedBox(width: 12),
                Expanded(child: text('rollNumber', 'Roll number', roll, hint: '001')),
              ]),
              Text('Your batch applies to every theory, lab and tutorial subject.', style: TextStyle(color: c.graphite2, fontSize: 13)),
            ],
          ),
        ),
        const SectionLabel('Appearance'),
        BubbleChoice<String>(
          value: theme,
          options: const [('system', 'System'), ('light', 'Light'), ('dark', 'Dark')],
          onChanged: (v) => setState(() => theme = v),
        ),
        if (!p.onboardingComplete) ...[
          const SizedBox(height: 12),
          Panel(
            padding: EdgeInsets.zero,
            child: CheckboxListTile(
              value: addTimetable,
              onChanged: (v) => setState(() => addTimetable = v ?? false),
              title: const Text('Add my timetable next'),
              subtitle: const Text('Classes appear beside your deadlines. You can also add it later from Subjects.'),
            ),
          ),
        ],
        ErrorNotice(error),
        const SizedBox(height: 16),
        DueButton(
          label: pending ? 'Saving…' : (p.onboardingComplete ? 'Save profile' : (addTimetable ? 'Continue to timetable' : 'Get started')),
          expand: true,
          onPressed: pending ? null : save,
        ),
      ],
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
  Object? error;

  Future<void> choose(bool value) async {
    final services = AppScope.of(context);
    setState(() {
      ignore = value;
      pending = true;
      error = null;
    });
    try {
      // Save against the profile as it is now, so another change in between cannot fail this one-tap choice.
      final current = Profile(((await services.api.get('/me')) as Map).cast<String, dynamic>());
      final p = await services.api.send('PATCH', '/me', body: {'revision': current.revision, 'ignoreKtNotices': value});
      services.queries.peek(Keys.me)?.set(p);
    } on ApiError catch (e) {
      error = e;
      ignore = widget.profile.ignoreKtNotices;
    }
    if (mounted) setState(() => pending = false);
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    Widget option(bool value, String title, String body) => ListTile(
          onTap: pending ? null : () => choose(value),
          leading: Bubble(fill: ignore == value ? c.graphite : null, stroke: ignore == value ? c.graphite : null),
          title: Text(title),
          subtitle: Text(body),
        );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        GroupCard(
          label: 'KT notices',
          footer: 'Notices for regular and KT students together are always kept. After switching to Show, use Reprocess in Sources to bring back '
              'earlier KT notices.',
          children: [
            option(false, 'Show KT notices', 'I have a KT subject, or want to see them'),
            option(true, 'Ignore KT notices', 'Items only for KT students create no tasks'),
          ],
        ),
        ErrorNotice(error),
      ],
    );
  }
}

/// Delete imported data per source, reimport, follow privacy operations, delete the account.
class PrivacyControls extends StatefulWidget {
  const PrivacyControls({super.key});

  @override
  State<PrivacyControls> createState() => _PrivacyControlsState();
}

class _PrivacyControlsState extends State<PrivacyControls> {
  bool busy = false;
  Object? error;
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

  Future<void> _source(Connection c) async {
    final choice = await pick<String>(
      context,
      title: '${c.service == 'gmail' ? 'Gmail' : 'Classroom'} · ${c.accountEmail}',
      options: [
        ('delete', 'Delete imported data'),
        if (c.status == 'active') ('reimport', 'Reimport the normal history window'),
      ],
    );
    if (choice == null || !mounted) return;
    final services = AppScope.of(context);
    if (choice.$1 == 'delete') {
      if (!await confirm(
        context,
        title: 'Delete imported data?',
        body: 'Tasks that only came from this source are removed. Your own tasks, your edits and work with another source stay. '
            'Removed imports stay deleted during future syncs.',
        action: 'Delete',
      )) {
        return;
      }
      await _run(() async {
        await services.api.send('POST', '/privacy/source-data-deletions', body: {'connectionId': c.id, 'revision': c.revision});
        await services.queries.invalidateAll();
      });
    } else {
      await _run(() async {
        await services.api.send('POST', '/connections/${c.id}/reimport');
        await services.queries.invalidateAll();
        if (mounted) toast(context, 'Reimport queued. Follow it in Sources.');
      });
    }
  }

  Future<void> deleteAccount() async {
    final word = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialog) => AlertDialog(
          title: Text('Delete your account?', style: display(context, 22)),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('This cannot be undone. Your workspace, source access and DueCare login are removed.'),
              const SizedBox(height: 14),
              TextField(
                controller: word,
                autocorrect: false,
                decoration: const InputDecoration(hintText: 'Type DELETE to confirm'),
                onChanged: (_) => setDialog(() {}),
              ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
            DueButton(label: 'Delete account', variant: Variant.destructive, onPressed: word.text == 'DELETE' ? () => Navigator.pop(context, true) : null),
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
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ErrorNotice(cq.error ?? jq.error ?? error, retry: () => AppScope.of(context).queries.invalidate(['connections', 'privacy-jobs'])),
              GroupCard(
                label: 'Imported data',
                footer: 'Disconnect a source in Sources to stop syncing but keep your work. Deleting imported data removes its evidence and '
                    'reviews; deleted imports stay deleted.',
                children: [
                  if (cq.isPending) const Loading('Loading sources…'),
                  if (!cq.isPending && connections.isEmpty) const SettingTile(icon: DueIcons.review, title: 'No imported sources'),
                  for (final conn in connections)
                    SettingTile(
                      icon: conn.service == 'gmail' ? DueIcons.mail : DueIcons.classroom,
                      title: conn.service == 'gmail' ? 'Gmail' : 'Classroom',
                      subtitle: conn.privacyJobId != null ? 'Privacy operation in progress' : conn.accountEmail,
                      onTap: busy || conn.privacyJobId != null ? null : () => _source(conn),
                    ),
                ],
              ),
              if (jobs.isNotEmpty)
                GroupCard(
                  label: 'Privacy operations',
                  children: [
                    for (final j in jobs)
                      SettingTile(
                        icon: j.status == 'completed' ? DueIcons.done : DueIcons.clock,
                        title: j.kind == 'disconnect' ? 'Disconnect' : 'Imported data deletion',
                        subtitle: j.status == 'completed'
                            ? 'Done · ${j.progress['deletedTasks'] ?? 0} tasks removed, ${j.progress['preservedTasks'] ?? 0} kept'
                            : 'In progress: ${j.stage}${j.errorCode != null ? ' · retrying automatically' : ''}',
                      ),
                    if (jq.hasMore) ListTile(title: const Text('Show more'), onTap: jq.loadMore),
                  ],
                ),
              GroupCard(
                label: 'Account',
                children: [
                  SettingTile(
                    icon: DueIcons.erase,
                    title: 'Delete my account',
                    subtitle: 'Removes your workspace, source access and login. Your Google data stays in Google.',
                    danger: true,
                    onTap: busy ? null : deleteAccount,
                  ),
                ],
              ),
            ],
          );
        },
      ),
    );
  }
}
