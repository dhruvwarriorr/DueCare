import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/ist.dart';
import '../core/models.dart';
import '../core/query.dart';
import '../state/services.dart';
import '../ui/icons.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'review.dart';
import 'sources.dart';
import 'workspace.dart';

const _icons = {
  'new_task': DueIcons.add,
  'revision': DueIcons.event,
  'reopened': DueIcons.reopen,
  'review': DueIcons.review,
  'auto_completed': DueIcons.done,
  'sync_issue': DueIcons.sources,
};

/// New work, changes and sync issues, newest first.
class ActivityScreen extends StatefulWidget {
  const ActivityScreen({super.key});

  @override
  State<ActivityScreen> createState() => _ActivityScreenState();
}

class _ActivityScreenState extends State<ActivityScreen> {
  String filter = '';

  Future<void> _run(Future<dynamic> Function() action) async {
    final services = AppScope.of(context);
    try {
      await action();
      await services.queries.invalidate(['activity']);
    } on ApiError catch (e) {
      if (mounted) toast(context, e.message);
    }
  }

  void _open(ActivityItem item) {
    final api = AppScope.of(context).api;
    if (item.readAt == null) _run(() => api.send('PATCH', '/activity/${item.id}', body: {'read': true, 'revision': item.revision}));
    switch (item.targetType) {
      case 'task':
        openTask(context, item.targetId);
      case 'review':
        Navigator.push(context, MaterialPageRoute(builder: (_) => ReviewScreen(targetId: item.targetId)));
      default:
        Navigator.push(context, MaterialPageRoute(builder: (_) => const SourcesScreen()));
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final api = AppScope.of(context).api;
    return QueryView(
      queryKey: ['activity', filter],
      poll: const Duration(seconds: 30),
      pager: (cursor) => api.get('/activity?${Uri(queryParameters: {
            if (filter.isNotEmpty) 'read': filter,
            'cursor': ?cursor,
          }).query}'),
      builder: (context, q) {
        final items = pageOf(q.data).items.map(ActivityItem.new).toList();
        final unread = q.data is Map ? ((q.data as Map)['unreadCount'] as num? ?? 0).toInt() : 0;
        return PageScaffold(
          title: 'Activity',
          onRefresh: q.refetch,
          actions: [
            if (unread > 0)
              IconButton(tooltip: 'Mark all as read', icon: const DueIcon(DueIcons.done), onPressed: () => _run(() => api.send('POST', '/activity/read-all'))),
          ],
          children: [
            Wrap(spacing: 8, children: [
              for (final (value, label) in [('', 'All'), ('false', 'Unread${unread > 0 ? ' ($unread)' : ''}'), ('true', 'Read')])
                ChoiceChip(label: Text(label), selected: filter == value, onSelected: (_) => setState(() => filter = value)),
            ]),
            const SizedBox(height: 12),
            ErrorNotice(q.error, retry: q.refetch),
            if (q.isPending)
              const Loading('Loading activity…')
            else if (items.isEmpty)
              const EmptyState(icon: DueIcons.activity, title: 'Nothing here yet', body: 'Updates appear as you add work and sources sync.')
            else
              for (final item in items)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Dismissible(
                    key: ValueKey('activity-${item.id}-${item.readAt}'),
                    direction: DismissDirection.horizontal,
                    background: Container(
                      decoration: BoxDecoration(color: c.inkTint, borderRadius: BorderRadius.circular(Radii.card)),
                      alignment: Alignment.centerLeft,
                      padding: const EdgeInsets.symmetric(horizontal: 22),
                      child: Text(item.readAt == null ? 'Mark read' : 'Mark unread', style: const TextStyle(fontWeight: FontWeight.w800)),
                    ),
                    confirmDismiss: (_) async {
                      await _run(() => api.send('PATCH', '/activity/${item.id}', body: {'read': item.readAt == null, 'revision': item.revision}));
                      return false;
                    },
                    child: Material(
                      color: item.readAt == null ? c.sheet : c.sheet.withValues(alpha: 0.55),
                      borderRadius: BorderRadius.circular(Radii.card),
                      clipBehavior: Clip.antiAlias,
                      child: InkWell(
                        onTap: () => _open(item),
                        child: Padding(
                          padding: const EdgeInsets.all(14),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Container(
                                width: 40,
                                height: 40,
                                decoration: BoxDecoration(color: item.readAt == null ? c.inkTint : c.inkWash, borderRadius: BorderRadius.circular(12)),
                                child: glyph(_icons[item.json['eventType']] ?? DueIcons.activity, color: c.ink, size: 21),
                              ),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      item.message,
                                      style: TextStyle(fontWeight: item.readAt == null ? FontWeight.w700 : FontWeight.w500, height: 1.35),
                                    ),
                                    const SizedBox(height: 4),
                                    Text(formatTime(item.createdAt), style: TextStyle(fontSize: 12.5, color: c.graphite2)),
                                  ],
                                ),
                              ),
                              if (item.readAt == null)
                                Container(width: 9, height: 9, margin: const EdgeInsets.only(top: 6, left: 8), decoration: BoxDecoration(color: c.ink, shape: BoxShape.circle)),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
            if (q.hasMore)
              Center(child: TextButton(onPressed: q.fetchingMore ? null : q.loadMore, child: const Text('Show older'))),
          ],
        );
      },
    );
  }
}
