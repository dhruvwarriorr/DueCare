import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/ist.dart';
import '../core/models.dart';
import '../core/query.dart';
import '../state/services.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'review.dart';
import 'sources.dart';
import 'workspace.dart';

/// New work, changes, and sync issues (apps/web activity.tsx).
class ActivityScreen extends StatefulWidget {
  const ActivityScreen({super.key});

  @override
  State<ActivityScreen> createState() => _ActivityScreenState();
}

class _ActivityScreenState extends State<ActivityScreen> {
  String filter = '';
  Object? error;

  Future<void> _run(Future<dynamic> Function() action) async {
    final services = AppScope.of(context);
    try {
      await action();
      await services.queries.invalidate(['activity']);
      if (mounted) setState(() => error = null);
    } on ApiError catch (e) {
      if (mounted) setState(() => error = e);
    }
  }

  void _open(ActivityItem item) {
    final api = AppScope.of(context).api;
    if (item.readAt == null) _run(() => api.send('PATCH', '/activity/${item.id}', body: {'read': true, 'revision': item.revision}));
    final Widget? target = switch (item.targetType) {
      'task' => null,
      'review' => ReviewScreen(targetId: item.targetId),
      _ => const SourcesScreen(),
    };
    if (item.targetType == 'task') {
      openTask(context, item.targetId);
    } else {
      Navigator.push(context, MaterialPageRoute(builder: (_) => target!));
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final api = AppScope.of(context).api;
    return Scaffold(
      appBar: AppBar(title: const Text('Activity')),
      body: QueryView(
        queryKey: ['activity', filter],
        poll: const Duration(seconds: 30),
        pager: (cursor) => api.get('/activity?${Uri(queryParameters: {
              if (filter.isNotEmpty) 'read': filter,
              'cursor': ?cursor,
            }).query}'),
        builder: (context, q) {
          final items = pageOf(q.data).items.map(ActivityItem.new).toList();
          final unread = q.data is Map ? ((q.data as Map)['unreadCount'] as num? ?? 0).toInt() : 0;
          return RefreshIndicator(
            onRefresh: q.refetch,
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
              children: [
                const SectionHeader(title: 'Activity', subtitle: 'New work, changes, and items that need your attention.'),
                Row(
                  children: [
                    Expanded(
                      child: SelectField<String>(
                        value: filter,
                        title: 'Show',
                        options: const [('', 'All activity'), ('false', 'Unread'), ('true', 'Read')],
                        onChanged: (v) => setState(() => filter = v),
                      ),
                    ),
                    if (unread > 0) ...[
                      const SizedBox(width: 8),
                      DueButton(
                        label: 'Mark all read',
                        icon: Icons.done_all,
                        variant: Variant.outline,
                        onPressed: () => _run(() => api.send('POST', '/activity/read-all')),
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 12),
                ErrorNotice(q.error ?? error, retry: q.refetch),
                if (q.isPending)
                  const Loading('Loading activity…')
                else if (items.isEmpty)
                  const EmptyState(
                    icon: Icons.notifications_none,
                    title: 'No activity here yet',
                    body: 'Updates will appear as you add work and sync sources.',
                  )
                else
                  Container(
                    decoration: BoxDecoration(border: Border.all(color: c.inkLine), color: c.sheet),
                    child: Column(
                      children: [
                        for (final item in items)
                          Container(
                            decoration: BoxDecoration(
                              color: item.readAt == null ? c.inkWash : null,
                              border: Border(bottom: BorderSide(color: c.inkRule)),
                            ),
                            padding: const EdgeInsets.fromLTRB(12, 12, 8, 6),
                            child: Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Icon(Icons.notifications_none, size: 18, color: item.readAt == null ? c.ink : c.graphite2),
                                const SizedBox(width: 10),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(item.message, style: TextStyle(fontWeight: item.readAt == null ? FontWeight.w600 : FontWeight.w400)),
                                      Text(
                                        '${formatTime(item.createdAt)} · ${item.readAt != null ? 'Read' : 'Unread'}',
                                        style: TextStyle(fontSize: 12.5, color: c.graphite2),
                                      ),
                                      Row(
                                        children: [
                                          DueButton(label: 'Open ↗', small: true, variant: Variant.ghost, onPressed: () => _open(item)),
                                          DueButton(
                                            label: item.readAt != null ? 'Mark unread' : 'Mark read',
                                            small: true,
                                            variant: Variant.ghost,
                                            onPressed: () => _run(() => api.send('PATCH', '/activity/${item.id}',
                                                body: {'read': item.readAt == null, 'revision': item.revision})),
                                          ),
                                        ],
                                      ),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                          ),
                      ],
                    ),
                  ),
                if (q.hasMore)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: DueButton(label: 'Load more activity', variant: Variant.outline, onPressed: q.fetchingMore ? null : q.loadMore),
                  ),
              ],
            ),
          );
        },
      ),
    );
  }
}
