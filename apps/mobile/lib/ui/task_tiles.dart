import 'package:flutter/material.dart';

import '../core/deadline.dart';
import '../core/models.dart';
import '../state/quick_complete.dart';
import 'theme.dart';
import 'widgets.dart';

/// A task as a card: the done bubble, title with a priority flag, its subject line, when it is
/// due and its status.
class TaskRow extends StatelessWidget {
  const TaskRow({super.key, required this.task, required this.onOpen, this.selected, this.onToggle, this.onLongPress});

  final Task task;
  final VoidCallback onOpen;

  /// When set, rows are chosen for a bulk action instead of opened.
  final bool? selected;
  final VoidCallback? onToggle;
  final VoidCallback? onLongPress;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final t = task;
    final d = deadline(t);
    final flag = t.status == 'due' && (t.priority == 'critical' || t.priority == 'high');
    final selecting = selected != null;
    return Material(
      color: selected == true ? c.inkTint : c.sheet,
      borderRadius: BorderRadius.circular(Radii.card),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: selecting ? onToggle : onOpen,
        onLongPress: onLongPress,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(4, 12, 16, 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (selecting)
                SizedBox(width: 48, height: 40, child: Checkbox(value: selected, onChanged: (_) => onToggle?.call()))
              else
                DoneButton(task: t),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: Text(
                            t.title,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              fontWeight: FontWeight.w700,
                              fontSize: 16,
                              height: 1.3,
                              color: t.status == 'completed' ? c.graphite2 : (t.status == 'missed' ? c.badText : c.graphite),
                              decoration: t.status == 'missed' ? TextDecoration.lineThrough : null,
                              decorationColor: c.bad,
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        StatusPill(t.status),
                      ],
                    ),
                    const SizedBox(height: 3),
                    Text(taskSubline(t), style: TextStyle(color: c.graphite2, fontSize: 13.5)),
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        Icon(t.dueAt == null ? Icons.event_busy_outlined : Icons.schedule_rounded, size: 16, color: c.ink),
                        const SizedBox(width: 6),
                        Flexible(
                          child: Text.rich(
                            TextSpan(children: [
                              TextSpan(text: d.main, style: display(context, 14.5, weight: FontWeight.w700)),
                              if (d.note != null) TextSpan(text: '  ${d.note}', style: TextStyle(color: c.graphite2, fontSize: 12.5)),
                            ]),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        if (flag) ...[
                          const SizedBox(width: 8),
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                            decoration: BoxDecoration(color: c.dueTint, borderRadius: BorderRadius.circular(6)),
                            child: Text(t.priority.toUpperCase(), style: printed(context, color: c.dueText, size: 10.5)),
                          ),
                        ],
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

/// A deadline in the day's agenda: a rounded card edged in its status colour.
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
      _ => (c.dueTint, c.due, c.graphite),
    };
    final word = switch (t.status) {
      'missed' => 'missed',
      'completed' => 'done',
      _ => null,
    };
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: bg,
        borderRadius: BorderRadius.circular(Radii.medium),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onOpen,
          child: IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Container(width: 5, color: line),
                if (t.status == 'completed')
                  SizedBox(
                    width: 44,
                    child: Center(child: Bubble(small: true, fill: c.good, stroke: c.good, child: Icon(Icons.check, size: 10, color: c.onGood))),
                  )
                else
                  DoneButton(task: t, compact: true),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(0, 11, 12, 11),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Text(
                          t.title,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontWeight: FontWeight.w700,
                            fontSize: 15,
                            color: fg,
                            decoration: t.status == 'missed' ? TextDecoration.lineThrough : null,
                            decorationColor: c.bad,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text.rich(
                          TextSpan(
                            style: TextStyle(fontSize: 13, color: c.graphite2),
                            children: [
                              TextSpan(text: dueClock(t), style: display(context, 13, weight: FontWeight.w700, color: c.graphite)),
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
        ),
      ),
    );
  }
}
