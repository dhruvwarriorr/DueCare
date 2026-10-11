import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/models.dart';
import '../core/query.dart';
import '../state/data.dart';
import '../state/services.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

/// A rule as one plain sentence: "Make ITVC work high priority", "Hide work containing “seminar”"
/// (apps/web rules.tsx › describe).
String describeRule(Json rule, List<Subject> subjects) {
  String value(Json c) => c['value'] is List ? (c['value'] as List).join(', ') : '${c['value']}';
  var what = 'work';
  final parts = <String>[];
  for (final c in ((rule['conditions'] as List?) ?? []).cast<Map>().map((m) => m.cast<String, dynamic>())) {
    final v = value(c);
    switch (c['field']) {
      case 'taskType':
        what = v == 'test' ? 'tests' : 'assignments';
      case 'subjectId':
        // One course can be several subjects (ITVC theory and tutorial): name it once.
        final ids = c['value'] is List ? (c['value'] as List).cast<String>() : ['${c['value']}'];
        final names = ids.map((id) => subjects.where((s) => s.id == id).firstOrNull?.name).whereType<String>().toSet();
        parts.insert(0, names.isEmpty ? 'a subject' : names.join(' / '));
      case 'subjectKind':
        parts.insert(0, v);
      case 'source':
        parts.add('from ${v == 'gmail' ? 'Gmail' : 'Classroom'}');
      case 'sender':
        parts.add('from $v');
      case 'keyword':
        parts.add('containing “$v”');
      case 'assessmentLabel':
        parts.add('labelled “$v”');
    }
  }
  final subject = parts.isNotEmpty && !RegExp(r'^(from|containing|labelled)').hasMatch(parts.first) ? '${parts.removeAt(0)} ' : '';
  final tail = parts.isEmpty ? '' : ' ${parts.join(' ')}';
  final action = (rule['action'] as Map?) ?? {};
  return action['type'] == 'priority' ? 'Make $subject$what$tail ${action['priority']} priority' : 'Hide $subject$what$tail';
}

Json ruleDraft(String doing, String target, String value, List<Subject> subjects) {
  final rule = <String, dynamic>{
    'name': '',
    'enabled': true,
    'match': 'all',
    'exceptions': <Json>[],
    'conditions': [
      {'field': target, 'op': target == 'keyword' ? 'contains' : 'equals', 'value': value.trim()},
    ],
    'action': doing == 'hide' ? {'type': 'exclude'} : {'type': 'priority', 'priority': doing},
  };
  final name = describeRule(rule, subjects);
  return {...rule, 'name': name.length > 200 ? name.substring(0, 200) : name};
}

class RulesScreen extends StatefulWidget {
  const RulesScreen({super.key});

  @override
  State<RulesScreen> createState() => _RulesScreenState();
}

class _RulesScreenState extends State<RulesScreen> {
  final sentence = TextEditingController();
  Json? preview;
  String? unsupported;
  bool building = false;
  bool pending = false;
  Object? error;
  String doing = 'high', target = 'subjectId', value = '';
  final valueText = TextEditingController();

  @override
  void dispose() {
    sentence.dispose();
    valueText.dispose();
    super.dispose();
  }

  // Rules apply to every task at once, so lists, counts and the week all change with them.
  Future<void> _run(Future<void> Function(Services s) action) async {
    final services = AppScope.of(context);
    setState(() {
      pending = true;
      error = null;
    });
    try {
      await action(services);
      await services.queries.invalidate(['rules', 'tasks', 'task', 'overview']);
    } on ApiError catch (e) {
      error = e;
    }
    if (mounted) setState(() => pending = false);
  }

  Future<void> read() => _run((s) async {
        final out = (await s.api.send('POST', '/rules/interpret', body: {'instruction': sentence.text})) as Map;
        final rule = (out['rule'] as Map).cast<String, dynamic>();
        preview = {...rule, 'exceptions': rule['exceptions'] ?? []};
        unsupported = out['unsupported'] as String?;
      });

  Future<void> save(List<Subject> subjects) => _run((s) async {
        final name = describeRule(preview!, subjects);
        await s.api.send('POST', '/rules', body: {...preview!, 'name': name.length > 200 ? name.substring(0, 200) : name});
        preview = null;
        unsupported = null;
        sentence.clear();
      });

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final api = AppScope.of(context).api;
    return Scaffold(
      appBar: AppBar(title: const Text('Rules')),
      body: QueryView(
        queryKey: Keys.subjects,
        fetch: () => loadSubjects(api),
        builder: (context, sq) {
          final subjects = subjectsOf(sq);
          return QueryView(
            queryKey: Keys.rules,
            fetch: () => api.get('/rules'),
            builder: (context, q) {
              final rules = pageOf(q.data).items.map(Rule.new).toList();
              return ListView(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
                children: [
                  const SectionHeader(
                    title: 'Rules',
                    subtitle: 'Tell DueCare what matters to you. Rules apply to all your tasks right away, and to new ones as they arrive. '
                        'Turning a rule off undoes it.',
                  ),
                  Panel(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Field(
                          label: 'Add a rule',
                          child: TextField(
                            controller: sentence,
                            onChanged: (_) => setState(() {}),
                            onSubmitted: (_) => sentence.text.trim().length >= 3 ? read() : null,
                            decoration: const InputDecoration(hintText: 'e.g. make ITVC high priority · hide seminar mail'),
                          ),
                        ),
                        DueButton(label: pending && preview == null ? 'Reading…' : 'Add', onPressed: pending || sentence.text.trim().length < 3 ? null : read),
                        if (preview == null)
                          DueButton(
                            label: building ? 'Hide the builder' : 'Or build it yourself',
                            variant: Variant.ghost,
                            small: true,
                            onPressed: () => setState(() => building = !building),
                          ),
                        if (building && preview == null) _builder(subjects),
                        if (preview != null)
                          Container(
                            width: double.infinity,
                            margin: const EdgeInsets.only(top: 12),
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(color: c.inkWash, border: Border.all(color: c.graphite)),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('${describeRule(preview!, subjects)}.', style: const TextStyle(fontWeight: FontWeight.w700)),
                                if (unsupported != null)
                                  Text('Left out (not something rules can do): $unsupported', style: TextStyle(color: c.graphite2, fontSize: 13)),
                                const SizedBox(height: 10),
                                Wrap(spacing: 8, runSpacing: 8, children: [
                                  DueButton(label: 'Save rule', onPressed: pending ? null : () => save(subjects)),
                                  DueButton(
                                    label: 'Not right? Build it instead',
                                    variant: Variant.ghost,
                                    onPressed: () => setState(() {
                                      preview = null;
                                      building = true;
                                    }),
                                  ),
                                ]),
                              ],
                            ),
                          ),
                        ErrorNotice(error),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                  ErrorNotice(q.error, retry: q.refetch),
                  if (q.isPending)
                    const Loading('Loading rules…')
                  else if (rules.isEmpty)
                    const EmptyState(
                      icon: Icons.tune,
                      title: 'No rules yet',
                      body: 'Without rules, every task you get is shown, with priority based on its deadline.',
                    )
                  else
                    Container(
                      decoration: BoxDecoration(border: Border.all(color: c.inkLine), color: c.sheet),
                      child: Column(children: [for (final r in rules) _ruleRow(r, subjects)]),
                    ),
                  const SizedBox(height: 12),
                  Text(
                    'Hidden work is kept, just out of your lists; find it under Tasks → More filters → Only work hidden by rules. '
                    'If two priority rules match the same task, the older rule wins. A priority you set on a task yourself always wins.',
                    style: TextStyle(color: c.graphite2, fontSize: 13),
                  ),
                ],
              );
            },
          );
        },
      ),
    );
  }

  Widget _ruleRow(Rule r, List<Subject> subjects) {
    final c = Palette.of(context);
    final text = describeRule(r.json, subjects);
    return Opacity(
      opacity: r.enabled ? 1 : 0.6,
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 8, 4, 8),
        decoration: BoxDecoration(border: Border(bottom: BorderSide(color: c.inkRule))),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(text, style: const TextStyle(fontWeight: FontWeight.w600)),
              Text(r.enabled ? 'Applies to ${r.affects} ${r.affects == 1 ? 'task' : 'tasks'}' : 'Off', style: TextStyle(color: c.graphite2, fontSize: 13)),
            ]),
          ),
          Switch(
            value: r.enabled,
            onChanged: pending
                ? null
                : (on) => _run((s) => s.api.send('PATCH', '/rules/${r.id}', body: {
                      'revision': r.revision,
                      'name': r.name,
                      'enabled': on,
                      'match': r.json['match'],
                      'conditions': r.json['conditions'],
                      'exceptions': r.json['exceptions'],
                      'action': r.json['action'],
                      'instruction': r.json['instruction'],
                    })),
          ),
          IconButton(
            tooltip: 'Delete rule: $text',
            icon: const Icon(Icons.delete_outline, size: 20),
            onPressed: pending ? null : () => _run((s) => s.api.send('DELETE', '/rules/${r.id}?revision=${r.revision}')),
          ),
        ]),
      ),
    );
  }

  Widget _builder(List<Subject> subjects) {
    final choices = <String, List<(String, String)>>{
      'subjectId': [for (final s in subjects) (s.id, s.label)],
      'taskType': const [('test', 'Tests'), ('assignment', 'Assignments')],
      'source': const [('gmail', 'Gmail'), ('classroom', 'Classroom')],
    };
    final options = choices[target];
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Field(
            label: 'Do',
            child: SelectField<String>(
              value: doing,
              title: 'Do',
              options: const [
                ('high', 'Make high priority'),
                ('critical', 'Make critical priority'),
                ('medium', 'Make medium priority'),
                ('low', 'Make low priority'),
                ('hide', 'Hide'),
              ],
              onChanged: (v) => setState(() => doing = v),
            ),
          ),
          Field(
            label: 'For',
            child: SelectField<String>(
              value: target,
              title: 'For',
              options: const [
                ('subjectId', 'a subject'),
                ('taskType', 'tests or assignments'),
                ('keyword', 'work containing a word'),
                ('sender', 'mail from a sender'),
                ('source', 'Gmail or Classroom'),
              ],
              onChanged: (v) => setState(() {
                target = v;
                value = '';
                valueText.clear();
              }),
            ),
          ),
          Field(
            label: 'Which',
            child: options != null
                ? SelectField<String>(value: value.isEmpty ? null : value, title: 'Which', options: options, onChanged: (v) => setState(() => value = v))
                : TextField(
                    controller: valueText,
                    onChanged: (v) => setState(() => value = v),
                    decoration: InputDecoration(hintText: target == 'sender' ? 'name@somaiya.edu' : 'e.g. seminar'),
                  ),
          ),
          DueButton(
            label: 'Preview',
            variant: Variant.outline,
            onPressed: value.trim().isEmpty
                ? null
                : () => setState(() {
                      preview = ruleDraft(doing, target, value, subjects);
                      unsupported = null;
                    }),
          ),
        ],
      ),
    );
  }
}
