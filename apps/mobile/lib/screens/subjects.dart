import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/ist.dart';
import '../core/models.dart';
import '../core/query.dart';
import '../state/data.dart';
import '../state/services.dart';
import '../ui/icons.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'timetable_import.dart';

/// Subjects and their weekly timetables (apps/web subjects.tsx).
class SubjectsScreen extends StatefulWidget {
  const SubjectsScreen({super.key, this.startImport = false});

  /// Open the timetable upload straight away (chosen during onboarding).
  final bool startImport;

  @override
  State<SubjectsScreen> createState() => _SubjectsScreenState();
}

class _SubjectsScreenState extends State<SubjectsScreen> {
  @override
  void initState() {
    super.initState();
    if (widget.startImport) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _import());
    }
  }

  void _import() => Navigator.push(
    context,
    MaterialPageRoute(
      fullscreenDialog: true,
      builder: (_) => const TimetableImportScreen(),
    ),
  );

  void _edit([Subject? s]) => Navigator.push(
    context,
    MaterialPageRoute(
      fullscreenDialog: true,
      builder: (_) => SubjectEditor(subject: s),
    ),
  );

  Future<void> _delete(Subject s) async {
    if (!await confirm(
      context,
      title: 'Delete subject?',
      body:
          '${s.name}\n\nIts timetable will be removed. Your tasks and history will remain, with the subject unlinked.',
      action: 'Delete subject',
    )) {
      return;
    }
    if (!mounted) return;
    final services = AppScope.of(context);
    try {
      await services.api.send(
        'DELETE',
        '/subjects/${s.id}?revision=${s.revision}',
      );
      await services.queries.invalidate([
        'subjects',
        'tasks',
        'overview',
        'timetable',
      ]);
    } on ApiError catch (e) {
      if (mounted) toast(context, e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final api = AppScope.of(context).api;
    return QueryView(
      queryKey: Keys.me,
      fetch: () => api.get('/me'),
      builder: (context, mq) => QueryView(
        queryKey: Keys.subjects,
        fetch: () => loadSubjects(api),
        builder: (context, q) {
          final subjects = subjectsOf(q);
          return PageScaffold(
            title: 'Subjects',
            subtitle:
                'Batch ${profileOf(mq)?.generalBatch ?? 'not set'} applies to every subject.',
            onRefresh: q.refetch,
            floatingActionButton: FloatingActionButton.extended(
              heroTag: 'add-subject',
              onPressed: _edit,
              icon: const DueIcon(DueIcons.add),
              label: const Text('Add subject'),
            ),
            actions: [
              IconButton(
                tooltip: 'Upload timetable',
                icon: const DueIcon(DueIcons.upload),
                onPressed: _import,
              ),
            ],
            bottomPadding: 110,
            children: [
              if (subjects.isEmpty || q.isPending)
                ...[]
              else
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: DueButton(
                    label: 'Upload your timetable',
                    icon: DueIcons.upload,
                    variant: Variant.tonal,
                    expand: true,
                    onPressed: _import,
                  ),
                ),
              ErrorNotice(q.error, retry: q.refetch),
              if (q.isPending)
                const Loading('Loading subjects…')
              else if (subjects.isEmpty)
                const EmptyState(
                  icon: DueIcons.month,
                  title: 'A place for every subject',
                  body: 'Upload your timetable to create all your subjects in one go and fill in their weekly slots, or add subjects yourself.',
                )
              else
                for (final s in subjects)
                  Panel(
                    margin: const EdgeInsets.only(bottom: 12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Printed(s.kind),
                        const SizedBox(height: 2),
                        Text(
                          s.name,
                          style: const TextStyle(
                            fontSize: 17,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        if (s.code != null || s.term != null)
                          Text(
                            [s.code, s.term].whereType<String>().join(' · '),
                            style: TextStyle(color: c.graphite2, fontSize: 13),
                          ),
                        if (s.aliases.isNotEmpty)
                          Text(
                            'Also known as ${s.aliases.join(', ')}',
                            style: const TextStyle(fontSize: 13),
                          ),
                        for (final m in s.classroomMappings)
                          Text(
                            'Linked to Classroom: ${m['courseName'] ?? m['externalCourseId']}${m['sourceAvailable'] == false ? ' (no longer available)' : ''}',
                            style: TextStyle(
                              color: c.graphite2,
                              fontSize: 12.5,
                            ),
                          ),
                        const SizedBox(height: 10),
                        Row(
                          children: [
                            DueButton(
                              label: 'Timetable',
                              icon: DueIcons.event,
                              small: true,
                              variant: Variant.outline,
                              onPressed: () => Navigator.push(
                                context,
                                MaterialPageRoute(
                                  fullscreenDialog: true,
                                  builder: (_) => TimetableEditor(subject: s),
                                ),
                              ),
                            ),
                            const Spacer(),
                            IconButton(
                              tooltip: 'Edit ${s.name}',
                              icon: const DueIcon(DueIcons.edit, size: 20),
                              onPressed: () => _edit(s),
                            ),
                            IconButton(
                              tooltip: 'Delete ${s.name}',
                              icon: const DueIcon(DueIcons.erase, size: 20),
                              onPressed: () => _delete(s),
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
    );
  }
}

class SubjectEditor extends StatefulWidget {
  const SubjectEditor({super.key, this.subject});

  final Subject? subject;

  @override
  State<SubjectEditor> createState() => _SubjectEditorState();
}

class _SubjectEditorState extends State<SubjectEditor> {
  late final name = TextEditingController(text: widget.subject?.name ?? '');
  late String kind = widget.subject?.kind ?? 'theory';
  String? nameError;
  bool pending = false;
  Object? error;

  @override
  void dispose() {
    name.dispose();
    super.dispose();
  }

  Future<void> save() async {
    if (name.text.trim().isEmpty) {
      setState(() => nameError = 'Add a name');
      return;
    }
    final s = widget.subject;
    final services = AppScope.of(context);
    setState(() {
      pending = true;
      error = null;
      nameError = null;
    });
    try {
      await services.api.send(
        s != null ? 'PATCH' : 'POST',
        s != null ? '/subjects/${s.id}' : '/subjects',
        body: {
          'name': name.text.trim(),
          'kind': kind,
          // Retain existing source-matching metadata when editing the simpler form.
          if (s != null) ...{
            'code': s.code,
            'aliases': s.aliases,
            'term': s.term,
            'classCode': s.classCode,
            'revision': s.revision,
          },
        },
      );
      await services.queries.invalidate(['subjects', 'tasks']);
      if (mounted) Navigator.pop(context);
    } on ApiError catch (e) {
      error = e;
    }
    if (mounted) setState(() => pending = false);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: Text(widget.subject != null ? 'Edit subject' : 'Add a subject'),
    ),
    body: ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(
          'Theory, lab, and tutorial subjects stay separate. Your profile batch applies to all of them.',
          style: TextStyle(color: Palette.of(context).graphite2),
        ),
        const SizedBox(height: 16),
        Field(
          label: 'Subject name',
          error: nameError,
          child: TextField(controller: name, autofocus: widget.subject == null),
        ),
        Field(
          label: 'Subject kind',
          child: BubbleChoice<String>(
            value: kind,
            options: const [
              ('theory', 'Theory'),
              ('lab', 'Lab'),
              ('tutorial', 'Tutorial'),
            ],
            onChanged: (v) => setState(() => kind = v),
          ),
        ),
        ErrorNotice(error),
        const SizedBox(height: 8),
        DueButton(
          label: pending ? 'Saving…' : 'Save subject',
          onPressed: pending ? null : save,
        ),
      ],
    ),
  );
}

/// Optional weekly class slots in IST. Saving does not create attendance tasks.
class TimetableEditor extends StatefulWidget {
  const TimetableEditor({super.key, required this.subject});

  final Subject subject;

  @override
  State<TimetableEditor> createState() => _TimetableEditorState();
}

class _TimetableEditorState extends State<TimetableEditor> {
  List<Json>? draft;
  bool pending = false;
  Object? error;

  Future<void> save(int revision, List<Json> slots) async {
    final services = AppScope.of(context);
    setState(() {
      pending = true;
      error = null;
    });
    try {
      await services.api.send(
        'PUT',
        '/subjects/${widget.subject.id}/timetable',
        body: {
          'revision': revision,
          'slots': [
            for (final s in slots)
              {
                'id': s['id'],
                'weekday': s['weekday'],
                'startTime': s['startTime'],
                'endTime': s['endTime'],
                'location': (s['location'] as String?)?.trim().isEmpty ?? true
                    ? null
                    : (s['location'] as String).trim(),
                'instructor': s['instructor'],
                'validFrom': s['validFrom'],
                'validUntil': s['validUntil'],
              },
          ],
        },
      );
      await services.queries.invalidate(['subjects', 'timetable']);
      if (mounted) Navigator.pop(context);
    } on ApiError catch (e) {
      error = e;
    }
    if (mounted) setState(() => pending = false);
  }

  @override
  Widget build(BuildContext context) {
    final api = AppScope.of(context).api;
    return QueryView(
      queryKey: Keys.timetable(widget.subject.id),
      fetch: () => api.get('/subjects/${widget.subject.id}/timetable'),
      builder: (context, q) {
        final data = q.data is Map
            ? (q.data as Map).cast<String, dynamic>()
            : null;
        final slots =
            draft ??
            [
              for (final s in (data?['slots'] as List? ?? []).cast<Map>())
                s.cast<String, dynamic>(),
            ];
        void change(int i, String key, Object? value) => setState(() {
          draft = [
            for (final (n, s) in slots.indexed) n == i ? {...s, key: value} : s,
          ];
        });
        return Scaffold(
          appBar: AppBar(title: Text('${widget.subject.name} timetable')),
          bottomNavigationBar: Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Palette.of(context).sheet,
              border: Border(
                top: BorderSide(color: Palette.of(context).graphite),
              ),
            ),
            child: SafeArea(
              top: false,
              child: DueButton(
                label: pending ? 'Saving…' : 'Save timetable',
                expand: true,
                onPressed: pending || data == null
                    ? null
                    : () => save(data['revision'] as int, slots),
              ),
            ),
          ),
          body: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text(
                'Optional weekly context in IST. Saving does not create attendance tasks.',
                style: TextStyle(color: Palette.of(context).graphite2),
              ),
              const SizedBox(height: 12),
              ErrorNotice(q.error, retry: q.refetch),
              if (q.isPending) const Loading('Loading weekly slots…'),
              if (data != null && slots.isEmpty)
                const Text(
                  'No weekly slots yet. Add your regular class or lab hours.',
                ),
              for (final (i, s) in slots.indexed)
                Panel(
                  key: ValueKey(s['id'] ?? s['_key']),
                  margin: const EdgeInsets.only(bottom: 12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Printed('Weekly slot ${i + 1}'),
                      const SizedBox(height: 10),
                      Field(
                        label: 'Day',
                        child: SelectField<int>(
                          value: (s['weekday'] as num?)?.toInt() ?? 1,
                          title: 'Day',
                          options: [
                            for (final (n, d) in weekdayNames.indexed)
                              (n + 1, d),
                          ],
                          onChanged: (v) => change(i, 'weekday', v),
                        ),
                      ),
                      Row(
                        children: [
                          Expanded(
                            child: Field(
                              label: 'Starts (IST)',
                              child: TimeField(
                                value: hhmm('${s['startTime'] ?? ''}'),
                                placeholder: 'Set time',
                                onChanged: (v) => change(i, 'startTime', v),
                              ),
                            ),
                          ),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Field(
                              label: 'Ends (IST)',
                              child: TimeField(
                                value: hhmm('${s['endTime'] ?? ''}'),
                                placeholder: 'Set time',
                                onChanged: (v) => change(i, 'endTime', v),
                              ),
                            ),
                          ),
                        ],
                      ),
                      Field(
                        label: 'Room / location',
                        child: TextFormField(
                          initialValue: s['location'] as String? ?? '',
                          onChanged: (v) => change(i, 'location', v),
                        ),
                      ),
                      DueButton(
                        label: 'Remove slot',
                        icon: DueIcons.erase,
                        small: true,
                        variant: Variant.ghost,
                        onPressed: () => setState(
                          () => draft = [
                            for (final (n, x) in slots.indexed)
                              if (n != i) x,
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              if (data != null)
                DueButton(
                  label: 'Add weekly slot',
                  icon: DueIcons.add,
                  variant: Variant.outline,
                  onPressed: () => setState(
                    () => draft = [
                      ...slots,
                      {
                        '_key': uuid4(),
                        'weekday': 1,
                        'startTime': '',
                        'endTime': '',
                      },
                    ],
                  ),
                ),
              ErrorNotice(error),
            ],
          ),
        );
      },
    );
  }
}
