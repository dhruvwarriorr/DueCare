import 'dart:async';
import 'dart:convert';

import 'package:flutter/widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';

typedef Fetcher = Future<dynamic> Function();
typedef Pager = Future<dynamic> Function(String? cursor);

/// One cached server answer, keyed like the web app's TanStack queries: ['tasks', 'week', monday].
class Query extends ChangeNotifier {
  Query._(this.key, this.id);

  final List<Object?> key;
  final String id;
  Fetcher? _fetch;
  Pager? _pager;
  dynamic data;
  Object? error;
  DateTime? updatedAt;
  bool fetching = false;
  bool fetchingMore = false;
  bool _stale = true;
  Future<void>? _inflight;
  int _users = 0;

  String get root => '${key.first}';
  bool get isPending => data == null && error == null;
  bool get active => _users > 0;
  bool get hasMore => _pager != null && data is Map && (data as Map)['nextCursor'] != null;

  bool _isStale(Duration staleTime) =>
      _stale || updatedAt == null || DateTime.now().difference(updatedAt!) > staleTime;

  Future<void> refetch() {
    final running = _inflight;
    if (running != null) return running;
    final future = _run();
    _inflight = future;
    return future.whenComplete(() => _inflight = null);
  }

  Future<void> _run() async {
    fetching = true;
    notifyListeners();
    try {
      final result = _pager != null ? await _pager!(null) : await _fetch!();
      data = result;
      error = null;
      updatedAt = DateTime.now();
      _stale = false;
    } catch (e) {
      error = e;
    } finally {
      fetching = false;
      notifyListeners();
    }
  }

  /// Append the next page of a paged list.
  Future<void> loadMore() async {
    if (!hasMore || fetchingMore) return;
    fetchingMore = true;
    notifyListeners();
    try {
      final current = (data as Map).cast<String, dynamic>();
      final next = (await _pager!(current['nextCursor'] as String)) as Map;
      data = {
        ...next.cast<String, dynamic>(),
        'items': [...(current['items'] as List), ...(next['items'] as List)],
      };
      error = null;
    } catch (e) {
      error = e;
    } finally {
      fetchingMore = false;
      notifyListeners();
    }
  }

  /// Show a value at once (an optimistic change, or a write's own answer).
  void set(dynamic value) {
    data = value;
    updatedAt = DateTime.now();
    notifyListeners();
  }
}

/// The app's query cache. Saved lists show at once on the next launch (and offline); a fresh
/// load always follows. Saved data is cleared on sign-out and account deletion.
class QueryClient {
  QueryClient(this.api);

  final Api api;
  final Map<String, Query> _queries = {};
  static const _savedKey = 'duecare.saved.v1';
  // What is worth showing before the network answers: lists, counts, subjects, the profile.
  static const saved = {'tasks', 'overview', 'subjects', 'me', 'rules', 'timetable', 'activity'};
  static const _limit = 2000000; // Characters; a very large workspace simply is not saved.
  Timer? _saveTimer;
  int _generation = 0;

  static String idOf(List<Object?> key) => jsonEncode(key);

  Query _entry(List<Object?> key) => _queries.putIfAbsent(idOf(key), () => Query._(key, idOf(key)));

  /// The query for [key], fetched when it has no fresh answer.
  Query watch(List<Object?> key, Fetcher fetch, {Duration staleTime = const Duration(seconds: 15)}) {
    final q = _entry(key).._fetch = fetch;
    _refreshIfStale(q, staleTime);
    return q;
  }

  // Views watch during build; the load starts right after it, so no listener changes mid-build.
  void _refreshIfStale(Query q, Duration staleTime) {
    if (q._isStale(staleTime) && !q.fetching) scheduleMicrotask(() => _track(q));
  }

  /// A cursor-paged list for [key]; [pager] fetches one page.
  Query watchPaged(List<Object?> key, Pager pager, {Duration staleTime = const Duration(seconds: 15)}) {
    final q = _entry(key).._pager = pager;
    _refreshIfStale(q, staleTime);
    return q;
  }

  /// Fetch now and return the answer (e.g. the latest revision before a one-click write).
  Future<dynamic> fetch(List<Object?> key, Fetcher fetch) async {
    final q = _entry(key).._fetch = fetch;
    await _track(q);
    if (q.error != null) throw q.error!;
    return q.data;
  }

  Query? peek(List<Object?> key) => _queries[idOf(key)];

  void retain(Query q) => q._users++;
  void release(Query q) => q._users--;

  Future<void> _track(Query q) async {
    final generation = _generation;
    await q.refetch();
    if (generation == _generation && saved.contains(q.root) && q.error == null) _scheduleSave();
  }

  /// Mark every query under these roots stale and reload the ones on screen.
  Future<void> invalidate(Iterable<String> roots) async {
    final set = roots.toSet();
    final reloads = <Future<void>>[];
    for (final q in _queries.values.toList()) {
      if (!set.contains(q.root)) continue;
      q._stale = true;
      if (q.active) reloads.add(_track(q));
    }
    await Future.wait(reloads);
  }

  Future<void> invalidateAll() => invalidate(_queries.values.map((q) => q.root));

  /// Forget everything (sign-out, a different account, account deletion).
  Future<void> clear() async {
    _generation++;
    _saveTimer?.cancel();
    for (final q in _queries.values) {
      q
        ..data = null
        ..error = null
        ..updatedAt = null
        .._stale = true;
    }
    _queries.removeWhere((_, q) => !q.active);
    try {
      await (await SharedPreferences.getInstance()).remove(_savedKey);
    } catch (_) {}
  }

  /// Put the last saved data into the cache; returns when it was saved, or null. Saved data is
  /// always stale: it shows at once, and a fresh load replaces it.
  Future<DateTime?> restore() async {
    try {
      final raw = (await SharedPreferences.getInstance()).getString(_savedKey);
      if (raw == null) return null;
      final saved = jsonDecode(raw) as Map<String, dynamic>;
      for (final item in (saved['queries'] as List).cast<Map<String, dynamic>>()) {
        final q = _entry((item['key'] as List).cast<Object?>());
        if (q.data != null || q.fetching) continue;
        q
          ..data = item['data']
          .._stale = true;
      }
      return DateTime.tryParse(saved['at'] as String);
    } catch (_) {
      return null;
    }
  }

  void _scheduleSave() {
    _saveTimer?.cancel();
    _saveTimer = Timer(const Duration(seconds: 2), _save);
  }

  Future<void> _save() async {
    final queries = [
      for (final q in _queries.values)
        if (saved.contains(q.root) && q.data != null && q.error == null) {'key': q.key, 'data': q.data},
    ];
    try {
      final text = jsonEncode({'at': DateTime.now().toUtc().toIso8601String(), 'queries': queries});
      if (text.length <= _limit) await (await SharedPreferences.getInstance()).setString(_savedKey, text);
    } catch (_) {}
  }
}

/// Builds from one query and keeps it fresh while on screen. [poll] refetches on an interval.
class QueryView extends StatefulWidget {
  const QueryView({
    super.key,
    required this.queryKey,
    this.fetch,
    this.pager,
    required this.builder,
    this.poll,
    this.staleTime = const Duration(seconds: 15),
  }) : assert((fetch == null) != (pager == null));

  final List<Object?> queryKey;
  final Fetcher? fetch;
  final Pager? pager;
  final Duration? poll;
  final Duration staleTime;
  final Widget Function(BuildContext context, Query query) builder;

  @override
  State<QueryView> createState() => _QueryViewState();
}

class _QueryViewState extends State<QueryView> {
  Query? _query;
  Timer? _timer;
  // Kept for dispose, where looking up the scope is no longer allowed.
  late QueryClient _client;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _client = QueryScope.of(context);
    _attach();
  }

  @override
  void didUpdateWidget(QueryView old) {
    super.didUpdateWidget(old);
    if (QueryClient.idOf(old.queryKey) != QueryClient.idOf(widget.queryKey) || old.poll != widget.poll) _attach();
  }

  void _attach() {
    final next = widget.pager != null
        ? _client.watchPaged(widget.queryKey, widget.pager!, staleTime: widget.staleTime)
        : _client.watch(widget.queryKey, widget.fetch!, staleTime: widget.staleTime);
    if (!identical(next, _query)) {
      _detach();
      _query = next
        ..addListener(_changed);
      _client.retain(next);
    }
    _timer?.cancel();
    if (widget.poll != null) _timer = Timer.periodic(widget.poll!, (_) => _query?.refetch());
  }

  void _detach() {
    final q = _query;
    if (q == null) return;
    q.removeListener(_changed);
    _client.release(q);
    _query = null;
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _timer?.cancel();
    _detach();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.builder(context, _query!);
}

class QueryScope extends InheritedWidget {
  const QueryScope({super.key, required this.client, required super.child});

  final QueryClient client;

  static QueryClient of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<QueryScope>()!.client;

  @override
  bool updateShouldNotify(QueryScope old) => old.client != client;
}

/// Read every page of a cursor-paged list (subjects, a week's tasks).
Future<List<Map<String, dynamic>>> allPages(Api api, String path) async {
  final items = <Map<String, dynamic>>[];
  String? cursor;
  do {
    final sep = path.contains('?') ? '&' : '?';
    final page = (await api.get('$path${cursor != null ? '${sep}cursor=${Uri.encodeQueryComponent(cursor)}' : ''}')) as Map;
    items.addAll((page['items'] as List).cast<Map>().map((m) => m.cast<String, dynamic>()));
    cursor = page['nextCursor'] as String?;
  } while (cursor != null);
  return items;
}
