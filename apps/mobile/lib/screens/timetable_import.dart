import 'dart:convert';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/ist.dart';
import '../core/models.dart';
import '../core/query.dart';
import '../core/timetable_draft.dart';
import '../state/data.dart';
import '../state/services.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

const _mb = 1024 * 1024;
const _types = {'pdf': 'application/pdf', 'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'webp': 'image/webp'};

typedef _File = ({String name, Uint8List bytes, String contentType});

String _slotTime(String value) {
  if (value.isEmpty) return 'Set time';
  final h = int.parse(value.substring(0, 2)), m = value.substring(3, 5);
  return '${h % 12 == 0 ? 12 : h % 12}:$m ${h >= 12 ? 'pm' : 'am'}';
}

/// Upload the department timetable PDF or scheduler screenshots, review the draft, and save
/// the confirmed weekly slots (apps/web timetable-import.tsx). Nothing is saved before
/// confirmation, except subjects the student creates along the way.
class TimetableImportScreen extends StatefulWidget {
  const TimetableImportScreen({super.key});

  @override
  State<TimetableImportScreen> createState() => _TimetableImportScreenState();
}

class _TimetableImportScreenState extends State<TimetableImportScreen> {
  List<_File> files = [];
  String? fileError;
  Json? reading;
  Json? draft;
  List<Json> rows = [];
  Map<String, String> choices = {};
  Map<String, bool> taken = {};
  String mode = 'add';
  Json? summary;
  bool ackOverlaps = false, ackRemovals = false;
  ({int slots, int subjects})? saved;
  String stage = 'choose'; // choose, reading, organizing, review, summary, done
  bool busy = false;
  bool original = false;
  Object? error;
  String status = '';
  String? confirmKey;
  String? confirmPayload;
  int added = 0;

  Services get services => AppScope.of(context);

  Future<void> _run(Future<void> Function() action) async {
    if (busy) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await action();
    } on ApiError catch (e) {
      error = e;
      if (e.status == 409) await services.queries.invalidate(['subjects', 'me']);
    }
    if (mounted) setState(() => busy = false);
  }

  Future<void> pick() async {
    final picked = await FilePicker.pickFiles(type: FileType.custom, allowedExtensions: _types.keys.toList());
    if (picked.isEmpty) return;
    final next = <_File>[
      ...files,
      for (final f in picked)
        (name: f.name, bytes: await f.readAsBytes(), contentType: _types[(f.extension ?? '').replaceFirst('.', '').toLowerCase()] ?? ''),
    ];
    var total = 0;
    for (final f in next) {
      total += f.bytes.length;
    }
    final pdfs = next.where((f) => f.contentType == 'application/pdf').length;
    final pictures = next.where((f) => f.contentType.startsWith('image/')).length;
    String? problem;
    if (pdfs + pictures != next.length) {
      problem = 'Choose the timetable PDF or scheduler screenshots (PNG, JPEG or WebP)';
    } else if (pdfs > 0 && next.length > 1) {
      problem = 'Upload the timetable PDF, or scheduler screenshots, not both';
    } else if (pictures > 4) {
      problem = 'Upload at most four scheduler screenshots';
    } else if (next.any((f) => f.bytes.length > 10 * _mb)) {
      problem = 'Each file must be 10 MB or smaller';
    } else if (total > 20 * _mb) {
      problem = 'Uploads are limited to 20 MB in total';
    }
    setState(() {
      fileError = problem;
      if (problem == null) files = next;
    });
  }

  /// Files go to private temporary storage (avoiding the host's request size limit), are read
  /// on the server, and are deleted afterwards. Without upload storage they are sent directly.
  Future<Json> _extract() async {
    final api = services.api;
    final List uploads;
    try {
      uploads = ((await api.send('POST', '/timetable-imports/uploads', body: {
        'files': [
          for (final f in files) {'filename': f.name.length > 120 ? f.name.substring(0, 120) : f.name, 'contentType': f.contentType, 'size': f.bytes.length},
        ],
      })) as Map)['uploads'] as List;
    } on ApiError catch (e) {
      if (e.code != 'UPLOAD_UNAVAILABLE') rethrow;
      return ((await api.multipart('/timetable-imports/extract', [
        for (final f in files) (name: f.name, bytes: f.bytes, contentType: f.contentType),
      ])) as Map).cast<String, dynamic>();
    }
    final uploaded = {
      'files': [
        for (final (i, u) in uploads.cast<Map>().indexed)
          {'path': u['path'], 'filename': files[i].name.length > 120 ? files[i].name.substring(0, 120) : files[i].name},
      ],
    };
    try {
      for (final (i, u) in uploads.cast<Map>().indexed) {
        await api.putBytes(u['url'] as String, files[i].bytes, files[i].contentType);
      }
      return ((await api.send('POST', '/timetable-imports/extract-uploaded', body: uploaded, timeout: const Duration(seconds: 140))) as Map)
          .cast<String, dynamic>();
    } finally {
      // Also clean up partial uploads; the scheduled cleaner covers the rest.
      try {
        await api.send('DELETE', '/timetable-imports/uploads', body: uploaded);
      } catch (_) {}
    }
  }

  Future<void> _interpret({bool refresh = false}) async {
    final r = reading!;
    final pages = (r['pages'] as List).cast<Map>();
    final d = ((await services.api.send('POST', '/timetable-imports/interpret', timeout: const Duration(seconds: 75), body: {
      'pages': [for (final p in pages) {'id': p['id'], 'layout': p['layout'], 'header': p['header']}],
      'cells': [
        for (final p in pages)
          for (final c in (p['cells'] as List).cast<Map>())
            {
              'id': c['id'],
              'page': c['page'],
              'weekday': c['weekday'],
              'start': c['start'],
              'end': c['end'],
              'lines': c['lines'],
              'bbox': c['bbox'],
              'spansDays': c['spansDays'] ?? false,
              'narrow': c['narrow'] ?? false,
              'clippedTop': c['clippedTop'] == true,
              'clippedBottom': c['clippedBottom'] == true,
              'unsure': c['unsure'] == true,
            },
      ],
    })) as Map).cast<String, dynamic>();
    final fresh = [for (final row in (d['rows'] as List).cast<Map>()) row.cast<String, dynamic>()];
    if (refresh) {
      // Keep the student's links and time edits across a refresh of batch decisions.
      final previous = {for (final r in rows.where((r) => r['cellId'] != null)) r['cellId']: r};
      rows = [
        for (final r in fresh)
          if (previous[r['cellId']] case final before?)
            {
              ...r,
              'weekday': before['weekday'],
              'startTime': before['startTime'],
              'endTime': before['endTime'],
              'location': before['location'],
              'subjectId': before['subjectId'] ?? r['subjectId'],
              'link': before['subjectId'] != null ? before['link'] : r['link'],
              if (before['exclusionReason'] == 'Excluded by you') ...{'include': false, 'exclusionReason': before['exclusionReason']},
            }
          else
            r,
        ...rows.where((r) => r['cellId'] == null),
      ];
    } else {
      rows = fresh;
    }
    draft = d;
    choices = {};
    taken = {for (final f in (d['families'] as List? ?? []).cast<Map>()) f['key'] as String: f['selected'] == true};
    summary = null;
    status = refresh ? 'Batch decisions refreshed. Review the included classes before saving.' : '';
    stage = 'review';
  }

  Future<void> read() => _run(() async {
        setState(() => stage = 'reading');
        try {
          reading = await _extract();
          setState(() => stage = 'organizing');
          await _interpret();
        } catch (_) {
          if (mounted) setState(() => stage = draft == null ? 'choose' : 'review');
          rethrow;
        }
      });

  void update(Set<String> ids, Json patch) => setState(() {
        rows = [for (final r in rows) ids.contains(r['id']) ? {...r, ...patch} : r];
        summary = null;
      });

  Json _payload(bool dryRun, List<RowView> views, Map<String, Subject> byId) {
    final slots = [
      for (final v in views.where((v) => v.included))
        {
          'subjectId': v.row['subjectId'],
          'weekday': v.row['weekday'],
          'startTime': v.row['startTime'],
          'endTime': v.row['endTime'],
          'location': (v.row['location'] as String?)?.trim().isEmpty ?? true ? null : (v.row['location'] as String).trim(),
          'instructor': null,
        },
    ];
    final ids = {for (final s in slots) s['subjectId'] as String};
    return {
      'mode': mode,
      'dryRun': dryRun,
      'method': reading?['method'] ?? 'pdf_text',
      'profileRevision': draft?['profileRevision'],
      'profileContext': draft?['profileContext'],
      'subjects': [for (final id in ids) {'id': id, 'revision': byId[id]?.revision}],
      'slots': slots,
      'acknowledgeOverlaps': dryRun ? false : ackOverlaps,
    };
  }

  Future<void> preview(List<RowView> views, Map<String, Subject> byId) => _run(() async {
        final r = (await services.api.send('POST', '/timetable-imports/confirm', body: _payload(true, views, byId))) as Map;
        summary = (r['summary'] as Map).cast<String, dynamic>();
        ackOverlaps = ackRemovals = false;
        stage = 'summary';
      });

  Future<void> save(List<RowView> views, Map<String, Subject> byId) => _run(() async {
        final body = _payload(false, views, byId);
        // Retrying the same reviewed payload reuses its key; any edit starts a new confirmation.
        final text = jsonEncode(body);
        if (confirmPayload != text) {
          confirmPayload = text;
          confirmKey = uuid4();
        }
        try {
          final r = (await services.api.send('POST', '/timetable-imports/confirm', body: body, idempotencyKey: confirmKey)) as Map;
          final s = r['summary'] as Map;
          saved = (slots: (s['added'] as List).length + (s['updated'] as List).length, subjects: (r['subjects'] as List).length);
          stage = 'done';
          await services.queries.invalidate(['subjects', 'timetable']);
        } on ApiError catch (e) {
          if (e.status == 409) summary = null;
          if (e.status == 409) stage = 'review';
          rethrow;
        }
      });

  /// Create every unlinked, recognized course as a subject (reusing suggestions) and link it.
  Future<void> instant(List<Course> unlinked, Map<String, Subject> byId, List<Subject> subjects) => _run(() async {
        final targets = unlinked.where((c) => c.label.trim().isNotEmpty).toList();
        final missing = targets.where((c) => c.suggestion == null || !byId.containsKey(c.suggestion)).toList();
        var created = 0;
        final links = {for (final c in targets) c.key: c.suggestion};
        if (missing.isNotEmpty) {
          final result = (await services.api.send('POST', '/subjects/bulk', body: {
            'subjects': [
              for (final c in missing)
                {'name': c.label.trim(), 'kind': importSubjectKind(c.slots.first.row, subjects), 'code': c.code, 'aliases': <String>[]},
            ],
          })) as Map;
          created = (result['created'] as num).toInt();
          final items = (result['items'] as List).cast<Map>();
          for (final (i, c) in missing.indexed) {
            links[c.key] = items[i]['id'] as String;
          }
          await services.queries.fetch(Keys.subjects, () => loadSubjects(services.api));
        }
        rows = [
          for (final r in rows)
            if (links[courseKey(r)] case final id? when r['subjectId'] == null) {...r, 'subjectId': id, 'link': 'manual'} else r,
        ];
        summary = null;
        status = '$created ${created == 1 ? 'subject' : 'subjects'} created. All recognized courses are linked.';
      });

  Future<bool> _leave() async {
    if (busy) return false;
    if (draft == null || saved != null) return true;
    return confirm(
      context,
      title: 'Discard this draft?',
      body: 'Weekly slot edits will be lost. Any subjects you created will stay in your subject list.',
      action: 'Discard draft',
      cancel: 'Keep reviewing',
    );
  }

  @override
  Widget build(BuildContext context) {
    final api = services.api;
    return PopScope(
      canPop: draft == null || saved != null,
      onPopInvokedWithResult: (popped, _) async {
        if (popped) return;
        if (await _leave() && context.mounted) Navigator.of(context).pop();
      },
      child: QueryView(
        queryKey: Keys.subjects,
        fetch: () => loadSubjects(api),
        builder: (context, sq) {
          final subjects = subjectsOf(sq)..sort((a, b) => a.name.compareTo(b.name) != 0 ? a.name.compareTo(b.name) : a.kind.compareTo(b.kind));
          final byId = {for (final s in subjects) s.id: s};
          final views = [
            for (final r in rows)
              () {
                final v = viewOf(r, choices, taken);
                // A subject deleted during review must be linked again.
                if (r['subjectId'] != null && !byId.containsKey(r['subjectId']) && v.included) {
                  return RowView(r, included: true, problems: [...v.problems, 'Choose a subject'], notes: v.notes);
                }
                return v;
              }(),
          ];
          return Scaffold(
            appBar: AppBar(
              title: const Text('Upload timetable'),
              leading: IconButton(
                icon: const Icon(Icons.close),
                tooltip: 'Close',
                onPressed: () async {
                  if (await _leave() && context.mounted) Navigator.of(context).pop();
                },
              ),
            ),
            bottomNavigationBar: _footer(views, byId),
            body: switch (stage) {
              'choose' => _choose(),
              'reading' || 'organizing' => _progress(),
              'done' => _done(),
              'summary' => _summaryView(views, byId),
              _ => _review(views, byId, subjects),
            },
          );
        },
      ),
    );
  }

  Widget? _footer(List<RowView> views, Map<String, Subject> byId) {
    final c = Palette.of(context);
    final List<Widget> buttons;
    switch (stage) {
      case 'choose':
        buttons = [Expanded(child: DueButton(label: 'Read timetable', expand: true, onPressed: busy || files.isEmpty ? null : read))];
      case 'review':
        final courses = coursesOf(views.where((v) => v.included).toList());
        final attention = courses.where((c) => c.needsReview).length;
        final blocked = views.any((v) => v.included && v.problems.isNotEmpty);
        buttons = [
          DueButton(
            label: 'Start over',
            icon: Icons.replay,
            variant: Variant.ghost,
            onPressed: busy ? null : () => _run(() => _interpret()),
          ),
          Expanded(
            child: DueButton(
              label: attention > 0 ? '$attention ${attention == 1 ? 'course needs' : 'courses need'} review' : 'Review save',
              expand: true,
              onPressed: busy || blocked || !views.any((v) => v.included) ? null : () => preview(views, byId),
            ),
          ),
        ];
      case 'summary':
        final s = summary!;
        final nothing = (s['added'] as List).length + (s['updated'] as List).length + (s['removed'] as List).length == 0;
        buttons = [
          DueButton(label: 'Back to draft', variant: Variant.outline, onPressed: busy ? null : () => setState(() => stage = 'review')),
          Expanded(
            child: DueButton(
              label: 'Confirm timetable',
              expand: true,
              onPressed: busy ||
                      nothing ||
                      ((s['overlaps'] as List).isNotEmpty && !ackOverlaps) ||
                      ((s['removed'] as List).isNotEmpty && !ackRemovals)
                  ? null
                  : () => save(views, byId),
            ),
          ),
        ];
      case 'done':
        buttons = [Expanded(child: DueButton(label: 'Done', expand: true, onPressed: () => Navigator.pop(context)))];
      default:
        return null;
    }
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: c.sheet, border: Border(top: BorderSide(color: c.graphite))),
      child: SafeArea(top: false, child: Row(spacing: 8, children: buttons)),
    );
  }

  Widget _choose() {
    final c = Palette.of(context);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(
          'Upload your department’s timetable PDF, or screenshots of the Somaiya roster scheduler. Weekly slots are saved when you confirm; '
          'creating subjects saves them immediately.',
          style: TextStyle(color: c.graphite2),
        ),
        const SizedBox(height: 16),
        InkWell(
          onTap: pick,
          child: Container(
            padding: const EdgeInsets.symmetric(vertical: 28, horizontal: 16),
            decoration: BoxDecoration(color: c.inkWash, border: Border.all(color: c.inkLine, width: 1.5)),
            child: Column(children: [
              Icon(Icons.upload_file, size: 28, color: c.ink),
              const SizedBox(height: 8),
              const Text('Choose your timetable', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
              Text('The timetable PDF, or up to four scheduler screenshots', style: TextStyle(color: c.graphite2)),
            ]),
          ),
        ),
        if (fileError != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(fileError!, style: TextStyle(color: c.ink, fontWeight: FontWeight.w600))),
        const SizedBox(height: 12),
        for (final (i, f) in files.indexed)
          Container(
            padding: const EdgeInsets.symmetric(vertical: 6),
            decoration: BoxDecoration(border: Border(bottom: BorderSide(color: c.inkRule))),
            child: Row(children: [
              f.contentType.startsWith('image/')
                  ? Image.memory(f.bytes, width: 48, height: 48, fit: BoxFit.cover)
                  : Container(width: 48, height: 48, alignment: Alignment.center, color: c.inkTint, child: const Printed('PDF')),
              const SizedBox(width: 10),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(f.name, maxLines: 1, overflow: TextOverflow.ellipsis),
                  Text('${(f.bytes.length / _mb).toStringAsFixed(1)} MB', style: TextStyle(color: c.graphite2, fontSize: 12.5)),
                ]),
              ),
              if (files.length > 1) ...[
                IconButton(
                  tooltip: 'Move ${f.name} up',
                  icon: const Icon(Icons.arrow_upward, size: 18),
                  onPressed: i == 0 ? null : () => setState(() => files.insert(i - 1, files.removeAt(i))),
                ),
                IconButton(
                  tooltip: 'Move ${f.name} down',
                  icon: const Icon(Icons.arrow_downward, size: 18),
                  onPressed: i == files.length - 1 ? null : () => setState(() => files.insert(i + 1, files.removeAt(i))),
                ),
              ],
              IconButton(tooltip: 'Remove ${f.name}', icon: const Icon(Icons.close, size: 18), onPressed: () => setState(() => files.removeAt(i))),
            ]),
          ),
        const SizedBox(height: 12),
        const Text.rich(TextSpan(children: [
          TextSpan(text: 'Timetable PDF ', style: TextStyle(fontWeight: FontWeight.w700)),
          TextSpan(
              text: 'shared by your department (the class timetable with Monday–Friday columns). A scan or a clear, uncropped picture '
                  'of it also works; check the text it reads.'),
        ])),
        const SizedBox(height: 8),
        const Text.rich(TextSpan(children: [
          TextSpan(text: 'Somaiya roster scheduler screenshots: ', style: TextStyle(fontWeight: FontWeight.w700)),
          TextSpan(text: 'open My Scheduler, choose Week, and take screenshots while scrolling so every hour appears in at least one.'),
        ])),
        const SizedBox(height: 12),
        Text(
          'Files are read on DueCare’s server and are not stored. Only course names may be sent to DueCare’s AI provider, '
          'to suggest which of your subjects they belong to.',
          style: TextStyle(color: c.graphite2, fontSize: 13),
        ),
        ErrorNotice(error),
      ],
    );
  }

  Widget _progress() {
    final c = Palette.of(context);
    Widget step(String label, bool active, bool done) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 10),
          child: Row(children: [
            SizedBox(
              width: 20,
              height: 20,
              child: active ? CircularProgressIndicator(strokeWidth: 2, color: c.ink) : Icon(done ? Icons.check : Icons.circle_outlined, size: 18, color: done ? c.good : c.inkLine),
            ),
            const SizedBox(width: 12),
            Text(label, style: TextStyle(fontWeight: active ? FontWeight.w700 : FontWeight.w500)),
          ]),
        );
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        step('Reading your timetable', stage == 'reading', stage == 'organizing'),
        step('Organizing your timetable', stage == 'organizing', false),
      ]),
    );
  }

  Widget _done() => Padding(
        padding: const EdgeInsets.all(24),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(Icons.check, size: 30, color: Palette.of(context).good),
          const SizedBox(height: 8),
          Text('Timetable saved', style: display(context, 28)),
          const SizedBox(height: 8),
          Text(
            '${saved!.slots} weekly ${saved!.slots == 1 ? 'slot' : 'slots'} saved across ${saved!.subjects} '
            '${saved!.subjects == 1 ? 'subject' : 'subjects'}. Open a subject’s Timetable to see or adjust them.',
          ),
        ]),
      );

  Widget _review(List<RowView> views, Map<String, Subject> byId, List<Subject> subjects) {
    final c = Palette.of(context);
    final d = draft!;
    final included = coursesOf(views.where((v) => v.included).toList())
        .map((course) => course.subjectId != null && !byId.containsKey(course.subjectId)
            ? Course(
                key: course.key,
                label: course.label,
                code: course.code,
                component: course.component,
                track: course.track,
                slots: course.slots,
                subjectId: null,
                mixed: course.mixed,
                suggestion: course.suggestion,
                suggestionSource: course.suggestionSource,
                needsReview: course.needsReview,
                notes: course.notes,
              )
            : course)
        .toList();
    final attention = included.where((c) => c.needsReview).toList();
    final ready = included.where((c) => !c.needsReview).toList()
      ..sort((a, b) => (byId[a.subjectId]?.name ?? '').compareTo(byId[b.subjectId]?.name ?? ''));
    final unlinked = included.where((c) => c.subjectId == null).toList();
    final suggestions = unlinked.where((c) => c.suggestion != null && byId.containsKey(c.suggestion)).toList();
    final unmatched = unlinked.where((c) => !suggestions.contains(c)).toList();
    final excluded = views.where((v) => !v.included).toList();
    final groups = choiceGroupsOf(rows, taken);
    final openChoices = groups.where((g) => !choices.containsKey(g.key)).length;
    final readyRows = views.where((v) => v.included && v.problems.isEmpty).length;
    final counts = [
      '$readyRows ready',
      if (unlinked.isNotEmpty) '${unlinked.length} ${unlinked.length == 1 ? 'course needs' : 'courses need'} a subject',
      if (openChoices > 0) '$openChoices group ${openChoices == 1 ? 'choice' : 'choices'} left',
      if (excluded.isNotEmpty) '${excluded.length} not included',
    ];
    final pages = ((reading?['pages'] as List?) ?? []).cast<Map>();
    final mismatches = ((d['documents'] as List?) ?? []).cast<Map>().where((doc) =>
        doc['mismatch'] != null && rows.any((r) => r['page'] == doc['page'] && r['exclusionReason'] == doc['mismatch']));
    final families = ((d['families'] as List?) ?? []).cast<Map>();
    final profileChanged = error is ApiError && (error as ApiError).code == 'PROFILE_CHANGED';
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
      children: [
        Row(children: [
          Expanded(
            child: BubbleChoice<bool>(
              value: original,
              options: const [(false, 'Draft'), (true, 'Original')],
              onChanged: (v) => setState(() => original = v),
            ),
          ),
        ]),
        const SizedBox(height: 12),
        if (original)
          for (final (i, p) in pages.indexed) _OriginalPage(page: p, file: i < files.length ? files[i] : null)
        else ...[
          Text('${counts.join(' · ')}${d['batch'] != null ? ' · Your batch: ${d['batch']}' : ''}', style: const TextStyle(fontWeight: FontWeight.w600)),
          Text('This draft is only on this screen. Leaving discards it.', style: TextStyle(color: c.graphite2, fontSize: 12.5)),
          if ((d['ai'] as Map?)?['unavailable'] == true)
            const Notice('Subject suggestions are unavailable right now. Link subjects yourself, or close and try again later.', warn: true),
          for (final p in pages)
            for (final issue in ((p['issues'] as List?) ?? []).cast<String>()) Notice(issue, warn: true),
          for (final doc in mismatches)
            Panel(
              margin: const EdgeInsets.symmetric(vertical: 6),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${doc['mismatch']} (${doc['classLabel']}), not your profile’s class. Its classes are excluded.'),
                const SizedBox(height: 8),
                DueButton(
                  label: 'Include them anyway',
                  small: true,
                  variant: Variant.outline,
                  onPressed: () => update(
                    {for (final r in rows) if (r['page'] == doc['page'] && r['exclusionReason'] == doc['mismatch'] && r['otherBatch'] != true) r['id'] as String},
                    {'include': true, 'exclusionReason': null},
                  ),
                ),
              ]),
            ),
          const SizedBox(height: 10),
          Wrap(spacing: 8, runSpacing: 8, children: [
            if (unlinked.any((c) => c.label.trim().isNotEmpty))
              DueButton(
                label: busy ? 'Creating subjects…' : 'Instant create subjects',
                icon: Icons.add,
                small: true,
                onPressed: busy ? null : () => instant(unlinked, byId, subjects),
              ),
            if (suggestions.isNotEmpty)
              DueButton(
                label: 'Accept ${suggestions.length} suggested ${suggestions.length == 1 ? 'link' : 'links'}',
                icon: Icons.check,
                small: true,
                variant: Variant.outline,
                onPressed: () => setState(() {
                  final target = {for (final c in suggestions) for (final v in c.slots) v.id: c.suggestion};
                  rows = [for (final r in rows) target.containsKey(r['id']) ? {...r, 'subjectId': target[r['id']], 'link': 'accepted'} : r];
                  summary = null;
                }),
              ),
            if (unmatched.isNotEmpty)
              DueButton(
                label: 'Exclude ${unmatched.length} ${unmatched.length == 1 ? 'course' : 'courses'} without a subject',
                icon: Icons.close,
                small: true,
                variant: Variant.outline,
                onPressed: () => update({for (final c in unmatched) ...c.rowIds}, {'include': false, 'exclusionReason': 'Excluded by you'}),
              ),
            DueButton(
              label: 'Add a missed slot',
              icon: Icons.add,
              small: true,
              variant: Variant.ghost,
              onPressed: () => setState(() {
                added++;
                rows = [
                  ...rows,
                  {
                    'id': 'm$added', 'cellId': null, 'page': null, 'bbox': null, 'sourceText': 'Added by you', 'label': '', 'baseLabel': '', //
                    'code': null, 'group': null, 'batches': <String>[], 'component': null, 'weekday': 1, 'startTime': '', 'endTime': '',
                    'location': null, 'instructor': null, 'include': true, 'otherBatch': false, 'exclusionReason': null, 'subjectId': null,
                    'link': 'manual', 'suggestedSubjectId': null, 'suggestionSource': null, 'choiceKey': null, 'choiceLabel': null,
                    'issues': <String>[],
                  },
                ];
              }),
            ),
          ]),
          const SizedBox(height: 6),
          Text('Create and link all recognized subjects in one tap, using the timetable names. Existing matches are reused. You can edit subjects later.',
              style: TextStyle(color: c.graphite2, fontSize: 12.5)),
          if (status.isNotEmpty) Notice(status),
          if (families.isNotEmpty)
            _Section(
              title: 'Your electives, honours and minor',
              help: 'Tick the ones you take. Each includes its theory, lab and tutorial slots; the rest are left out.',
              children: [
                for (final f in families)
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    controlAffinity: ListTileControlAffinity.leading,
                    value: taken[f['key']] ?? false,
                    title: Text('${f['name']}'),
                    subtitle: Text('${f['track'] == 'honours' ? 'Honours' : f['track'] == 'minor' ? 'Minor' : 'Elective'} · ${f['slots']} ${f['slots'] == 1 ? 'slot' : 'slots'}'),
                    onChanged: (v) => setState(() {
                      taken = {...taken, f['key'] as String: v ?? false};
                      summary = null;
                    }),
                  ),
              ],
            ),
          if (groups.isNotEmpty)
            _Section(
              title: 'Your groups',
              help: 'These classes run as parallel groups, teachers or rooms. Choose the one you attend; the others are left out.',
              children: [
                for (final g in groups)
                  Field(
                    label: g.title,
                    child: SelectField<String>(
                      value: choices[g.key],
                      title: g.title,
                      options: [for (final o in g.options.keys) (o, o), ('none', 'I don’t take this')],
                      onChanged: (v) => setState(() {
                        choices = {...choices, g.key: v};
                        summary = null;
                      }),
                    ),
                  ),
              ],
            ),
          if (attention.isNotEmpty)
            _Section(
              title: 'Needs your review (${attention.length})',
              children: [for (final course in attention) _courseCard(course, subjects, byId)],
            ),
          if (ready.isNotEmpty)
            _Section(title: 'Ready (${ready.length})', children: [for (final course in ready) _courseCard(course, subjects, byId)]),
          if (excluded.isNotEmpty)
            ExpansionTile(
              tilePadding: EdgeInsets.zero,
              shape: const Border(),
              title: Text('Not included (${excluded.length})'),
              children: [
                for (final v in excluded)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(
                      '${(v.row['label'] as String?)?.isNotEmpty ?? false ? v.row['label'] : v.row['sourceText']} · '
                      '${weekdayNames[(v.row['weekday'] as num).toInt() - 1].substring(0, 3)} ${v.row['startTime']}',
                    ),
                    subtitle: Text(v.reason ?? 'Excluded'),
                    trailing: v.row['include'] == true
                        ? null
                        : DueButton(
                            label: 'Include',
                            small: true,
                            variant: Variant.ghost,
                            onPressed: () => update({v.id}, {'include': true, 'exclusionReason': null}),
                          ),
                  ),
              ],
            ),
          if (profileChanged)
            Panel(
              margin: const EdgeInsets.symmetric(vertical: 8),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('Your academic details changed. Refresh the batch decisions to continue. Your subject links and time edits will be kept.'),
                const SizedBox(height: 8),
                DueButton(label: 'Refresh batch decisions', small: true, onPressed: busy ? null : () => _run(() => _interpret(refresh: true))),
              ]),
            )
          else
            ErrorNotice(error),
        ],
      ],
    );
  }

  Widget _courseCard(Course course, List<Subject> subjects, Map<String, Subject> byId) {
    final c = Palette.of(context);
    final ids = course.rowIds;
    final suggestion = course.subjectId == null && course.suggestion != null ? byId[course.suggestion] : null;
    return Panel(
      hatched: course.needsReview,
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(course.label.isEmpty ? 'New slot' : course.label, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
          Text(
            '${[course.code, course.track, course.component].whereType<String>().where((s) => s.isNotEmpty).join(' · ')} · '
            '${course.slots.length} weekly ${course.slots.length == 1 ? 'slot' : 'slots'}',
            style: TextStyle(color: c.graphite2, fontSize: 12.5),
          ),
          const SizedBox(height: 8),
          Field(
            label: 'Subject',
            child: SelectField<String>(
              value: course.subjectId,
              placeholder: course.mixed ? 'Different subjects. Choose one…' : 'Choose a subject…',
              title: 'Subject',
              options: [for (final s in subjects) (s.id, s.label)],
              onChanged: (v) => update(ids, {'subjectId': v, 'link': 'manual'}),
            ),
          ),
          if (suggestion != null)
            Wrap(crossAxisAlignment: WrapCrossAlignment.center, spacing: 8, children: [
              Text('Suggested: ${suggestion.label}${course.suggestionSource == 'ai' ? ' (AI)' : ''}'),
              DueButton(label: 'Use this', small: true, variant: Variant.outline, onPressed: () => update(ids, {'subjectId': suggestion.id, 'link': 'accepted'})),
            ]),
          if (course.subjectId == null)
            _CreateSubject(
              course: course,
              subjects: subjects,
              busy: busy,
              onLinked: (id) => update(ids, {'subjectId': id, 'link': 'manual'}),
              run: _run,
            ),
          for (final (n, v) in course.slots.indexed) _slotEditor(v, n + 1),
          for (final note in course.notes) Padding(padding: const EdgeInsets.only(top: 4), child: Text('• $note', style: TextStyle(color: c.dueText, fontSize: 12.5))),
        ],
      ),
    );
  }

  Widget _slotEditor(RowView v, int number) {
    final c = Palette.of(context);
    final r = v.row;
    final weekday = (r['weekday'] as num).toInt();
    final tag = [((r['batches'] as List?) ?? []).join(', '), r['choiceLabel'] ?? ''].where((s) => '$s'.isNotEmpty).join(' · ');
    final problems = v.problems.where((p) => p != 'Choose a subject').toList();
    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.only(top: 8),
      decoration: BoxDecoration(border: Border(top: BorderSide(color: c.inkRule))),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Text(number.toString().padLeft(2, '0'), style: display(context, 14, color: c.ink)),
            const SizedBox(width: 8),
            Expanded(child: Text('${weekdayNames[weekday - 1]} · ${_slotTime('${r['startTime'] ?? ''}')} – ${_slotTime('${r['endTime'] ?? ''}')}')),
            IconButton(
              tooltip: 'Exclude ${weekdayNames[weekday - 1]} ${r['startTime']}',
              icon: const Icon(Icons.delete_outline, size: 18),
              onPressed: () => update({v.id}, {'include': false, 'exclusionReason': 'Excluded by you'}),
            ),
          ]),
          SelectField<int>(
            value: weekday,
            title: 'Day',
            options: [for (final (n, d) in weekdayNames.indexed) (n + 1, d)],
            onChanged: (d) => update({v.id}, {'weekday': d}),
          ),
          const SizedBox(height: 6),
          Row(children: [
            Expanded(child: TimeField(value: hhmm('${r['startTime'] ?? ''}'), placeholder: 'Starts', onChanged: (t) => update({v.id}, {'startTime': t}))),
            const SizedBox(width: 6),
            Expanded(child: TimeField(value: hhmm('${r['endTime'] ?? ''}'), placeholder: 'Ends', onChanged: (t) => update({v.id}, {'endTime': t}))),
          ]),
          const SizedBox(height: 6),
          TextFormField(
            key: ValueKey('room-${v.id}'),
            initialValue: r['location'] as String? ?? '',
            decoration: const InputDecoration(hintText: 'Room'),
            onChanged: (t) {
              rows = [for (final x in rows) x['id'] == v.id ? {...x, 'location': t} : x];
              summary = null;
            },
          ),
          if (tag.isNotEmpty || problems.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Wrap(spacing: 8, children: [
                if (tag.isNotEmpty) Tag(tag),
                for (final p in problems) Text(p, style: TextStyle(color: c.ink, fontWeight: FontWeight.w600, fontSize: 13)),
              ]),
            ),
        ],
      ),
    );
  }

  Widget _summaryView(List<RowView> views, Map<String, Subject> byId) {
    final c = Palette.of(context);
    final s = summary!;
    List<Map> list(String k) => ((s[k] as List?) ?? []).cast<Map>();
    String line(Map x) =>
        '${x['subjectName']} ${weekdayNames[(x['weekday'] as num).toInt() - 1].substring(0, 3)} ${x['startTime']}–${x['endTime']}'
        '${x['location'] != null ? ' · ${x['location']}' : ''}';
    final nothing = list('added').length + list('updated').length + list('removed').length == 0;
    void setMode(String m) {
      setState(() => mode = m);
      preview(views, byId);
    }

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text('How should these slots be saved?', style: display(context, 22)),
        const SizedBox(height: 8),
        for (final (value, title, body) in [
          ('add', 'Add to existing timetable', 'Keeps every slot already saved.'),
          ('replace', 'Replace timetable for these subjects', 'Removes their other saved slots. Subjects not in this import keep theirs.'),
        ])
          InkWell(
            onTap: busy ? null : () => setMode(value),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Bubble(fill: mode == value ? c.graphite : null, stroke: mode == value ? c.graphite : null),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
                    Text(body, style: TextStyle(color: c.graphite2, fontSize: 13)),
                  ]),
                ),
              ]),
            ),
          ),
        if (nothing) const Notice('Every slot is already saved. There is nothing new to add.'),
        if (list('added').isNotEmpty) _Section(title: 'Will add (${list('added').length})', children: [for (final x in list('added')) Text(line(x))]),
        if (list('updated').isNotEmpty)
          _Section(title: 'Will update room (${list('updated').length})', children: [for (final x in list('updated')) Text(line(x))]),
        if (list('duplicates').isNotEmpty)
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            shape: const Border(),
            title: Text('Already saved, skipped (${list('duplicates').length})'),
            children: [for (final x in list('duplicates')) Align(alignment: Alignment.centerLeft, child: Text(line(x)))],
          ),
        if (list('removed').isNotEmpty)
          _Section(title: 'Will remove (${list('removed').length})', children: [
            for (final x in list('removed')) Text(line(x)),
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              value: ackRemovals,
              title: const Text('I reviewed these removals'),
              onChanged: (v) => setState(() => ackRemovals = v ?? false),
            ),
          ]),
        if (list('overlaps').isNotEmpty)
          _Section(title: 'Overlapping classes (${list('overlaps').length})', children: [
            for (final o in list('overlaps'))
              Text('${weekdayNames[((o['first'] as Map)['weekday'] as num).toInt() - 1].substring(0, 3)}: '
                  '${(o['first'] as Map)['subjectName']} ${(o['first'] as Map)['startTime']}–${(o['first'] as Map)['endTime']} overlaps '
                  '${(o['second'] as Map)['subjectName']} ${(o['second'] as Map)['startTime']}–${(o['second'] as Map)['endTime']}'),
            Text('Go back to exclude or correct one, or keep both if they really overlap.', style: TextStyle(color: c.graphite2, fontSize: 12.5)),
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              value: ackOverlaps,
              title: const Text('Keep overlapping classes'),
              onChanged: (v) => setState(() => ackOverlaps = v ?? false),
            ),
          ]),
        ErrorNotice(error),
      ],
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({required this.title, this.help, required this.children});

  final String title;
  final String? help;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
            if (help != null) Text(help!, style: TextStyle(color: Palette.of(context).graphite2, fontSize: 12.5)),
            const SizedBox(height: 6),
            ...children,
          ],
        ),
      );
}

/// Create a subject from a course and link its slots, offering an existing match first.
class _CreateSubject extends StatefulWidget {
  const _CreateSubject({required this.course, required this.subjects, required this.busy, required this.onLinked, required this.run});

  final Course course;
  final List<Subject> subjects;
  final bool busy;
  final ValueChanged<String> onLinked;
  final Future<void> Function(Future<void> Function()) run;

  @override
  State<_CreateSubject> createState() => _CreateSubjectState();
}

class _CreateSubjectState extends State<_CreateSubject> {
  bool open = false;
  late final name = TextEditingController(text: widget.course.label);
  late String kind = importSubjectKind(widget.course.slots.first.row, widget.subjects);

  @override
  void dispose() {
    name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final course = widget.course;
    if (!open) {
      return Wrap(crossAxisAlignment: WrapCrossAlignment.center, spacing: 8, children: [
        Text('Choose a subject', style: TextStyle(color: c.ink, fontWeight: FontWeight.w600)),
        DueButton(label: 'Create subject from this', icon: Icons.add, small: true, variant: Variant.ghost, onPressed: () => setState(() => open = true)),
      ]);
    }
    // The same name and kind is never created twice; link the existing subject instead.
    final existing = widget.subjects.where((s) => s.kind == kind && normalized(s.name) == normalized(name.text)).firstOrNull;
    final similar = course.suggestion == null ? null : widget.subjects.where((s) => s.id == course.suggestion).firstOrNull;
    final alias = course.label.isNotEmpty && normalized(course.label) != normalized(name.text);
    return Container(
      margin: const EdgeInsets.only(top: 6),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(color: c.inkWash, border: Border.all(color: c.inkRule)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Field(label: 'New subject name', child: TextField(controller: name, maxLength: 200, onChanged: (_) => setState(() {}))),
        Field(
          label: 'Kind',
          child: BubbleChoice<String>(
            value: kind,
            options: const [('theory', 'Theory'), ('lab', 'Lab'), ('tutorial', 'Tutorial')],
            onChanged: (v) => setState(() => kind = v),
          ),
        ),
        if (alias)
          Text('“${course.label}” will be saved as another name for it${course.code != null ? ', with course code ${course.code}' : ''}.',
              style: TextStyle(color: c.graphite2, fontSize: 12.5)),
        if (existing != null || similar != null)
          Wrap(crossAxisAlignment: WrapCrossAlignment.center, spacing: 8, children: [
            Text(existing != null ? 'You already have ${existing.label}.' : 'This looks like your ${similar!.label}.'),
            DueButton(label: 'Use it', small: true, variant: Variant.outline, onPressed: () => widget.onLinked((existing ?? similar)!.id)),
          ]),
        const SizedBox(height: 6),
        Wrap(spacing: 8, children: [
          DueButton(
            label: 'Create and link ${course.slots.length} ${course.slots.length == 1 ? 'slot' : 'slots'}',
            small: true,
            onPressed: name.text.trim().isEmpty || existing != null || widget.busy
                ? null
                : () => widget.run(() async {
                      final services = AppScope.of(context);
                      final s = (await services.api.send('POST', '/subjects', body: {
                        'name': name.text.trim(),
                        'kind': kind,
                        'code': course.code,
                        // The printed label stays recognizable in later imports and source matching.
                        'aliases': alias ? [course.label] : <String>[],
                      })) as Map;
                      await services.queries.fetch(Keys.subjects, () => loadSubjects(services.api));
                      widget.onLinked(s['id'] as String);
                      if (mounted) setState(() => open = false);
                    }),
          ),
          DueButton(label: 'Cancel', small: true, variant: Variant.ghost, onPressed: () => setState(() => open = false)),
        ]),
      ]),
    );
  }
}

/// A page of the uploaded original, to check the draft against.
class _OriginalPage extends StatelessWidget {
  const _OriginalPage({required this.page, required this.file});

  final Map page;
  final _File? file;

  @override
  Widget build(BuildContext context) {
    final preview = page['preview'] as String?;
    Uint8List? bytes;
    if (preview != null && preview.startsWith('data:')) {
      bytes = base64Decode(preview.substring(preview.indexOf(',') + 1));
    } else if (file != null && file!.contentType.startsWith('image/')) {
      bytes = file!.bytes;
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${page['source']}${page['visible'] != null ? ' · shows ${page['visible']}' : ''}',
            style: TextStyle(color: Palette.of(context).graphite2, fontSize: 12.5)),
        const SizedBox(height: 6),
        if (bytes != null)
          InteractiveViewer(maxScale: 5, child: Image.memory(bytes))
        else
          const Text('No preview for this page.'),
      ]),
    );
  }
}
