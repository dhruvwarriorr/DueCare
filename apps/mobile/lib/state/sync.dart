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

  bool get busy => driving.isNotEmpty || connections.any((c) => c.activeJob != null);

  Future<void> _load() async {
    try {
      final data = await queries.fetch(Keys.connections, () => api.get('/connections'));
      connections = pageOf(data).items.map(Connection.new).toList();
      error = null;
    } catch (e) {
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
    _started = true;
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
    _poll?.cancel();
    _poll = null;
    _started = false;
    connections = const [];
    loaded = false;
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }
}
