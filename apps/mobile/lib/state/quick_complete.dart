import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/models.dart';
import '../ui/widgets.dart';
import 'data.dart';
import 'services.dart';

/// One-tap "mark done" from any list, with Undo (apps/web/src/lib/quick-complete.tsx). The
/// bubble fills at once; the row changes when the saved answer arrives.
class QuickComplete extends ChangeNotifier {
  final Set<String> _pending = {};

  bool pending(String id) => _pending.contains(id);

  Future<void> complete(BuildContext context, Task task) async {
    final services = AppScope.of(context);
    final messenger = ScaffoldMessenger.of(context);
    _pending.add(task.id);
    notifyListeners();
    try {
      final saved = Task((await services.api.send('PATCH', '/tasks/${task.id}', body: {
        'revision': task.revision,
        'status': 'completed',
      })) as Map<String, dynamic>);
      await services.queries.invalidate(taskRoots);
      messenger
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(
          content: Text('Marked done: ${saved.title}'),
          duration: const Duration(seconds: 6),
          action: SnackBarAction(label: 'Undo', onPressed: () => _undo(services, messenger, saved)),
        ));
    } on ApiError catch (e) {
      messenger
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text('Couldn’t mark “${task.title}” done. ${e.message}')));
    } finally {
      _pending.remove(task.id);
      notifyListeners();
    }
  }

  Future<void> _undo(Services services, ScaffoldMessengerState messenger, Task task) async {
    try {
      await services.api.send('PATCH', '/tasks/${task.id}', body: {'revision': task.revision, 'status': 'due'});
      await services.queries.invalidate(taskRoots);
    } on ApiError catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.message)));
    }
  }
}

class QuickCompleteScope extends InheritedNotifier<QuickComplete> {
  const QuickCompleteScope({super.key, required QuickComplete super.notifier, required super.child});

  static QuickComplete of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<QuickCompleteScope>()!.notifier!;
}

/// The bubble that marks a task done.
class DoneButton extends StatelessWidget {
  const DoneButton({super.key, required this.task, this.compact = false});

  final Task task;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final quick = QuickCompleteScope.of(context);
    final c = statusColors(context, 'completed');
    final busy = quick.pending(task.id);
    if (task.status == 'completed') return SizedBox(width: compact ? 32 : 44);
    return Semantics(
      button: true,
      label: 'Mark done: ${task.title}',
      child: InkWell(
        onTap: busy ? null : () => quick.complete(context, task),
        child: SizedBox(
          width: compact ? 32 : 44,
          height: 44,
          child: Center(
            child: Bubble(
              small: compact,
              fill: busy ? c.bg : null,
              stroke: busy ? c.line : null,
              child: busy ? Icon(Icons.check, size: compact ? 8 : 10, color: c.fg) : null,
            ),
          ),
        ),
      ),
    );
  }
}
