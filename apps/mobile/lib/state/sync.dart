import 'dart:async';

import 'package:flutter/foundation.dart';

import '../core/api.dart';
import '../core/models.dart';
import '../core/query.dart';
import 'data.dart';

/// Starts and follows Gmail/Classroom syncs (apps/web/src/lib/sync.tsx). The API's worker does
/// the work; the app only enqueues jobs on open, on return and on request, and watches progress.
class SyncController extends ChangeNotifier {
  SyncController(this.api, this.queries);

  final Api api;
  final QueryClient queries;
  final Set<String> driving = {};
  final Map<String, ApiError> failures = {};
  List<Connection> connections = const [];
  Object? error;
  bool loaded = false;
  Timer? _poll;
  bool _started = false;
  DateTime? _lastStart;
  // Bumped on sign-out, so an answer that arrives afterwards cannot restart polling.
  int _epoch = 0;
  // Like the web: returning to the app syncs again only after a while away.
  static const _refocus = Duration(minutes: 15);

  bool get busy => driving.isNotEmpty || connections.any((c) => c.activeJob != null);

  Future<void> _load() async {
    final epoch = _epoch;
    try {
      final data = await queries.fetch(Keys.connections, () => api.get('/connections'));
      if (epoch != _epoch) return;
      connections = pageOf(data).items.map(Connection.new).toList();
      error = null;
    } catch (e) {
      if (epoch != _epoch) return;
      error = e;
    }
    loaded = true;
    _schedule();
    notifyListeners();
  }

  /// While a job runs, refresh progress and the committed tasks every five seconds.
  void _schedule() {
    if (busy && _poll == null) {
      _poll = Timer.periodic(const Duration(seconds: 5), (_) async {
        await queries.invalidate(syncRoots.where((r) => r != 'connections'));
        await _load();
      });
    } else if (!busy) {
      _poll?.cancel();
      _poll = null;
    }
  }

  /// Opening the app syncs each active source once; returning to it syncs again.
  Future<void> start({String trigger = 'open'}) async {
    if (trigger == 'open' && _started) return;
    final last = _lastStart;
    if (trigger == 'focus' && last != null && DateTime.now().difference(last) < _refocus) {
      await _load(); // Still refresh progress on return.
      return;
    }
    _started = true;
    _lastStart = DateTime.now();
    await _load();
    for (final c in connections) {
      if (c.status == 'active' && c.privacyJobId == null && c.activeJob == null) unawaited(_drive(c.id, trigger));
    }
  }

  void syncNow(String id) => unawaited(_drive(id, 'manual'));

  Future<void> _drive(String id, String trigger) async {
    if (driving.contains(id)) return;
    driving.add(id);
    failures.remove(id);
    notifyListeners();
    try {
      await api.send('POST', '/connections/$id/sync', body: {'trigger': trigger});
    } on ApiError catch (e) {
      failures[id] = e;
    } finally {
      driving.remove(id);
      await queries.invalidate(syncRoots);
      await _load();
    }
  }

  Future<void> reprocess(String id) async {
    await api.send('POST', '/connections/$id/reprocess');
    await queries.invalidate(syncRoots);
    await _load();
  }

  Future<void> refresh() => _load();

  void stop() {
    _epoch++;
    _poll?.cancel();
    _poll = null;
    _started = false;
    _lastStart = null;
    driving.clear();
    failures.clear();
    connections = const [];
    loaded = false;
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }
}
