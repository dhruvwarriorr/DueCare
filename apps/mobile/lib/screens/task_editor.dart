import 'dart:async';

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

/// Add or edit a task. Only a title is needed; the deadline is an IST date and an optional time.
class TaskEditorScreen extends StatefulWidget {
  const TaskEditorScreen({super.key, this.task});

  final Task? task;

  @override
  State<TaskEditorScreen> createState() => _TaskEditorScreenState();
}

class _TaskEditorScreenState extends State<TaskEditorScreen> {
  late final title = TextEditingController(text: widget.task?.title ?? '');
  late final notes = TextEditingController(text: widget.task?.notes ?? '');
  late String type = widget.task?.type ?? 'assignment';
  late String subjectId = widget.task?.subjectId ?? '';
  late String priority = widget.task?.priorityOverride ?? '';
  late final ({String date, String time}) initial = _deadlineOf(widget.task);
  late String date = initial.date;
  late String time = initial.time;
  String? titleError;
  bool pending = false;
  Object? error;

  // Deadline inputs split the stored IST cutoff into a date and an optional time.
  static ({String date, String time}) _deadlineOf(Task? t) {
    if (t?.dueDate != null) return (date: t!.dueDate!, time: '');
    final local = localTime(t?.dueAt);
    return local.isEmpty ? (date: '', time: '') : (date: local.substring(0, 10), time: local.substring(11, 16));
  }

  @override
  void dispose() {
    title.dispose();
    notes.dispose();
    super.dispose();
  }

  Future<void> save() async {
    final name = title.text.trim();
    if (name.isEmpty) {
      setState(() => titleError = 'Give the task a name');
      return;
    }
    final task = widget.task;
    final body = <String, dynamic>{
      'title': name,
      'type': type,
      'subjectId': subjectId.isEmpty ? null : subjectId,
      'priorityOverride': priority.isEmpty ? null : priority,
      'notes': notes.text,
    };
    // Only rewrite timing when the student changed it, so imported test details (start,
    // attempt window) survive ordinary edits.
    if (task == null || date != initial.date || time != initial.time) {
      body['timingMode'] = date.isNotEmpty ? 'deadline_only' : 'undated';
      body['dueDate'] = date.isNotEmpty && time.isEmpty ? date : null;
      body['dueAt'] = date.isNotEmpty && time.isNotEmpty ? utcTime('${date}T$time') : null;
      if (task != null) {
        body['startsAt'] = null;
        body['availabilityClosesAt'] = null;
      }
    }
    if (task != null) body['revision'] = task.revision;
    final services = AppScope.of(context);
    setState(() {
      pending = true;
      error = null;
      titleError = null;
    });
    try {
      await services.api.send(task != null ? 'PATCH' : 'POST', task != null ? '/tasks/${task.id}' : '/tasks', body: body);
      await services.queries.invalidate(['tasks', 'overview', 'task']);
      unawaited(services.notifier.refresh(services.api));
      if (mounted) {
        toast(context, task != null ? 'Task saved' : 'Task added');
        Navigator.pop(context);
      }
    } on ApiError catch (e) {
      error = e;
    }
    if (mounted) setState(() => pending = false);
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final api = AppScope.of(context).api;
    final today = todayKey();
    final quick = [
      ('Today', today),
      ('Tomorrow', addDays(today, 1)),
      ('In 3 days', addDays(today, 3)),
      ('Next week', addDays(today, 7)),
    ];
    return Scaffold(
      appBar: AppBar(
        leading: IconButton(icon: const Icon(Icons.close), tooltip: 'Cancel', onPressed: () => Navigator.pop(context)),
        title: Text(widget.task != null ? 'Edit task' : 'New task'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: FilledButton(
              style: FilledButton.styleFrom(minimumSize: const Size(72, 40)),
              onPressed: pending ? null : save,
              child: Text(pending ? 'Saving…' : 'Save'),
            ),
          ),
        ],
      ),
      body: QueryView(
        queryKey: Keys.subjects,
        fetch: () => loadSubjects(api),
        builder: (context, sq) => ListView(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 40),
          children: [
            TextField(
              controller: title,
              autofocus: widget.task == null,
              textCapitalization: TextCapitalization.sentences,
              maxLength: 300,
              style: display(context, 22, weight: FontWeight.w700),
              decoration: InputDecoration(
                hintText: 'What do you need to do?',
                errorText: titleError,
                counterText: '',
                filled: false,
                border: InputBorder.none,
                enabledBorder: InputBorder.none,
                focusedBorder: InputBorder.none,
                contentPadding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
              ),
            ),
            const SizedBox(height: 8),
            BubbleChoice<String>(
              value: type,
              options: const [('assignment', 'Assignment'), ('test', 'Test')],
              onChanged: (v) => setState(() => type = v),
            ),
            const SizedBox(height: 18),
            Field(
              label: 'Subject',
              child: SelectField<String>(
                value: subjectId,
                icon: DueIcons.subjects,
                title: 'Subject',
                options: [('', 'No subject'), for (final s in subjectsOf(sq)) (s.id, s.label)],
                onChanged: (v) => setState(() => subjectId = v),
              ),
            ),
            Field(
              label: 'Due',
              help: date.isEmpty ? 'No date yet? Leave it and add one when you know.' : (time.isEmpty ? 'Without a time it’s due by 23:59 IST.' : null),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Wrap(spacing: 8, runSpacing: 8, children: [
                    for (final (label, value) in quick)
                      ChoiceChip(label: Text(label), selected: date == value, onSelected: (_) => setState(() => date = date == value ? '' : value)),
                  ]),
                  const SizedBox(height: 10),
                  DateField(value: date, placeholder: 'Pick a date', onChanged: (v) => setState(() => date = v)),
                  const SizedBox(height: 8),
                  TimeField(value: time, enabled: date.isNotEmpty, placeholder: 'Add a time (optional)', onChanged: (v) => setState(() => time = v)),
                ],
              ),
            ),
            Field(
              label: 'Priority',
              help: priority.isEmpty ? 'Automatic: rises as the deadline gets closer.' : null,
              child: Wrap(spacing: 8, runSpacing: 8, children: [
                for (final (value, label) in const [('', 'Automatic'), ('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical')])
                  ChoiceChip(label: Text(label), selected: priority == value, onSelected: (_) => setState(() => priority = value)),
              ]),
            ),
            Field(
              label: 'Notes',
              child: TextField(controller: notes, minLines: 3, maxLines: 8, decoration: const InputDecoration(hintText: 'Anything to remember')),
            ),
            Text('All times are in IST.', style: TextStyle(color: c.graphite2, fontSize: 13)),
            ErrorNotice(error),
          ],
        ),
      ),
    );
  }
}
