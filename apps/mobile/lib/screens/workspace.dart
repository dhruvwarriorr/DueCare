import 'dart:async';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../app.dart';
import '../core/api.dart';
import '../core/models.dart';
import '../core/query.dart';
import '../notifications/planner.dart' as planner;
import '../notifications/prefs.dart';
import '../state/data.dart';
import '../state/services.dart';
import '../ui/icons.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'activity.dart';
import 'more.dart';
import 'review.dart';
import 'settings.dart';
import 'sources.dart';
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
            body: Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Logo(size: 40),
                    const SizedBox(height: 28),
                    if (q.error == null) const Loading('Opening your workspace…') else ErrorNotice(q.error, retry: q.refetch),
                  ],
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
  State<Shell> createState() => ShellState();
}

class ShellState extends State<Shell> with WidgetsBindingObserver {
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
    s.notifier.onTap = (payload) => openPayload(payload);
    final launch = s.notifier.takeLaunch();
    if (launch != null && mounted) openPayload(launch);
    unawaited(s.sync.start());
    _watch = Timer.periodic(const Duration(seconds: 20), (_) => _checkChanges());
    await _checkChanges();
    await _notifications();
  }

  /// Start notifying for this account: its choices, permission (asked once), push and reminders.
  Future<void> _notifications() async {
    final s = services;
    try {
      await s.notifier.begin(widget.profile.id);
      NotifyPrefs prefs;
      try {
        prefs = await s.loadNotifyPrefs();
      } on ApiError {
        prefs = await NotifyPrefs.load();
      }
      final store = await SharedPreferences.getInstance();
      if (!(store.getBool('duecare.notify.asked') ?? false)) {
        await store.setBool('duecare.notify.asked', true);
        if (!s.push.available) await s.notifier.requestPermission();
      }
      await s.push.register(s.api, onPush: () => s.queries.invalidate(reloadRoots));
      await s.notifier.refresh(s.api, prefs: prefs);
    } catch (e) {
      debugPrint('Notifications unavailable: ${e.runtimeType}');
    }
  }

  /// Open what a notification is about.
  void openPayload(String? payload) {
    final nav = navigatorKey.currentState;
    if (nav == null || !mounted) return;
    final r = planner.route(payload);
    switch (r.kind) {
      case 'task' when r.id != null:
        nav.push(MaterialPageRoute(builder: (_) => TaskDetailScreen(id: r.id!)));
      case 'review' when r.id != null:
        nav.push(MaterialPageRoute(builder: (_) => ReviewScreen(targetId: r.id)));
      case 'sources':
        nav.push(MaterialPageRoute(builder: (_) => const SourcesScreen()));
      default:
        nav.popUntil((route) => route.isFirst);
        go(0);
    }
  }

  /// Poll a tiny change stamp; reload data only when it moves (apps/web/src/lib/offline.tsx).
  Future<void> _checkChanges() async {
    final s = services;
    try {
      final stamp = (await s.api.get('/changes')) as Map;
      final version = stamp['version'] as String;
      if (_version != null && _version != version) {
        await s.queries.invalidate(reloadRoots);
        unawaited(s.notifier.refresh(s.api));
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

  void go(int index, {String? status}) {
    setState(() {
      tab = index;
      opened.add(index);
      if (index == 1 && status != null) {
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
      WeekScreen(profile: p, onTasks: (s) => go(1, status: s), onReview: () => go(2)),
      TasksScreen(key: ValueKey(taskListGeneration), initialStatus: taskStatus, batch: p.generalBatch),
      const ReviewScreen(),
      MoreScreen(profile: p),
    ];
    return Scaffold(
      body: Column(
        children: [
          Expanded(
            child: IndexedStack(
              index: tab,
              children: [for (final (i, page) in pages.indexed) opened.contains(i) ? page : const SizedBox.shrink()],
            ),
          ),
          if (!reachable) OfflineBanner(savedAt: widget.savedAt),
        ],
      ),
      bottomNavigationBar: QueryView(
        queryKey: Keys.overview,
        fetch: () => api.get('/overview'),
        builder: (context, q) {
          final review = q.data is Map ? ((q.data as Map)['reviewCount'] as num? ?? 0).toInt() : 0;
          return DecoratedBox(
            decoration: BoxDecoration(border: Border(top: BorderSide(color: c.inkRule))),
            child: NavigationBar(
              selectedIndex: tab,
              onDestinationSelected: go,
              destinations: [
                const NavigationDestination(icon: DueIcon(DueIcons.week), selectedIcon: DueIcon(DueIcons.week, filled: true), label: 'Week'),
                const NavigationDestination(icon: DueIcon(DueIcons.tasks), selectedIcon: DueIcon(DueIcons.tasks, filled: true), label: 'Tasks'),
                NavigationDestination(
                  icon: Badge(isLabelVisible: review > 0, label: Text('$review'), child: const DueIcon(DueIcons.review)),
                  selectedIcon: Badge(isLabelVisible: review > 0, label: Text('$review'), child: const DueIcon(DueIcons.review, filled: true)),
                  label: 'Review',
                ),
                const NavigationDestination(icon: DueIcon(DueIcons.more), selectedIcon: DueIcon(DueIcons.more, filled: true), label: 'More'),
              ],
            ),
          );
        },
      ),
    );
  }
}

/// The bell in a page's app bar, with the unread count.
class ActivityBell extends StatelessWidget {
  const ActivityBell({super.key});

  @override
  Widget build(BuildContext context) {
    final api = AppScope.of(context).api;
    return QueryView(
      queryKey: Keys.activityCount,
      fetch: () => api.get('/activity?limit=1'),
      builder: (context, q) {
        final unread = q.data is Map ? ((q.data as Map)['unreadCount'] as num? ?? 0).toInt() : 0;
        return IconButton(
          tooltip: 'Activity${unread > 0 ? ', $unread unread' : ''}',
          onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ActivityScreen())),
          icon: Badge(isLabelVisible: unread > 0, label: Text(unread > 99 ? '99+' : '$unread'), child: const DueIcon(DueIcons.activity)),
        );
      },
    );
  }
}

void openTask(BuildContext context, String id) =>
    Navigator.push(context, MaterialPageRoute(builder: (_) => TaskDetailScreen(id: id)));

void openEditor(BuildContext context, [Task? task]) => Navigator.push(
      context,
      MaterialPageRoute(fullscreenDialog: true, builder: (_) => TaskEditorScreen(task: task)),
    );
