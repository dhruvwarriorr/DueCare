import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../core/api.dart';
import '../notifications/prefs.dart';
import '../state/services.dart';
import '../ui/icons.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

/// What DueCare tells the student, and when. Choices save as they change.
class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key});

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> with WidgetsBindingObserver {
  NotifyPrefs? prefs;
  int? revision;
  bool serverPush = false;
  int devices = 0;
  bool? permitted;
  bool exact = true;
  bool saving = false;
  Object? error;
  Timer? _save;

  Services get services => AppScope.of(context);

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    // Leaving straight after a change still saves it.
    if (_save?.isActive ?? false) {
      _save!.cancel();
      unawaited(_persist(leaving: true));
    }
    super.dispose();
  }

  // Coming back from the system settings may have changed the permissions.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _permissions();
  }

  Future<void> _permissions() async {
    final n = services.notifier;
    final p = await n.permitted();
    final e = await n.exactAllowed();
    if (mounted) {
      setState(() {
        permitted = p;
        exact = e;
      });
    }
  }

  Future<void> _load() async {
    final cached = await NotifyPrefs.load();
    if (mounted && prefs == null) setState(() => prefs = cached);
    await _permissions();
    try {
      final body = (await services.api.get('/notification-settings')) as Map;
      final loaded = NotifyPrefs.fromJson((body['settings'] as Map).cast<String, dynamic>());
      await loaded.save();
      if (!mounted) return;
      setState(() {
        prefs = loaded;
        revision = body['revision'] as int?;
        serverPush = (body['push'] as Map)['configured'] == true;
        devices = ((body['push'] as Map)['devices'] as num? ?? 0).toInt();
        error = null;
      });
    } on ApiError catch (e) {
      if (mounted) setState(() => error = e);
    }
  }

  /// Show the change at once; save it a moment later (several quick changes save together).
  void change(Map<String, dynamic> changes) {
    setState(() => prefs = prefs!.copyWith(changes));
    _save?.cancel();
    _save = Timer(const Duration(milliseconds: 500), _persist);
  }

  Future<void> _persist({bool leaving = false}) async {
    final chosen = prefs!;
    final api = services.api;
    final notifier = services.notifier;
    if (!leaving) setState(() => saving = true);
    try {
      final body = (await api.send('PUT', '/notification-settings', body: {'revision': revision, 'settings': chosen.toJson()})) as Map;
      revision = body['revision'] as int?;
      await chosen.save();
      unawaited(notifier.refresh(api, prefs: chosen));
      if (mounted) setState(() => error = null);
    } on ApiError catch (e) {
      if (mounted) setState(() => error = e);
      if (e.status == 409 && mounted) await _load();
    }
    if (mounted) setState(() => saving = false);
  }

  Future<void> _turnOn() async {
    final granted = await services.notifier.requestPermission();
    if (!granted) await services.notifier.openSettings();
    await _permissions();
    if (permitted == true) await services.push.register(services.api, onPush: () => services.queries.invalidateAll());
  }

  Future<void> _test() async {
    final p = prefs ?? const NotifyPrefs();
    if (services.push.available && serverPush && devices > 0) {
      try {
        await services.api.send('POST', '/devices/test');
        if (mounted) toast(context, 'Test sent. It should arrive in a few seconds.');
        return;
      } on ApiError catch (e) {
        if (mounted) toast(context, '${e.message}. Showing a local one instead.');
      }
    }
    await services.notifier.showTest(p);
  }

  Future<void> _time(String key, String value) async {
    final picked = await pickTime(context, value);
    if (picked != null) change({key: picked});
  }

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final p = prefs;
    final pushReady = services.push.available && serverPush;
    return PageScaffold(
      title: 'Notifications',
      onRefresh: _load,
      actions: [
        if (saving) const Padding(padding: EdgeInsets.all(14), child: SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2.2))),
      ],
      children: [
        if (permitted == false)
          Panel(
            color: c.dueTint,
            child: Row(children: [
              DueIcon(DueIcons.activity, color: c.dueText),
              const SizedBox(width: 12),
              const Expanded(child: Text('Notifications are off for DueCare on this phone.', style: TextStyle(fontWeight: FontWeight.w600))),
              TextButton(onPressed: _turnOn, child: const Text('Turn on')),
            ]),
          ),
        ErrorNotice(error, retry: _load),
        if (p == null)
          const Loading('Loading your choices…')
        else ...[
          GroupCard(
            label: 'Deadline reminders',
            footer: exact || !p.reminders ? null : 'Reminders may arrive a few minutes late. Allow precise timing for exact times.',
            children: [
              SwitchTile(
                icon: DueIcons.clock,
                title: 'Remind me before deadlines',
                value: p.reminders,
                onChanged: (v) => change({'reminders': v}),
              ),
              if (p.reminders) ...[
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 14),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('Remind me', style: TextStyle(fontWeight: FontWeight.w700, color: c.graphite2)),
                    const SizedBox(height: 8),
                    Wrap(spacing: 8, runSpacing: 8, children: [
                      for (final (minutes, label) in NotifyPrefs.leads)
                        FilterChip(
                          label: Text('$label before'),
                          selected: p.reminderLeads.contains(minutes),
                          onSelected: (on) {
                            final next = {...p.reminderLeads};
                            on ? next.add(minutes) : next.remove(minutes);
                            // At least one reminder time stays chosen while reminders are on.
                            if (next.isNotEmpty) change({'reminderLeads': (next.toList()..sort((a, b) => b.compareTo(a)))});
                          },
                        ),
                    ]),
                  ]),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('For', style: TextStyle(fontWeight: FontWeight.w700, color: c.graphite2)),
                    const SizedBox(height: 8),
                    BubbleChoice<String>(
                      value: p.reminderScope,
                      options: const [('all', 'All work'), ('important', 'Tests & high priority')],
                      onChanged: (v) => change({'reminderScope': v}),
                    ),
                  ]),
                ),
                if (!exact)
                  SettingTile(
                    icon: DueIcons.clock,
                    title: 'Allow precise timing',
                    subtitle: 'Lets reminders arrive exactly on time',
                    onTap: () async {
                      await services.notifier.requestExact();
                      await _permissions();
                    },
                  ),
              ],
            ],
          ),
          GroupCard(
            label: 'Daily summary',
            children: [
              SwitchTile(
                icon: DueIcons.event,
                title: 'Morning summary',
                subtitle: 'What’s due that day',
                value: p.digest,
                onChanged: (v) => change({'digest': v}),
              ),
              if (p.digest)
                SettingTile(
                  icon: DueIcons.clock,
                  title: 'At ${p.digestTime}',
                  subtitle: 'IST',
                  onTap: () => _time('digestTime', p.digestTime),
                ),
            ],
          ),
          GroupCard(
            label: 'Updates',
            footer: pushReady
                ? 'Sent the moment DueCare finds something, even when the app is closed.'
                : 'Instant updates aren’t set up for this app yet, so these arrive when you open DueCare.',
            children: [
              SwitchTile(
                icon: DueIcons.activity,
                title: 'Instant updates',
                subtitle: pushReady ? (devices > 0 ? 'On for this phone' : 'Connecting this phone…') : 'Not available yet',
                value: p.push,
                onChanged: (v) => change({'push': v}),
              ),
              for (final (key, icon, title, subtitle) in const [
                ('newWork', DueIcons.add, 'New work', 'Assignments and tests found in Gmail or Classroom'),
                ('changes', DueIcons.event, 'Changes', 'Deadlines or details that changed'),
                ('review', DueIcons.review, 'Needs your review', 'Items DueCare couldn’t settle'),
                ('completed', DueIcons.done, 'Marked done for you', 'From your submission or turn-in'),
                ('syncIssues', DueIcons.sources, 'Sync problems', 'When a source needs attention'),
              ])
                SwitchTile(
                  icon: icon,
                  title: title,
                  subtitle: subtitle,
                  value: p.push && (p.toJson()[key] as bool),
                  onChanged: p.push ? (v) => change({key: v}) : null,
                ),
            ],
          ),
          GroupCard(
            label: 'Quiet hours',
            footer: 'Notifications still arrive, silently.',
            children: [
              SwitchTile(icon: DueIcons.quiet, title: 'Quiet hours', value: p.quietHours, onChanged: (v) => change({'quietHours': v})),
              if (p.quietHours) ...[
                SettingTile(icon: DueIcons.quiet, title: 'From ${p.quietStart}', subtitle: 'IST', onTap: () => _time('quietStart', p.quietStart)),
                SettingTile(icon: DueIcons.clock, title: 'Until ${p.quietEnd}', subtitle: 'IST', onTap: () => _time('quietEnd', p.quietEnd)),
              ],
            ],
          ),
          const SizedBox(height: 20),
          DueButton(label: 'Send a test notification', icon: DueIcons.send, variant: Variant.tonal, expand: true, onPressed: _test),
          if (kDebugMode) ...[
            const SizedBox(height: 8),
            DueButton(
              label: 'Simulate an update push (debug)',
              variant: Variant.ghost,
              expand: true,
              onPressed: () => services.notifier.handlePush({'type': 'activity'}, services.api),
            ),
          ],
        ],
      ],
    );
  }
}
