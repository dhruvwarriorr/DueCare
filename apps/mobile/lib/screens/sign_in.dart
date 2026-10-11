import 'package:flutter/material.dart';

import '../core/api.dart';
import '../state/services.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

class SignInScreen extends StatefulWidget {
  const SignInScreen({super.key});

  @override
  State<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends State<SignInScreen> {
  bool pending = false;
  Object? error;

  Future<void> signIn() async {
    setState(() {
      pending = true;
      error = null;
    });
    try {
      await AppScope.of(context).signIn();
    } on ApiError catch (e) {
      error = e;
    } catch (_) {
      error = ApiError('Sign-in could not be completed. Please try again', 0);
    }
    if (mounted) setState(() => pending = false);
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    // Illustrative only: a sample week drawn in the workspace's own vocabulary.
    const sample = [
      ('Mon', 'DS Exp 3', '23:59 · done', 'completed'),
      ('Tue', 'CN quiz', '12:15', 'due'),
      ('Wed', 'DBMS ER diagram', '17:00 · missed', 'missed'),
      ('Thu', 'OS write-up', '23:59', 'due'),
    ];
    return Scaffold(
      backgroundColor: c.paper,
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 24, 20, 32),
          children: [
            const Align(alignment: Alignment.centerLeft, child: Logo(size: 34)),
            const SizedBox(height: 36),
            Text.rich(
              TextSpan(
                style: display(context, 46),
                children: [
                  const TextSpan(text: 'Everything due, '),
                  TextSpan(text: 'on one week', style: TextStyle(color: c.ink)),
                  const TextSpan(text: '.'),
                ],
              ),
            ),
            const SizedBox(height: 14),
            Text(
              'DueCare collects assignments and tests from Gmail, Classroom, and your own notes, '
              'and shows them next to your classes.',
              style: TextStyle(fontSize: 17, height: 1.45, color: c.graphite2),
            ),
            const SizedBox(height: 18),
            for (final benefit in [
              'See what’s due, done, and late at a glance',
              'Marked done when you submit',
              'Asks you only when something is unclear',
            ])
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Row(
                  children: [
                    Icon(Icons.check, size: 18, color: c.good),
                    const SizedBox(width: 10),
                    Expanded(child: Text(benefit, style: const TextStyle(fontSize: 15))),
                  ],
                ),
              ),
            const SizedBox(height: 20),
            Container(
              decoration: BoxDecoration(color: c.sheet, border: Border.all(color: c.graphite)),
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  for (final (day, title, meta, status) in sample)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 6),
                      child: Row(
                        children: [
                          SizedBox(width: 40, child: Printed(day)),
                          Expanded(child: _SampleDue(title: title, meta: meta, status: status)),
                        ],
                      ),
                    ),
                  const SizedBox(height: 4),
                  Text('Sample week, for illustration · All times IST', style: TextStyle(fontSize: 12, color: c.graphite2)),
                ],
              ),
            ),
            const SizedBox(height: 28),
            DueButton(
              label: pending ? 'Opening Google…' : 'Continue with Google',
              icon: Icons.arrow_forward,
              expand: true,
              onPressed: pending ? null : signIn,
            ),
            const SizedBox(height: 10),
            Text(
              'Use your verified @somaiya.edu Google account. Google also asks for read-only Gmail and '
              'Classroom access, so your assignments and tests appear automatically. Your password is never '
              'shared with DueCare.',
              style: TextStyle(fontSize: 13, color: c.graphite2, height: 1.45),
            ),
            ErrorNotice(error),
          ],
        ),
      ),
    );
  }
}

class _SampleDue extends StatelessWidget {
  const _SampleDue({required this.title, required this.meta, required this.status});

  final String title, meta, status;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final (bg, line, fill) = switch (status) {
      'completed' => (c.goodTint, c.good, c.good),
      'missed' => (c.badTint, c.bad, c.badTint),
      _ => (c.dueTint, c.dueLine, c.due),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      decoration: BoxDecoration(color: bg, border: Border.all(color: line)),
      child: Row(
        children: [
          Bubble(small: true, fill: fill, stroke: line),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              title,
              style: TextStyle(
                fontWeight: FontWeight.w600,
                fontSize: 13,
                color: status == 'missed' ? c.badText : c.graphite,
                decoration: status == 'missed' ? TextDecoration.lineThrough : null,
              ),
            ),
          ),
          Text(meta, style: display(context, 12, weight: FontWeight.w500, color: c.graphite2)),
        ],
      ),
    );
  }
}
