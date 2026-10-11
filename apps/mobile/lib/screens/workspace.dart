import 'dart:async';

import 'package:flutter/material.dart';

import '../app.dart';
import '../core/api.dart';
import '../core/models.dart';
import '../core/query.dart';
import '../state/data.dart';
import '../state/services.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'activity.dart';
import 'more.dart';
import 'review.dart';
import 'settings.dart';
import 'task_detail.dart';
import 'task_editor.dart';
import 'tasks.dart';
import 'week.dart';

/// The signed-in app: onboarding until the academic profile is complete, then the shell.
class Workspace extends StatelessWidget {
  const Workspace({super.key, required this.savedAt, required this.onTheme});

  final DateTime? savedAt;
  final ValueChanged<String> onTheme;

  @override
  Widget build(BuildContext context) {
    final api = AppScope.of(context).api;
    return QueryView(
      queryKey: Keys.me,
      fetch: () => api.get('/me'),
      builder: (context, q) {
        final p = profileOf(q);
        if (p != null) WidgetsBinding.instance.addPostFrameCallback((_) => onTheme(p.theme));
        if (p == null) {
          return Scaffold(
            body: SafeArea(
              child: Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Logo(size: 34),
                      const SizedBox(height: 24),
                      if (q.error == null) const Loading('Opening your workspace…') else ErrorNotice(q.error, retry: q.refetch),
                    ],
                  ),
                ),
              ),
            ),
          );
        }
        if (!p.onboardingComplete) return Onboarding(profile: p);
        return Shell(profile: p, savedAt: savedAt);
      },
    );
  }
}

class Shell extends StatefulWidget {
  const Shell({super.key, required this.profile, required this.savedAt});

  final Profile profile;
  final DateTime? savedAt;

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> with WidgetsBindingObserver {
  int tab = 0;
  // Tabs build when first opened, then keep their state.
  final Set<int> opened = {0};
  String taskStatus = '';
  int taskListGeneration = 0;
  Timer? _watch;
  String? _version;
  bool reachable = true;

  Services get services => AppScope.of(context);

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) => _start());
  }

  Future<void> _start() async {
    final s = services;
    s.reminders.onOpenTask = (id) => openTask(navigatorKey.currentContext ?? context, id);
    final launch = s.reminders.takeLaunchTask();
    if (launch != null && mounted) openTask(context, launch);
    unawaited(s.sync.start());
    _watch = Timer.periodic(const Duration(seconds: 20), (_) => _checkChanges());
    await _checkChanges();
    await s.reminders.askOnce();
    await s.reminders.refresh(s.api);
  }

  /// Poll a tiny change stamp; reload data only when it moves (apps/web/src/lib/offline.tsx).
  Future<void> _checkChanges() async {
    final s = services;
    try {
      final stamp = (await s.api.get('/changes')) as Map;
      final version = stamp['version'] as String;
      if (_version != null && _version != version) {
        await s.queries.invalidate(reloadRoots);
        unawaited(s.reminders.refresh(s.api));
      }
      _version = version;
      if (!reachable && mounted) setState(() => reachable = true);
    } on ApiError catch (e) {
      // Only a failed connection means the server is unreachable; an error answer is a reply.
      if (e.unreachable && reachable && mounted) setState(() => reachable = false);
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      unawaited(_checkChanges());
      // Refresh progress on return; the worker continues while the app is in the background.
      unawaited(services.sync.start(trigger: 'focus'));
    }
  }

  @override
  void dispose() {
    _watch?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  void go(int index, {String status = ''}) {
    setState(() {
      tab = index;
      opened.add(index);
      if (index == 1) {
        taskStatus = status;
        taskListGeneration++;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final api = services.api;
    final p = widget.profile;
    final pages = [
      WeekScreen(onTasks: (s) => go(1, status: s), onReview: () => go(2)),
      TasksScreen(key: ValueKey(taskListGeneration), initialStatus: taskStatus, batch: p.generalBatch),
      const ReviewScreen(),
      MoreScreen(profile: p),
    ];
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 16,
        title: const Logo(size: 26),
        actions: [
          QueryView(
            queryKey: Keys.activityCount,
            fetch: () => api.get('/activity?limit=1'),
            builder: (context, q) {
              final unread = q.data is Map ? ((q.data as Map)['unreadCount'] as num? ?? 0).toInt() : 0;
              return IconButton(
                tooltip: 'Activity${unread > 0 ? ', $unread unread' : ''}',
                onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ActivityScreen())),
                icon: Badge(
                  isLabelVisible: unread > 0,
                  backgroundColor: c.bad,
                  textColor: c.onBad,
                  label: Text(unread > 99 ? '99+' : '$unread'),
                  child: const Icon(Icons.notifications_none),
                ),
              );
            },
          ),
          const SizedBox(width: 6),
        ],
      ),
      body: Column(
        children: [
          if (!reachable) OfflineBanner(savedAt: widget.savedAt),
          Expanded(
            child: IndexedStack(
              index: tab,
              children: [for (final (i, page) in pages.indexed) opened.contains(i) ? page : const SizedBox.shrink()],
            ),
          ),
        ],
      ),
      bottomNavigationBar: _BottomBar(
        tab: tab,
        onTab: go,
        onAdd: () => openEditor(context),
      ),
    );
  }
}

/// The fixed bottom bar: Week, Tasks, a graphite add button, Review, More.
class _BottomBar extends StatelessWidget {
  const _BottomBar({required this.tab, required this.onTab, required this.onAdd});

  final int tab;
  final ValueChanged<int> onTab;
  final VoidCallback onAdd;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final api = AppScope.of(context).api;
    Widget item(int index, String label, {Widget? badge}) => Expanded(
          child: InkWell(
            onTap: () => onTab(index),
            child: Container(
              height: 60,
              decoration: BoxDecoration(
                border: Border(top: BorderSide(color: tab == index ? c.graphite : Colors.transparent, width: 4)),
              ),
              alignment: Alignment.center,
              padding: const EdgeInsets.symmetric(horizontal: 4),
              // Large text settings shrink the label rather than clip it.
              child: FittedBox(
                fit: BoxFit.scaleDown,
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(label, style: TextStyle(fontSize: 15, fontWeight: tab == index ? FontWeight.w700 : FontWeight.w500)),
                    ?badge,
                  ],
                ),
              ),
            ),
          ),
        );
    return Container(
      decoration: BoxDecoration(color: c.sheet, border: Border(top: BorderSide(color: c.graphite))),
      child: SafeArea(
        top: false,
        child: Row(
          children: [
            item(0, 'Week'),
            item(1, 'Tasks'),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 6),
              child: Semantics(
                button: true,
                label: 'Add task',
                child: Material(
                  color: c.graphite,
                  child: InkWell(
                    onTap: onAdd,
                    child: SizedBox(width: 52, height: 44, child: Icon(Icons.add, color: c.onGraphite)),
                  ),
                ),
              ),
            ),
            item(
              2,
              'Review',
              badge: QueryView(
                queryKey: Keys.overview,
                fetch: () => api.get('/overview'),
                builder: (context, q) {
                  final count = q.data is Map ? ((q.data as Map)['reviewCount'] as num? ?? 0).toInt() : 0;
                  if (count == 0) return const SizedBox.shrink();
                  return Container(
                    margin: const EdgeInsets.only(left: 6),
                    padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                    color: c.bad,
                    child: Text('$count', style: display(context, 12, color: c.onBad)),
                  );
                },
              ),
            ),
            item(3, 'More'),
          ],
        ),
      ),
    );
  }
}

void openTask(BuildContext context, String id) =>
    Navigator.push(context, MaterialPageRoute(builder: (_) => TaskDetailScreen(id: id)));

void openEditor(BuildContext context, [Task? task]) => Navigator.push(
      context,
      MaterialPageRoute(fullscreenDialog: true, builder: (_) => TaskEditorScreen(task: task)),
    );
