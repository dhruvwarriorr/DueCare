import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/models.dart';
import '../state/services.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'activity.dart';
import 'notifications.dart';
import 'rules.dart';
import 'settings.dart';
import 'sources.dart';
import 'subjects.dart';
import 'workspace.dart';

/// Everything beyond the main tabs: the account, subjects and settings.
class MoreScreen extends StatefulWidget {
  const MoreScreen({super.key, required this.profile});

  final Profile profile;

  @override
  State<MoreScreen> createState() => _MoreScreenState();
}

class _MoreScreenState extends State<MoreScreen> {
  bool signingOut = false;

  Future<void> signOut() async {
    if (!await confirm(context, title: 'Sign out?', body: 'Saved data and reminders on this phone are removed.', action: 'Sign out')) return;
    if (!mounted) return;
    setState(() => signingOut = true);
    try {
      await AppScope.of(context).signOut();
    } on ApiError catch (e) {
      if (mounted) {
        setState(() => signingOut = false);
        toast(context, e.message);
      }
    }
  }

  void open(Widget screen) => Navigator.push(context, MaterialPageRoute(builder: (_) => screen));

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final p = widget.profile;
    return PageScaffold(
      title: 'More',
      actions: const [ActivityBell()],
      bottomPadding: 120,
      children: [
        Material(
          color: c.sheet,
          borderRadius: BorderRadius.circular(Radii.card),
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: () => open(const ProfileScreen()),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(children: [
                Avatar(p.initial, size: 56),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(p.name ?? 'Student', style: display(context, 20)),
                      Text(p.email, style: TextStyle(color: c.graphite2, fontSize: 13.5)),
                      if (p.academicLine.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 6),
                          child: Tag(p.academicLine, icon: Icons.school_outlined),
                        ),
                    ],
                  ),
                ),
                Icon(Icons.chevron_right, color: c.graphite2),
              ]),
            ),
          ),
        ),
        GroupCard(label: 'Your work', children: [
          SettingTile(icon: Icons.class_outlined, title: 'Subjects', subtitle: 'Subjects and weekly timetable', onTap: () => open(const SubjectsScreen())),
          SettingTile(icon: Icons.notifications_none_rounded, title: 'Activity', subtitle: 'New work, changes and sync issues', onTap: () => open(const ActivityScreen())),
        ]),
        GroupCard(label: 'Settings', children: [
          SettingTile(icon: Icons.notifications_active_outlined, title: 'Notifications', subtitle: 'Reminders, updates and quiet hours', onTap: () => open(const NotificationsScreen())),
          SettingTile(icon: Icons.person_outline_rounded, title: 'Profile', subtitle: 'Academic details, appearance and KT notices', onTap: () => open(const ProfileScreen())),
          SettingTile(icon: Icons.sync_rounded, title: 'Sources', subtitle: 'Gmail, Classroom, faculty and senders', onTap: () => open(const SourcesScreen())),
          SettingTile(icon: Icons.tune_rounded, title: 'Rules', subtitle: 'Priorities and hidden work', onTap: () => open(const RulesScreen())),
          SettingTile(icon: Icons.lock_outline_rounded, title: 'Privacy & data', subtitle: 'Imported data and account deletion', onTap: () => open(const PrivacyScreen())),
        ]),
        GroupCard(label: 'Account', children: [
          SettingTile(icon: Icons.logout_rounded, title: signingOut ? 'Signing out…' : 'Sign out', danger: true, onTap: signingOut ? null : signOut),
        ]),
        const SizedBox(height: 20),
        Center(
          child: Column(children: [
            const Logo(size: 22),
            const SizedBox(height: 6),
            Text('All times are in IST', style: TextStyle(color: c.graphite2, fontSize: 12.5)),
          ]),
        ),
      ],
    );
  }
}
