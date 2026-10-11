import 'package:flutter/material.dart';

import '../core/api.dart';
import '../state/services.dart';
import '../ui/icons.dart';
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
    // Illustrative only: a sample day drawn in the app's own vocabulary.
    const sample = [
      ('DS Experiment 3', '23:59', 'completed'),
      ('CN quiz', '12:15', 'due'),
      ('DBMS ER diagram', '17:00', 'missed'),
    ];
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(24, 28, 24, 16),
                children: [
                  const Align(alignment: Alignment.centerLeft, child: Logo(size: 34)),
                  const SizedBox(height: 40),
                  Text.rich(
                    TextSpan(
                      style: display(context, 42),
                      children: [
                        const TextSpan(text: 'Everything due,\n'),
                        TextSpan(text: 'in one place', style: TextStyle(color: c.ink)),
                        const TextSpan(text: '.'),
                      ],
                    ),
                  ),
                  const SizedBox(height: 14),
                  Text(
                    'Assignments and tests from Gmail, Classroom and your own notes, next to your classes.',
                    style: TextStyle(fontSize: 17, height: 1.45, color: c.graphite2),
                  ),
                  const SizedBox(height: 26),
                  Container(
                    padding: const EdgeInsets.fromLTRB(14, 14, 14, 8),
                    decoration: BoxDecoration(color: c.sheet, borderRadius: BorderRadius.circular(Radii.card + 4)),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(children: [
                          Text('Today', style: display(context, 18)),
                          const Spacer(),
                          Text('Sample', style: TextStyle(fontSize: 12, color: c.graphite2)),
                        ]),
                        const SizedBox(height: 10),
                        for (final (title, time, status) in sample) _SampleDue(title: title, time: time, status: status),
                      ],
                    ),
                  ),
                  const SizedBox(height: 22),
                  for (final (icon, text) in const [
                    (DueIcons.week, 'See what’s due, done and late at a glance'),
                    (DueIcons.done, 'Marked done when you submit'),
                    (DueIcons.notifications, 'Reminded before every deadline'),
                  ])
                    Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: Row(children: [
                        Container(
                          width: 36,
                          height: 36,
                          decoration: BoxDecoration(color: c.inkWash, borderRadius: BorderRadius.circular(11)),
                          child: glyph(icon, size: 19, color: c.ink),
                        ),
                        const SizedBox(width: 12),
                        Expanded(child: Text(text, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600))),
                      ]),
                    ),
                  ErrorNotice(error),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 8, 24, 16),
              child: Column(children: [
                DueButton(
                  label: pending ? 'Opening Google…' : 'Continue with Google',
                  icon: Icons.arrow_forward_rounded,
                  expand: true,
                  onPressed: pending ? null : signIn,
                ),
                const SizedBox(height: 10),
                Text(
                  'Use your @somaiya.edu account. Google also asks for read-only Gmail and Classroom access. Your password is never shared.',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 12.5, color: c.graphite2, height: 1.4),
                ),
              ]),
            ),
          ],
        ),
      ),
    );
  }
}

class _SampleDue extends StatelessWidget {
  const _SampleDue({required this.title, required this.time, required this.status});

  final String title, time, status;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final (bg, line) = switch (status) {
      'completed' => (c.goodTint, c.good),
      'missed' => (c.badTint, c.bad),
      _ => (c.dueTint, c.dueLine),
    };
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(Radii.medium), border: Border.all(color: line)),
      child: IntrinsicHeight(
        child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const SizedBox(width: 12),
          Center(child: Bubble(small: true, fill: status == 'due' ? null : line, stroke: line)),
          const SizedBox(width: 12),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 11),
              child: Text(
                title,
                style: TextStyle(
                  fontWeight: FontWeight.w700,
                  color: status == 'missed' ? c.badText : c.graphite,
                  decoration: status == 'missed' ? TextDecoration.lineThrough : null,
                ),
              ),
            ),
          ),
          Center(child: Text(time, style: display(context, 13, color: c.graphite2))),
          const SizedBox(width: 12),
        ]),
      ),
    );
  }
}
