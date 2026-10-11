import 'dart:async';
import 'dart:convert';

import 'package:duecare/core/api.dart';
import 'package:duecare/core/query.dart';
import 'package:duecare/core/session.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Session session;
  final requests = <http.Request>[];

  Api apiWith(Future<http.Response> Function(http.Request) handler) {
    requests.clear();
    return Api(
      base: Uri.parse('https://duecare.test'),
      session: session,
      client: MockClient((r) {
        requests.add(r);
        return handler(r);
      }),
    );
  }

  setUp(() async {
    FlutterSecureStorage.setMockInitialValues({'duecare.session': 'handle-1'});
    SharedPreferences.setMockInitialValues({});
    session = Session();
    await session.load();
  });

  test('requests carry the bearer session, and writes an idempotency key', () async {
    final api = apiWith((r) async => http.Response(jsonEncode({'ok': true}), 200));
    await api.get('/me');
    expect(requests.last.url.toString(), 'https://duecare.test/api/v1/me');
    expect(requests.last.headers['Authorization'], 'Bearer handle-1');
    expect(requests.last.headers.containsKey('Idempotency-Key'), isFalse);

    await api.send('PATCH', '/tasks/t1', body: {'revision': 2}, idempotencyKey: 'retry-1');
    expect(requests.last.headers['Idempotency-Key'], 'retry-1');
    expect(jsonDecode(requests.last.body), {'revision': 2});

    await api.send('POST', '/mobile/auth/start', body: {}, authenticated: false);
    expect(requests.last.headers.containsKey('Authorization'), isFalse);
    expect(uuid4(), matches(RegExp(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')));
  });

  test('errors keep the server message; 401 ends the session; deletion is reported', () async {
    var deleting = false;
    final api = apiWith((r) async => switch (r.url.path) {
          '/api/v1/tasks' => http.Response(jsonEncode({'code': 'INVALID_INPUT', 'message': 'Check the highlighted fields', 'fieldErrors': {'title': 'Required'}}), 422),
          '/api/v1/rules' => http.Response(jsonEncode({'code': 'ACCOUNT_DELETING', 'message': 'Deleting'}), 409),
          '/api/v1/broken' => http.Response('<html>proxy</html>', 502),
          _ => http.Response(jsonEncode({'code': 'SIGN_IN_REQUIRED', 'message': 'Please sign in'}), 401),
        })
      ..onDeleting = () => deleting = true;

    final invalid = await api.send('POST', '/tasks', body: {}).then<ApiError?>((_) => null, onError: (Object e) => e as ApiError);
    expect(invalid!.message, 'Check the highlighted fields');
    expect(invalid.fields, {'title': 'Required'});
    expect(session.signedIn, isTrue);

    await expectLater(api.get('/rules'), throwsA(isA<ApiError>()));
    expect(deleting, isTrue);

    final broken = await api.get('/broken').then<ApiError?>((_) => null, onError: (Object e) => e as ApiError);
    expect(broken!.message, 'DueCare is temporarily unavailable. Please try again');

    await expectLater(api.get('/me'), throwsA(isA<ApiError>().having((e) => e.status, 'status', 401)));
    expect(session.signedIn, isFalse);
  });

  test('an unreachable server is distinguished from an error answer', () async {
    final api = apiWith((r) async => throw http.ClientException('connection refused'));
    final e = await api.get('/changes').then<ApiError?>((_) => null, onError: (Object e) => e as ApiError);
    expect(e!.unreachable, isTrue);
    expect(session.signedIn, isTrue);
  });

  test('queries refetch on invalidate, page on demand, and survive restarts', () async {
    var version = 0;
    final api = apiWith((r) async {
      final cursor = r.url.queryParameters['cursor'];
      if (r.url.path == '/api/v1/tasks') {
        return http.Response(
          jsonEncode(cursor == null
              ? {'items': [{'id': 'a'}], 'nextCursor': 'c2'}
              : {'items': [{'id': 'b'}], 'nextCursor': null}),
          200,
        );
      }
      version++;
      return http.Response(jsonEncode({'version': version}), 200);
    });
    final client = QueryClient(api);

    final me = client.watch(['me'], () => api.get('/me'));
    client.retain(me);
    await pumpEventQueue();
    expect(me.data, {'version': 1});
    await client.invalidate(['me']);
    expect(me.data, {'version': 2});
    // Inactive queries are only marked stale.
    client.release(me);
    await client.invalidate(['me']);
    expect(me.data, {'version': 2});

    final tasks = client.watchPaged(['tasks', 'all'], (cursor) => api.get('/tasks${cursor != null ? '?cursor=$cursor' : ''}'));
    await pumpEventQueue();
    expect(tasks.hasMore, isTrue);
    await tasks.loadMore();
    expect((tasks.data as Map)['items'], [{'id': 'a'}, {'id': 'b'}]);
    expect(tasks.hasMore, isFalse);

    // Saved lists show at once on the next launch, marked stale.
    await Future<void>.delayed(const Duration(seconds: 3));
    final next = QueryClient(api);
    expect(await next.restore(), isNotNull);
    expect(next.peek(['tasks', 'all'])?.data, isNotNull);
    expect(next.peek(['me'])?.data, {'version': 2});

    await next.clear();
    expect(await QueryClient(api).restore(), isNull);
  });

  test('a refused sign-in step never ends the saved session; a rejected session does', () async {
    final api = apiWith((r) async => http.Response(jsonEncode({'code': 'LOGIN_EXPIRED', 'message': 'Sign-in expired'}), 401));
    // Re-asking Google for access while signed in: the callback is sent without the session.
    await expectLater(api.send('POST', '/mobile/auth/callback', body: {}, authenticated: false), throwsA(isA<ApiError>()));
    expect(session.signedIn, isTrue);
    // Ending a replaced, older session with its own handle leaves the current one alone.
    await expectLater(api.send('POST', '/mobile/auth/logout', bearer: 'older-handle'), throwsA(isA<ApiError>()));
    expect(session.signedIn, isTrue);
    await expectLater(api.get('/me'), throwsA(isA<ApiError>()));
    expect(session.signedIn, isFalse);
  });

  test('answers that arrive after sign-out, or after a refresh, are discarded', () async {
    final gate = <String, Completer<http.Response>>{};
    final api = apiWith((r) {
      final c = Completer<http.Response>();
      gate[r.url.toString()] = c;
      return c.future;
    });
    final client = QueryClient(api);
    final me = client.watch(['me'], () => api.get('/me'));
    client.retain(me);
    await pumpEventQueue();
    await client.clear(); // Signed out while /me was loading.
    gate['https://duecare.test/api/v1/me']!.complete(http.Response(jsonEncode({'name': 'Previous student'}), 200));
    await pumpEventQueue();
    expect(me.data, isNull, reason: 'The previous account’s data must never appear.');

    final list = client.watchPaged(['tasks'], (cursor) => api.get('/tasks${cursor != null ? '?cursor=$cursor' : ''}'));
    client.retain(list);
    await pumpEventQueue();
    gate['https://duecare.test/api/v1/tasks']!.complete(http.Response(jsonEncode({'items': ['a'], 'nextCursor': 'c2'}), 200));
    await pumpEventQueue();
    final more = list.loadMore();
    await pumpEventQueue();
    // A refresh lands while page 2 is still loading...
    final refresh = list.refetch();
    await pumpEventQueue();
    gate['https://duecare.test/api/v1/tasks']!.complete(http.Response(jsonEncode({'items': ['a2'], 'nextCursor': null}), 200));
    await refresh;
    gate['https://duecare.test/api/v1/tasks?cursor=c2']!.complete(http.Response(jsonEncode({'items': ['b'], 'nextCursor': null}), 200));
    await more;
    // ...so the old second page is not appended to the refreshed list.
    expect((list.data as Map)['items'], ['a2']);
  });
}
