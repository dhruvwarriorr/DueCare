import 'dart:async';

import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/ist.dart';
import '../core/models.dart';
import '../core/query.dart';
import '../state/data.dart';
import '../state/services.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

/// Add or edit a task. Only a title is required; the deadline is an IST date and an optional
/// time (apps/web task-editor.tsx).
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
      setState(() => titleError = 'Add a title');
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
      unawaited(services.reminders.refresh(services.api));
      if (mounted) Navigator.pop(context);
    } on ApiError catch (e) {
      error = e;
    }
    if (mounted) setState(() => pending = false);
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final api = AppScope.of(context).api;
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.task != null ? 'Edit task' : 'Add a task'),
        leading: IconButton(icon: const Icon(Icons.close), tooltip: 'Cancel', onPressed: () => Navigator.pop(context)),
      ),
      bottomNavigationBar: Container(
        decoration: BoxDecoration(color: c.sheet, border: Border(top: BorderSide(color: c.graphite))),
        padding: const EdgeInsets.all(12),
        child: SafeArea(
          top: false,
          child: Row(spacing: 8, children: [
            DueButton(label: 'Cancel', variant: Variant.outline, onPressed: () => Navigator.pop(context)),
            Expanded(child: DueButton(label: pending ? 'Saving…' : 'Save task', expand: true, onPressed: pending ? null : save)),
          ]),
        ),
      ),
      body: QueryView(
        queryKey: Keys.subjects,
        fetch: () => loadSubjects(api),
        builder: (context, sq) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text('Only a title is required. All times use IST.', style: TextStyle(color: c.graphite2)),
            const SizedBox(height: 16),
            Field(
              label: 'Title',
              error: titleError,
              child: TextField(controller: title, autofocus: widget.task == null, textCapitalization: TextCapitalization.sentences, maxLength: 300),
            ),
            Field(
              label: 'Type',
              child: BubbleChoice<String>(
                value: type,
                options: const [('assignment', 'Assignment'), ('test', 'Test')],
                onChanged: (v) => setState(() => type = v),
              ),
            ),
            Field(
              label: 'Subject',
              child: SelectField<String>(
                value: subjectId,
                title: 'Subject',
                options: [('', 'No subject'), for (final s in subjectsOf(sq)) (s.id, s.label)],
                onChanged: (v) => setState(() => subjectId = v),
              ),
            ),
            Field(label: 'Deadline date', child: DateField(value: date, onChanged: (v) => setState(() => date = v))),
            Field(
              label: 'Deadline time (optional)',
              help: date.isNotEmpty ? 'Without a time, it’s due by 23:59 IST that day.' : 'No date yet? Leave it blank and add it when you know.',
              child: TimeField(value: time, enabled: date.isNotEmpty, onChanged: (v) => setState(() => time = v)),
            ),
            Field(
              label: 'Priority',
              child: SelectField<String>(
                value: priority,
                title: 'Priority',
                options: const [('', 'Based on deadline'), ('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical')],
                onChanged: (v) => setState(() => priority = v),
              ),
            ),
            Field(label: 'Personal notes', child: TextField(controller: notes, minLines: 2, maxLines: 6)),
            ErrorNotice(error),
          ],
        ),
      ),
    );
  }
}
