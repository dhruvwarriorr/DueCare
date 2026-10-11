import 'package:flutter/material.dart';

import '../core/deadline.dart';
import '../core/models.dart';
import '../state/quick_complete.dart';
import 'theme.dart';
import 'widgets.dart';

/// A task row: done bubble, title (with a priority flag for urgent due work), subline, the
/// deadline in tabular numerals and the status pill (DESIGN.md › Task Rows).
class TaskRow extends StatelessWidget {
  const TaskRow({super.key, required this.task, required this.onOpen, this.selected, this.onToggle});

  final Task task;
  final VoidCallback onOpen;

  /// When set, rows are chosen for a bulk action instead of opened.
  final bool? selected;
  final VoidCallback? onToggle;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final t = task;
    final d = deadline(t);
    final flag = t.status == 'due' && (t.priority == 'critical' || t.priority == 'high');
    final selecting = selected != null;
    return Material(
      color: selected == true ? c.inkTint : c.sheet,
      child: InkWell(
        onTap: selecting ? onToggle : onOpen,
        child: Container(
          decoration: BoxDecoration(border: Border(bottom: BorderSide(color: c.inkRule))),
          padding: const EdgeInsets.fromLTRB(4, 10, 14, 10),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (selecting)
                SizedBox(width: 44, height: 44, child: Checkbox(value: selected, onChanged: (_) => onToggle?.call()))
              else
                DoneButton(task: t),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text.rich(
                      TextSpan(children: [
                        TextSpan(
                          text: t.title,
                          style: TextStyle(
                            fontWeight: FontWeight.w600,
                            fontSize: 15,
                            color: t.status == 'completed' ? c.graphite2 : (t.status == 'missed' ? c.badText : c.graphite),
                            decoration: t.status == 'missed' ? TextDecoration.lineThrough : null,
                            decorationColor: c.bad,
                          ),
                        ),
                        if (flag) ...[
                          const TextSpan(text: '  '),
                          TextSpan(text: t.priority.toUpperCase(), style: printed(context, color: c.dueText, size: 11)),
                        ],
                      ]),
                    ),
                    const SizedBox(height: 2),
                    Text(taskSubline(t), style: TextStyle(color: c.graphite2, fontSize: 13)),
                    const SizedBox(height: 6),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(d.main, style: display(context, 15, weight: FontWeight.w600)),
                              if (d.note != null) Text(d.note!, style: TextStyle(color: c.graphite2, fontSize: 12)),
                            ],
                          ),
                        ),
                        StatusPill(t.status),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The unit of the week's Due row and the day agenda (DESIGN.md › Due Items).
class DueItem extends StatelessWidget {
  const DueItem({super.key, required this.task, required this.onOpen, this.detail = true});

  final Task task;
  final VoidCallback onOpen;
  final bool detail;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final t = task;
    final (bg, line, fg) = switch (t.status) {
      'completed' => (c.goodTint, c.good, c.graphite),
      'missed' => (c.badTint, c.bad, c.badText),
      _ => (c.dueTint, c.dueLine, c.graphite),
    };
    final word = switch (t.status) {
      'missed' => 'missed',
      'completed' => 'done',
      _ => null,
    };
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      decoration: BoxDecoration(color: bg, border: Border.all(color: line)),
      child: InkWell(
        onTap: onOpen,
        child: Row(
          children: [
            if (t.status == 'completed')
              SizedBox(width: 32, height: 44, child: Center(child: Bubble(small: true, fill: c.good, stroke: c.good, child: Icon(Icons.check, size: 8, color: c.onGood))))
            else
              DoneButton(task: t, compact: true),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(0, 8, 10, 8),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      t.title,
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontWeight: FontWeight.w600,
                        fontSize: 14,
                        color: fg,
                        decoration: t.status == 'missed' ? TextDecoration.lineThrough : null,
                        decorationColor: c.bad,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text.rich(
                      TextSpan(
                        style: display(context, 12.5, weight: FontWeight.w500, color: c.graphite2),
                        children: [
                          TextSpan(text: dueClock(t)),
                          if (detail) TextSpan(text: ' · ${t.isTest ? 'Test' : 'Assignment'}${t.subjectName != null ? ' · ${t.subjectName}' : ''}'),
                          if (word != null) TextSpan(text: ' · $word', style: TextStyle(fontWeight: FontWeight.w800, color: fg)),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
