import 'dart:async';

import 'package:duecare/core/api.dart';
import 'package:duecare/core/query.dart';
import 'package:duecare/core/session.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_platform_interface.dart';

class DelayedRemovalStore extends InMemorySharedPreferencesStore {
  DelayedRemovalStore(super.data) : super.withData();

  final allowRemoval = Completer<void>();

  @override
  Future<bool> remove(String key) async {
    await allowRemoval.future;
    return super.remove(key);
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'cache cleanup waits for the platform to remove saved private data',
    () async {
      SharedPreferences.setMockInitialValues({});
      final store = DelayedRemovalStore({
        'flutter.duecare.saved.v1': 'private workspace',
      });
      SharedPreferencesStorePlatform.instance = store;
      addTearDown(() => SharedPreferences.setMockInitialValues({}));
      final queries = QueryClient(
        Api(base: Uri.parse('https://duecare.test'), session: Session()),
      );
      var finished = false;
      final clearing = queries.clear().then((_) => finished = true);
      await pumpEventQueue();
      expect(
        finished,
        isFalse,
        reason: 'Signing out must await the native persistence operation.',
      );
      expect(
        (await store.getAll()).containsKey('flutter.duecare.saved.v1'),
        isTrue,
      );
      store.allowRemoval.complete();
      await clearing;
      expect(finished, isTrue);
      expect(
        (await store.getAll()).containsKey('flutter.duecare.saved.v1'),
        isFalse,
      );
    },
  );
}
