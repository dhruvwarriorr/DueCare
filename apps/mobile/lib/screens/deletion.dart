import 'dart:async';

import 'package:flutter/material.dart';

import '../core/api.dart';
import '../state/services.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

/// Account deletion progress. The server deletes the account in saved steps; this screen only
/// shows how far it has got, using the resume token (the login is gone once auth is removed).
class DeletionScreen extends StatefulWidget {
  const DeletionScreen({super.key});

  @override
  State<DeletionScreen> createState() => _DeletionScreenState();
}

class _DeletionScreenState extends State<DeletionScreen> {
  static const steps = [
    ('revoke', 'Disconnect Google access'),
    ('data', 'Erase your tasks and imported data'),
    ('auth', 'Remove your DueCare login'),
  ];
  Map? job;
  Object? error;
  Timer? timer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      // Tasks saved on this phone belong to a signed-in session; none survive it.
      AppScope.of(context).queries.clear();
      _poll();
      timer = Timer.periodic(const Duration(seconds: 2), (_) => _poll());
    });
  }

  Future<void> _poll() async {
    final services = AppScope.of(context);
    final token = services.session.deletionToken;
    if (token == null) return;
    try {
      final result = (await services.api.send(
        'POST',
        '/mobile/account-deletion',
        body: {'token': token, 'advance': false},
        authenticated: false,
      )) as Map;
      if (!mounted) return;
      setState(() {
        job = result;
        error = null;
      });
      if (result['status'] == 'completed') timer?.cancel();
    } on ApiError catch (e) {
      if (mounted) setState(() => error = e);
    }
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> _finish() async {
    final services = AppScope.of(context);
    await services.forget();
    await services.session.deletionFinished();
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final done = job?['status'] == 'completed';
    final current = done ? steps.length : steps.indexWhere((s) => s.$1 == job?['stage']);
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            const Align(alignment: Alignment.centerLeft, child: Logo(size: 30)),
            const SizedBox(height: 32),
            Text(done ? 'Your account has been deleted' : 'Deleting your account', style: display(context, 36)),
            const SizedBox(height: 12),
            if (done)
              const Text(
                'Your workspace, source credentials, and DueCare login were removed. '
                'Your Google mail and Classroom work remain in Google.',
              ),
            const SizedBox(height: 20),
            for (final (i, (_, label)) in steps.indexed)
              Container(
                padding: const EdgeInsets.symmetric(vertical: 14),
                decoration: BoxDecoration(border: Border(bottom: BorderSide(color: c.inkRule))),
                child: Row(
                  children: [
                    Bubble(
                      fill: i < current ? c.good : (i == current ? c.due : null),
                      stroke: i < current ? c.good : (i == current ? c.dueLine : null),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        label +
                            (i < current
                                ? ' · done'
                                : i == current && !done
                                    ? (job?['errorCode'] != null ? ' · Google is busy, retrying automatically' : ' · in progress')
                                    : ''),
                        style: TextStyle(fontWeight: i == current ? FontWeight.w700 : FontWeight.w500),
                      ),
                    ),
                  ],
                ),
              ),
            ErrorNotice(error, retry: _poll),
            const SizedBox(height: 16),
            if (!done) Text('This screen updates by itself.', style: TextStyle(color: c.graphite2, fontSize: 13)),
            if (done) DueButton(label: 'Back to sign in', onPressed: _finish),
          ],
        ),
      ),
    );
  }
}
