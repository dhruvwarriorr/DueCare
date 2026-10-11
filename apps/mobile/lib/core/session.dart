import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// The signed-in session handle (the same opaque server-side session the web app keeps in an
/// HTTP-only cookie) and an account deletion's resume token. Both live in the platform
/// keychain/keystore, never in plain preferences.
class Session extends ChangeNotifier {
  Session({FlutterSecureStorage? storage}) : _storage = storage ?? const FlutterSecureStorage();

  static const _handleKey = 'duecare.session';
  static const _deletionKey = 'duecare.deletion';

  final FlutterSecureStorage _storage;
  String? _handle;
  String? _deletion;
  bool _loaded = false;

  String? get handle => _handle;
  bool get signedIn => _handle != null;
  bool get loaded => _loaded;

  /// Set while an account deletion runs: the app shows only its progress.
  String? get deletionToken => _deletion;

  Future<void> load() async {
    try {
      _handle = await _storage.read(key: _handleKey);
      _deletion = await _storage.read(key: _deletionKey);
    } catch (_) {
      // An unreadable keychain entry (e.g. after a restore to another device) means signing in again.
      _handle = null;
    }
    _loaded = true;
    notifyListeners();
  }

  Future<void> signIn(String handle) async {
    _handle = handle;
    await _storage.write(key: _handleKey, value: handle);
    notifyListeners();
  }

  /// Forget the session (sign-out, expiry or revocation). The caller clears cached data.
  Future<void> clear() async {
    if (_handle == null) return;
    _handle = null;
    await _storage.delete(key: _handleKey);
    notifyListeners();
  }

  Future<void> deleting(String token) async {
    _deletion = token;
    await _storage.write(key: _deletionKey, value: token);
    notifyListeners();
  }

  Future<void> deletionFinished() async {
    _deletion = null;
    await _storage.delete(key: _deletionKey);
    notifyListeners();
  }
}
