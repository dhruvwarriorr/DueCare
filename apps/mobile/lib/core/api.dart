import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

import 'session.dart';

class ApiError implements Exception {
  ApiError(this.message, this.status, {this.code, this.fields = const {}});

  final String message;
  final int status;
  final String? code;
  final Map<String, String> fields;

  /// The server could not be reached at all (as opposed to an error answer from it).
  bool get unreachable => status == 0;

  @override
  String toString() => message;
}

/// A random UUID v4 for idempotency keys.
String uuid4() {
  final r = Random.secure();
  final b = List<int>.generate(16, (_) => r.nextInt(256));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  final h = b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();
  return '${h.substring(0, 8)}-${h.substring(8, 12)}-${h.substring(12, 16)}-${h.substring(16, 20)}-${h.substring(20)}';
}

/// Calls the DueCare API directly with the session handle as a bearer token. Mirrors the web
/// client (apps/web/src/lib/api.ts): JSON in and out, an idempotency key on every write, and
/// one error shape for server answers and unreachable servers alike.
class Api {
  Api({required this.base, required this.session, http.Client? client}) : _client = client ?? http.Client();

  final Uri base;
  final Session session;
  final http.Client _client;

  /// Called when the server says account deletion is in progress.
  void Function()? onDeleting;

  Future<dynamic> get(String path, {Duration timeout = const Duration(seconds: 25)}) => send('GET', path, timeout: timeout);

  Future<dynamic> send(
    String method,
    String path, {
    Object? body,
    String? idempotencyKey,
    bool authenticated = true,
    String? bearer,
    Duration timeout = const Duration(seconds: 25),
  }) async {
    final uri = base.resolve('/api/v1$path');
    final request = http.Request(method, uri)..headers['Accept'] = 'application/json';
    final handle = bearer ?? (authenticated ? session.handle : null);
    if (handle != null) request.headers['Authorization'] = 'Bearer $handle';
    if (method != 'GET') {
      // A retry of an uncertain write reuses its key so the server replays, never repeats, it.
      request.headers['Idempotency-Key'] = idempotencyKey ?? uuid4();
      if (body != null) {
        request.headers['Content-Type'] = 'application/json';
        request.body = jsonEncode(body);
      }
    }
    final http.Response response;
    try {
      response = await http.Response.fromStream(await _client.send(request).timeout(timeout));
    } on TimeoutException {
      throw ApiError('DueCare took too long to answer. Please try again', 0, code: 'TIMEOUT');
    } on SocketException {
      throw ApiError('Can’t reach DueCare. Check your connection and try again', 0, code: 'OFFLINE');
    } on http.ClientException {
      throw ApiError('Can’t reach DueCare. Check your connection and try again', 0, code: 'OFFLINE');
    }
    // Only a rejected session ends the sign-in: not a refused sign-in step, nor a request
    // made with another (older) handle.
    return _decode(response, sessionRejected: handle != null && handle == session.handle);
  }

  /// Send files as multipart form data (timetable extraction on a host without upload storage).
  Future<dynamic> multipart(String path, List<({String name, List<int> bytes, String contentType})> files) async {
    final request = http.MultipartRequest('POST', base.resolve('/api/v1$path'))
      ..headers['Accept'] = 'application/json'
      ..headers['Idempotency-Key'] = uuid4();
    if (session.handle != null) request.headers['Authorization'] = 'Bearer ${session.handle}';
    for (final f in files) {
      request.files.add(http.MultipartFile.fromBytes('files', f.bytes, filename: f.name, contentType: MediaType.parse(f.contentType)));
    }
    final http.Response response;
    try {
      response = await http.Response.fromStream(await _client.send(request).timeout(const Duration(seconds: 90)));
    } on TimeoutException {
      throw ApiError('Reading the timetable took too long. Please try again', 0, code: 'TIMEOUT');
    } on Exception {
      throw ApiError('Can’t reach DueCare. Check your connection and try again', 0, code: 'OFFLINE');
    }
    return _decode(response, sessionRejected: session.handle != null);
  }

  /// Upload a file to a signed storage URL the API handed out (timetable originals).
  Future<void> putBytes(String url, List<int> bytes, String contentType) async {
    final http.Response response;
    try {
      response = await _client
          .put(Uri.parse(url), body: bytes, headers: {'Content-Type': contentType})
          .timeout(const Duration(seconds: 120));
    } on Exception {
      throw ApiError('Could not upload the timetable. Please try again', 0, code: 'OFFLINE');
    }
    if (response.statusCode >= 300) throw ApiError('Could not upload the timetable. Please try again', response.statusCode);
  }

  Future<dynamic> _decode(http.Response response, {required bool sessionRejected}) async {
    // A proxy, restart or crash can return non-JSON; report it as a normal request error.
    Map<String, dynamic> data = {};
    dynamic parsed;
    try {
      parsed = response.body.isEmpty ? <String, dynamic>{} : jsonDecode(utf8.decode(response.bodyBytes));
      if (parsed is Map<String, dynamic>) data = parsed;
    } on FormatException {
      if (response.statusCode < 300) throw ApiError('DueCare returned an unexpected response. Please try again', 502);
      data = {'message': 'DueCare is temporarily unavailable. Please try again'};
    }
    if (response.statusCode >= 300) {
      final code = data['code'] as String?;
      if (code == 'ACCOUNT_DELETING') onDeleting?.call();
      if (response.statusCode == 401 && sessionRejected) await session.clear();
      final fields = (data['fieldErrors'] as Map?)?.map((k, v) => MapEntry('$k', '$v')) ?? const <String, String>{};
      throw ApiError((data['message'] as String?) ?? 'Please try again', response.statusCode, code: code, fields: fields);
    }
    return parsed;
  }
}
