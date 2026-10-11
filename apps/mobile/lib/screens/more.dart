import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/models.dart';
import '../state/services.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'activity.dart';
import 'rules.dart';
import 'settings.dart';
import 'sources.dart';
import 'subjects.dart';

/// Everything beyond the bottom bar: subjects, activity, settings and the account.
class MoreScreen extends StatefulWidget {
  const MoreScreen({super.key, required this.profile});

  final Profile profile;

  @override
  State<MoreScreen> createState() => _MoreScreenState();
}

class _MoreScreenState extends State<MoreScreen> {
  bool signingOut = false;
  Object? error;

  Future<void> signOut() async {
    setState(() {
      signingOut = true;
      error = null;
    });
    try {
      await AppScope.of(context).signOut();
    } on ApiError catch (e) {
      if (mounted) {
        setState(() {
          error = e;
          signingOut = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final p = widget.profile;
    void open(Widget screen) => Navigator.push(context, MaterialPageRoute(builder: (_) => screen));
    final rows = [
      ('Subjects', 'Your subjects and weekly timetable', Icons.calendar_month_outlined, () => open(const SubjectsScreen())),
      ('Activity', 'New work, changes, and sync issues', Icons.notifications_none, () => open(const ActivityScreen())),
      ('Profile & privacy', 'Academic details, reminders, KT notices, your data', Icons.person_outline, () => open(const SettingsScreen())),
      ('Sources', 'Gmail and Classroom, faculty and senders', Icons.sync, () => open(const SourcesScreen())),
      ('Rules', 'Priorities and hidden work', Icons.tune, () => open(const RulesScreen())),
    ];
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
      children: [
        Row(
          children: [
            Container(
              width: 48,
              height: 48,
              alignment: Alignment.center,
              color: c.inkTint,
              child: Text(p.initial, style: display(context, 22)),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(p.name ?? 'Student', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 17)),
                  Text(p.email, style: TextStyle(color: c.graphite2, fontSize: 13)),
                  if (p.academicLine.isNotEmpty) Text(p.academicLine, style: TextStyle(color: c.graphite2, fontSize: 13)),
                ],
              ),
            ),
          ],
        ),
        const SizedBox(height: 18),
        Container(
          decoration: BoxDecoration(border: Border.all(color: c.graphite), color: c.sheet),
          child: Column(
            children: [
              for (final (title, subtitle, icon, onTap) in rows)
                InkWell(
                  onTap: onTap,
                  child: Container(
                    constraints: const BoxConstraints(minHeight: 56),
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                    decoration: BoxDecoration(border: Border(bottom: BorderSide(color: c.inkRule))),
                    child: Row(
                      children: [
                        Icon(icon, color: c.ink, size: 20),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(title, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
                              Text(subtitle, style: TextStyle(color: c.graphite2, fontSize: 13)),
                            ],
                          ),
                        ),
                        Icon(Icons.chevron_right, color: c.ink),
                      ],
                    ),
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: 14),
        Text('All times are in IST', style: TextStyle(color: c.graphite2, fontSize: 13)),
        const SizedBox(height: 14),
        ErrorNotice(error),
        Align(
          alignment: Alignment.centerLeft,
          child: DueButton(label: 'Sign out', icon: Icons.logout, variant: Variant.outline, onPressed: signingOut ? null : signOut),
        ),
      ],
    );
  }
}
