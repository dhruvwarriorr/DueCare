import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/deadline.dart';
import '../core/ist.dart';
import 'theme.dart';

enum Variant { primary, outline, ghost, destructive, tonal }

/// The app's buttons: Material buttons in DueCare's colours.
class DueButton extends StatelessWidget {
  const DueButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.variant = Variant.primary,
    this.icon,
    this.small = false,
    this.expand = false,
  });

  final String label;
  final VoidCallback? onPressed;
  final Variant variant;
  final IconData? icon;
  final bool small;
  final bool expand;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final size = small ? const Size(40, 40) : null;
    final pad = small ? const EdgeInsets.symmetric(horizontal: 14) : null;
    final text = Text(
      label,
      overflow: TextOverflow.ellipsis,
      style: small ? const TextStyle(fontSize: 13.5) : null,
    );
    final iconWidget = icon == null ? null : Icon(icon, size: small ? 17 : 19);
    final Widget button = switch (variant) {
      Variant.primary || Variant.destructive || Variant.tonal => () {
        final style = FilledButton.styleFrom(
          minimumSize: size,
          padding: pad,
          backgroundColor: switch (variant) {
            Variant.destructive => c.bad,
            Variant.tonal => c.inkTint,
            _ => null,
          },
          foregroundColor: switch (variant) {
            Variant.destructive => c.onBad,
            Variant.tonal => c.graphite,
            _ => null,
          },
        );
        return iconWidget == null
            ? FilledButton(onPressed: onPressed, style: style, child: text)
            : FilledButton.icon(
                onPressed: onPressed,
                style: style,
                icon: iconWidget,
                label: text,
              );
      }(),
      Variant.outline => () {
        final style = OutlinedButton.styleFrom(minimumSize: size, padding: pad);
        return iconWidget == null
            ? OutlinedButton(onPressed: onPressed, style: style, child: text)
            : OutlinedButton.icon(
                onPressed: onPressed,
                style: style,
                icon: iconWidget,
                label: text,
              );
      }(),
      Variant.ghost => () {
        final style = TextButton.styleFrom(minimumSize: size, padding: pad);
        return iconWidget == null
            ? TextButton(onPressed: onPressed, style: style, child: text)
            : TextButton.icon(
                onPressed: onPressed,
                style: style,
                icon: iconWidget,
                label: text,
              );
      }(),
    };
    return expand ? SizedBox(width: double.infinity, child: button) : button;
  }
}

/// The oval answer-sheet bubble: DueCare's mark for "done" and for choices.
class Bubble extends StatelessWidget {
  const Bubble({
    super.key,
    this.fill,
    this.stroke,
    this.small = false,
    this.child,
  });

  final Color? fill;
  final Color? stroke;
  final bool small;
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return AnimatedContainer(
      duration: const Duration(milliseconds: 180),
      width: small ? 18 : 24,
      height: small ? 13 : 17,
      alignment: Alignment.center,
      decoration: ShapeDecoration(
        color: fill ?? c.sheet,
        shape: StadiumBorder(
          side: BorderSide(color: stroke ?? c.inkLine, width: 1.6),
        ),
      ),
      child: child,
    );
  }
}

/// A small label above data, in the brand's printed caps.
class Printed extends StatelessWidget {
  const Printed(this.text, {super.key, this.color, this.size = 11.5});

  final String text;
  final Color? color;
  final double size;

  @override
  Widget build(BuildContext context) => Text(
    text.toUpperCase(),
    style: printed(context, color: color, size: size),
  );
}

({Color bg, Color fg, Color line}) statusColors(
  BuildContext context,
  String status,
) {
  final c = Palette.of(context);
  return switch (status) {
    'completed' => (bg: c.good, fg: c.onGood, line: c.good),
    'missed' => (bg: c.badTint, fg: c.badText, line: c.bad),
    'overdue' => (bg: c.bad, fg: c.onBad, line: c.bad),
    _ => (bg: c.due, fg: c.onDue, line: c.dueLine),
  };
}

/// Status chip: yellow due, green done, red missed (struck through), always with its word.
class StatusPill extends StatelessWidget {
  const StatusPill(this.status, {super.key});

  final String status;

  @override
  Widget build(BuildContext context) {
    final s = statusColors(context, status);
    return Container(
      height: 24,
      padding: const EdgeInsets.symmetric(horizontal: 9),
      decoration: ShapeDecoration(
        color: s.bg,
        shape: StadiumBorder(side: BorderSide(color: s.line)),
      ),
      // Sized to its word, wherever it is placed.
      child: Center(
        widthFactor: 1,
        child: Text(
          statusWord(status),
          style: TextStyle(
            color: s.fg,
            fontSize: 12.5,
            fontWeight: FontWeight.w800,
            decoration: status == 'missed' ? TextDecoration.lineThrough : null,
            decorationColor: s.fg,
          ),
        ),
      ),
    );
  }
}

/// A plain rounded tag: "test", "high priority".
class Tag extends StatelessWidget {
  const Tag(this.text, {super.key, this.icon});

  final String text;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Container(
      height: 24,
      padding: const EdgeInsets.symmetric(horizontal: 9),
      decoration: ShapeDecoration(
        color: c.inkWash,
        shape: StadiumBorder(side: BorderSide(color: c.inkRule)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 13, color: c.ink),
            const SizedBox(width: 4),
          ],
          Flexible(
            child: Text(
              text,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: 12.5,
                fontWeight: FontWeight.w700,
                color: c.graphite,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// A rounded card on the paper ground.
class Panel extends StatelessWidget {
  const Panel({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(18),
    this.hatched = false,
    this.margin,
    this.color,
  });

  final Widget child;
  final EdgeInsets padding;
  final EdgeInsets? margin;
  final Color? color;

  /// Waiting for the student's decision: drawn with the "do not write" hatch.
  final bool hatched;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final body = Padding(padding: padding, child: child);
    return Padding(
      padding: margin ?? EdgeInsets.zero,
      child: Material(
        color: color ?? c.sheet,
        clipBehavior: Clip.antiAlias,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(Radii.card),
          side: hatched ? BorderSide(color: c.inkLine) : BorderSide.none,
        ),
        child: hatched
            ? CustomPaint(painter: HatchPainter(c.inkWash), child: body)
            : body,
      ),
    );
  }
}

/// The -45° "do not write" hatch.
class HatchPainter extends CustomPainter {
  HatchPainter(this.color);

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..strokeWidth = 3;
    canvas.save();
    canvas.clipRect(Offset.zero & size);
    for (double x = -size.height; x < size.width; x += 9) {
      canvas.drawLine(
        Offset(x, 0),
        Offset(x + size.height, size.height),
        paint,
      );
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(HatchPainter old) => old.color != color;
}

/// A screen with a large collapsing title, pull to refresh and a padded list of content.
class PageScaffold extends StatelessWidget {
  const PageScaffold({
    super.key,
    required this.title,
    this.subtitle,
    this.actions = const [],
    this.children = const [],
    this.slivers,
    this.onRefresh,
    this.floatingActionButton,
    this.bottomBar,
    this.leading,
    this.bottomPadding = 32,
  });

  final String title;
  final String? subtitle;
  final List<Widget> actions;
  final List<Widget> children;
  final List<Widget>? slivers;
  final Future<void> Function()? onRefresh;
  final Widget? floatingActionButton;
  final Widget? bottomBar;
  final Widget? leading;
  final double bottomPadding;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final scroll = CustomScrollView(
      physics: const AlwaysScrollableScrollPhysics(
        parent: BouncingScrollPhysics(),
      ),
      slivers: [
        SliverAppBar.large(
          title: Text(title, style: display(context, 30)),
          leading: leading,
          actions: [...actions, const SizedBox(width: 6)],
          backgroundColor: c.paper,
          surfaceTintColor: Colors.transparent,
        ),
        if (subtitle != null)
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
              child: Text(
                subtitle!,
                style: TextStyle(
                  color: c.graphite2,
                  fontSize: 14.5,
                  height: 1.4,
                ),
              ),
            ),
          ),
        ...?slivers,
        if (children.isNotEmpty)
          SliverPadding(
            padding: EdgeInsets.fromLTRB(16, 4, 16, bottomPadding),
            sliver: SliverList.list(children: children),
          ),
      ],
    );
    return Scaffold(
      body: onRefresh == null
          ? scroll
          : RefreshIndicator(
              onRefresh: onRefresh!,
              edgeOffset: 120,
              child: scroll,
            ),
      floatingActionButton: floatingActionButton,
      bottomNavigationBar: bottomBar,
    );
  }
}

/// A heading inside a page, as a settings group label.
class SectionLabel extends StatelessWidget {
  const SectionLabel(this.text, {super.key, this.trailing, this.top = 22});

  final String text;
  final Widget? trailing;
  final double top;

  @override
  Widget build(BuildContext context) => Padding(
    padding: EdgeInsets.fromLTRB(4, top, 4, 8),
    child: Row(
      children: [
        Expanded(
          child: Text(
            text,
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w800,
              color: Palette.of(context).ink,
            ),
          ),
        ),
        ?trailing,
      ],
    ),
  );
}

/// A rounded group of rows, separated by hairlines.
class GroupCard extends StatelessWidget {
  const GroupCard({super.key, required this.children, this.label, this.footer});

  final List<Widget> children;
  final String? label;
  final String? footer;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (label != null) SectionLabel(label!),
        // A Material surface, so rows show their touch ripples.
        Material(
          color: c.sheet,
          borderRadius: BorderRadius.circular(Radii.card),
          clipBehavior: Clip.antiAlias,
          child: Column(
            children: [
              for (final (i, child) in children.indexed) ...[
                if (i > 0)
                  Divider(
                    height: 1,
                    indent: 16,
                    endIndent: 16,
                    color: c.inkRule,
                  ),
                child,
              ],
            ],
          ),
        ),
        if (footer != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(6, 8, 6, 0),
            child: Text(
              footer!,
              style: TextStyle(fontSize: 13, color: c.graphite2, height: 1.4),
            ),
          ),
      ],
    );
  }
}

/// A settings-style row: an icon in a tinted tile, a title, an optional subtitle and trailing.
class SettingTile extends StatelessWidget {
  const SettingTile({
    super.key,
    this.icon,
    required this.title,
    this.subtitle,
    this.trailing,
    this.onTap,
    this.danger = false,
  });

  final IconData? icon;
  final String title;
  final String? subtitle;
  final Widget? trailing;
  final VoidCallback? onTap;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return ListTile(
      onTap: onTap,
      leading: icon == null
          ? null
          : Container(
              width: 38,
              height: 38,
              decoration: BoxDecoration(
                color: danger ? c.badTint : c.inkWash,
                borderRadius: BorderRadius.circular(11),
              ),
              child: Icon(icon, size: 21, color: danger ? c.bad : c.ink),
            ),
      title: Text(title, style: danger ? TextStyle(color: c.bad) : null),
      subtitle: subtitle == null ? null : Text(subtitle!),
      trailing:
          trailing ??
          (onTap == null
              ? null
              : Icon(Icons.chevron_right, color: c.graphite2)),
    );
  }
}

/// A switch row in a settings group.
class SwitchTile extends StatelessWidget {
  const SwitchTile({
    super.key,
    required this.title,
    this.subtitle,
    required this.value,
    required this.onChanged,
    this.icon,
  });

  final String title;
  final String? subtitle;
  final bool value;
  final ValueChanged<bool>? onChanged;
  final IconData? icon;

  @override
  Widget build(BuildContext context) => SettingTile(
    icon: icon,
    title: title,
    subtitle: subtitle,
    onTap: onChanged == null ? null : () => onChanged!(!value),
    trailing: Switch(value: value, onChanged: onChanged),
  );
}

class Avatar extends StatelessWidget {
  const Avatar(this.initial, {super.key, this.size = 44});

  final String initial;
  final double size;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(color: c.inkTint, shape: BoxShape.circle),
      child: Text(
        initial.toUpperCase(),
        style: display(context, size * 0.42, color: c.ink),
      ),
    );
  }
}

/// A short page introduction that does not need a full heading.
class SectionHeader extends StatelessWidget {
  const SectionHeader({
    super.key,
    required this.title,
    this.subtitle,
    this.actions = const [],
  });

  final String title;
  final String? subtitle;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(0, 4, 0, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: display(context, 24)),
          if (subtitle != null) ...[
            const SizedBox(height: 4),
            Text(
              subtitle!,
              style: TextStyle(color: c.graphite2, fontSize: 14, height: 1.4),
            ),
          ],
          if (actions.isNotEmpty) ...[
            const SizedBox(height: 12),
            Wrap(spacing: 8, runSpacing: 8, children: actions),
          ],
        ],
      ),
    );
  }
}

/// An error answer, with an optional retry.
class ErrorNotice extends StatelessWidget {
  const ErrorNotice(this.error, {super.key, this.retry});

  final Object? error;
  final VoidCallback? retry;

  @override
  Widget build(BuildContext context) {
    if (error == null) return const SizedBox.shrink();
    final c = Palette.of(context);
    final message = error is ApiError
        ? (error as ApiError).message
        : 'Something went wrong. Please try again';
    final fields = error is ApiError
        ? (error as ApiError).fields
        : const <String, String>{};
    final offline = error is ApiError && (error as ApiError).unreachable;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: 8),
      padding: const EdgeInsets.fromLTRB(14, 12, 8, 12),
      decoration: BoxDecoration(
        color: c.badTint,
        borderRadius: BorderRadius.circular(Radii.medium),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            offline ? Icons.cloud_off : Icons.error_outline,
            color: c.badText,
            size: 20,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  message,
                  style: TextStyle(
                    color: c.badText,
                    fontWeight: FontWeight.w600,
                    fontSize: 14,
                  ),
                ),
                for (final e in fields.entries)
                  Text(
                    '${e.key}: ${e.value}',
                    style: TextStyle(color: c.badText, fontSize: 13),
                  ),
              ],
            ),
          ),
          if (retry != null)
            TextButton(onPressed: retry, child: const Text('Retry')),
        ],
      ),
    );
  }
}

class Notice extends StatelessWidget {
  const Notice(this.text, {super.key, this.warn = false, this.icon});

  final String text;
  final bool warn;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: warn ? c.dueTint : c.inkWash,
        borderRadius: BorderRadius.circular(Radii.medium),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            icon ?? (warn ? Icons.warning_amber_rounded : Icons.info_outline),
            size: 20,
            color: warn ? c.dueText : c.ink,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              text,
              style: TextStyle(fontSize: 14, color: c.graphite, height: 1.4),
            ),
          ),
        ],
      ),
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.icon,
    required this.title,
    required this.body,
    this.action,
  });

  final IconData icon;
  final String title;
  final String body;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 36),
      child: Column(
        children: [
          Container(
            width: 72,
            height: 72,
            decoration: BoxDecoration(color: c.inkWash, shape: BoxShape.circle),
            child: Icon(icon, size: 32, color: c.ink),
          ),
          const SizedBox(height: 16),
          Text(title, textAlign: TextAlign.center, style: display(context, 20)),
          const SizedBox(height: 6),
          Text(
            body,
            textAlign: TextAlign.center,
            style: TextStyle(color: c.graphite2, fontSize: 14.5, height: 1.4),
          ),
          if (action != null) ...[const SizedBox(height: 18), action!],
        ],
      ),
    );
  }
}

class Loading extends StatelessWidget {
  const Loading(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 28),
    child: Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        const SizedBox(
          width: 18,
          height: 18,
          child: CircularProgressIndicator(strokeWidth: 2.4),
        ),
        const SizedBox(width: 12),
        Flexible(
          child: Text(
            text,
            style: TextStyle(color: Palette.of(context).graphite2),
          ),
        ),
      ],
    ),
  );
}

/// A label above its control, with an inline error and help.
class Field extends StatelessWidget {
  const Field({
    super.key,
    required this.label,
    required this.child,
    this.error,
    this.help,
  });

  final String label;
  final Widget child;
  final String? error;
  final String? help;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(left: 4, bottom: 6),
            child: Text(
              label,
              style: TextStyle(
                fontSize: 13.5,
                fontWeight: FontWeight.w700,
                color: c.graphite2,
              ),
            ),
          ),
          child,
          if (error != null)
            Padding(
              padding: const EdgeInsets.only(left: 4, top: 4),
              child: Text(
                error!,
                style: TextStyle(
                  color: c.bad,
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          if (help != null)
            Padding(
              padding: const EdgeInsets.only(left: 4, top: 4),
              child: Text(
                help!,
                style: TextStyle(color: c.graphite2, fontSize: 13),
              ),
            ),
        ],
      ),
    );
  }
}

/// A filled field that opens a sheet of choices.
class SelectField<T> extends StatelessWidget {
  const SelectField({
    super.key,
    required this.value,
    required this.options,
    required this.onChanged,
    this.placeholder = 'Choose…',
    this.title,
    this.enabled = true,
    this.icon,
  });

  final T? value;
  final List<(T, String)> options;
  final ValueChanged<T> onChanged;
  final String placeholder;
  final String? title;
  final bool enabled;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final current = options.where((o) => o.$1 == value).firstOrNull;
    return Opacity(
      opacity: enabled ? 1 : 0.5,
      child: Material(
        color: Theme.of(context).colorScheme.surfaceContainer,
        borderRadius: BorderRadius.circular(Radii.medium),
        child: InkWell(
          borderRadius: BorderRadius.circular(Radii.medium),
          onTap: enabled ? () => _open(context) : null,
          child: Container(
            constraints: const BoxConstraints(minHeight: 52),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            child: Row(
              children: [
                if (icon != null) ...[
                  Icon(icon, size: 20, color: c.ink),
                  const SizedBox(width: 12),
                ],
                Expanded(
                  child: Text(
                    current?.$2 ?? placeholder,
                    style: TextStyle(
                      fontSize: 15.5,
                      color: current == null ? c.graphite2 : c.graphite,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ),
                Icon(Icons.unfold_more, color: c.graphite2, size: 20),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _open(BuildContext context) async {
    final picked = await pick<T>(
      context,
      title: title,
      options: options,
      value: value,
    );
    if (picked != null) onChanged(picked.$1);
  }
}

/// A bottom sheet of choices; returns the chosen value in a record (so null can be chosen).
Future<(T,)?> pick<T>(
  BuildContext context, {
  String? title,
  required List<(T, String)> options,
  T? value,
}) {
  return showModalBottomSheet<(T,)>(
    context: context,
    isScrollControlled: true,
    builder: (context) {
      final c = Palette.of(context);
      return SafeArea(
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxHeight: MediaQuery.sizeOf(context).height * 0.75,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (title != null)
                Padding(
                  padding: const EdgeInsets.fromLTRB(24, 0, 24, 8),
                  child: Text(title, style: display(context, 22)),
                ),
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  padding: const EdgeInsets.only(bottom: 12),
                  children: [
                    for (final o in options)
                      ListTile(
                        onTap: () => Navigator.pop(context, (o.$1,)),
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 24,
                        ),
                        leading: Bubble(
                          fill: o.$1 == value ? c.graphite : null,
                          stroke: o.$1 == value ? c.graphite : null,
                        ),
                        title: Text(
                          o.$2,
                          style: TextStyle(
                            fontWeight: o.$1 == value
                                ? FontWeight.w800
                                : FontWeight.w500,
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
    },
  );
}

/// A segmented choice of a few options.
class BubbleChoice<T> extends StatelessWidget {
  const BubbleChoice({
    super.key,
    required this.value,
    required this.options,
    required this.onChanged,
  });

  final T? value;
  final List<(T, String)> options;
  final ValueChanged<T>? onChanged;

  @override
  Widget build(BuildContext context) => SizedBox(
    width: double.infinity,
    child: SegmentedButton<T>(
      segments: [
        for (final o in options)
          ButtonSegment(
            value: o.$1,
            label: Text(o.$2, textAlign: TextAlign.center),
          ),
      ],
      selected: {?value},
      emptySelectionAllowed: value == null,
      showSelectedIcon: false,
      onSelectionChanged: onChanged == null
          ? null
          : (s) => s.isEmpty ? null : onChanged!(s.first),
    ),
  );
}

/// Date and optional time fields holding IST values ("YYYY-MM-DD" and "HH:MM").
class DateField extends StatelessWidget {
  const DateField({
    super.key,
    required this.value,
    required this.onChanged,
    this.placeholder = 'Choose a date',
  });

  final String value;
  final ValueChanged<String> onChanged;
  final String placeholder;

  @override
  Widget build(BuildContext context) => _PickerBox(
    text: value.isEmpty
        ? placeholder
        : '${weekdayNames[weekdayOf(value) - 1].substring(0, 3)}, ${formatDay(value, withYear: true)}',
    empty: value.isEmpty,
    icon: Icons.event_outlined,
    onClear: value.isEmpty ? null : () => onChanged(''),
    onTap: () async {
      final picked = await pickDate(context, value);
      if (picked != null) onChanged(picked);
    },
  );
}

Future<String?> pickDate(BuildContext context, String value) async {
  final initial = DateTime.parse(value.isEmpty ? todayKey() : value);
  final picked = await showDatePicker(
    context: context,
    initialDate: initial,
    firstDate: DateTime(2020),
    lastDate: DateTime(2100),
  );
  if (picked == null) return null;
  return '${picked.year}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}';
}

class TimeField extends StatelessWidget {
  const TimeField({
    super.key,
    required this.value,
    required this.onChanged,
    this.enabled = true,
    this.placeholder = 'Add a time',
  });

  final String value;
  final ValueChanged<String> onChanged;
  final bool enabled;
  final String placeholder;

  @override
  Widget build(BuildContext context) => Opacity(
    opacity: enabled ? 1 : 0.5,
    child: _PickerBox(
      text: value.isEmpty ? placeholder : value,
      empty: value.isEmpty,
      icon: Icons.schedule,
      onClear: value.isEmpty || !enabled ? null : () => onChanged(''),
      onTap: !enabled
          ? null
          : () async {
              final picked = await pickTime(context, value);
              if (picked != null) onChanged(picked);
            },
    ),
  );
}

Future<String?> pickTime(BuildContext context, String value) async {
  final parts = value.isEmpty
      ? [23, 59]
      : value.split(':').map(int.parse).toList();
  final picked = await showTimePicker(
    context: context,
    initialTime: TimeOfDay(hour: parts[0], minute: parts[1]),
    builder: (context, child) => MediaQuery(
      data: MediaQuery.of(context).copyWith(alwaysUse24HourFormat: true),
      child: child!,
    ),
  );
  return picked == null ? null : clock(picked.hour * 60 + picked.minute);
}

class _PickerBox extends StatelessWidget {
  const _PickerBox({
    required this.text,
    required this.empty,
    required this.icon,
    required this.onTap,
    this.onClear,
  });

  final String text;
  final bool empty;
  final IconData icon;
  final VoidCallback? onTap;
  final VoidCallback? onClear;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Material(
      color: Theme.of(context).colorScheme.surfaceContainer,
      borderRadius: BorderRadius.circular(Radii.medium),
      child: InkWell(
        borderRadius: BorderRadius.circular(Radii.medium),
        onTap: onTap,
        child: Container(
          constraints: const BoxConstraints(minHeight: 52),
          padding: const EdgeInsets.only(left: 16),
          child: Row(
            children: [
              Icon(icon, size: 20, color: c.ink),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  text,
                  style: display(
                    context,
                    15.5,
                    weight: FontWeight.w600,
                    color: empty ? c.graphite2 : c.graphite,
                  ),
                ),
              ),
              if (onClear != null)
                IconButton(
                  onPressed: onClear,
                  icon: Icon(Icons.close, size: 18, color: c.graphite2),
                  tooltip: 'Clear',
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The "bubble heart" mark: a rose diamond with a yellow (due) and a green (done) bubble.
class Logo extends StatelessWidget {
  const Logo({super.key, this.size = 28, this.wordmark = true});

  final double size;
  final bool wordmark;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        CustomPaint(
          size: Size.square(size),
          painter: _MarkPainter(c.ink, c.due, c.good),
        ),
        if (wordmark) ...[
          SizedBox(width: size * 0.32),
          Text('DueCare', style: display(context, size * 0.9)),
        ],
      ],
    );
  }
}

class _MarkPainter extends CustomPainter {
  _MarkPainter(this.ink, this.due, this.good);

  final Color ink, due, good;

  @override
  void paint(Canvas canvas, Size size) {
    // Drawn in the web mark's own coordinates (apps/web/src/app/icon.svg, viewBox 5 12 70 70).
    Offset pt(double x, double y) =>
        Offset((x - 5) / 70 * size.width, (y - 12) / 70 * size.height);
    Path diamond(List<(double, double)> points) =>
        Path()..addPolygon([for (final (x, y) in points) pt(x, y)], true);
    final rose = Paint()..color = ink;
    canvas.drawPath(diamond([(40, 22), (68, 50), (40, 78), (12, 50)]), rose);
    canvas.drawOval(
      Rect.fromPoints(pt(6, 16), pt(46, 56)),
      Paint()..color = due,
    );
    canvas.drawOval(
      Rect.fromPoints(pt(34, 16), pt(74, 56)),
      Paint()..color = good,
    );
    canvas.drawPath(diamond([(40, 36), (54, 50), (40, 64), (26, 50)]), rose);
  }

  @override
  bool shouldRepaint(_MarkPainter old) =>
      old.ink != ink || old.due != due || old.good != good;
}

/// Shown when the server cannot be reached: what is on screen is the saved copy.
class OfflineBanner extends StatelessWidget {
  const OfflineBanner({super.key, required this.savedAt});

  final DateTime? savedAt;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final fg = Theme.of(context).brightness == Brightness.dark
        ? c.graphite
        : c.sheet;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      color: c.band,
      child: Row(
        children: [
          Icon(Icons.cloud_off, size: 18, color: fg),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              'Offline${savedAt != null ? ' · showing what was saved ${formatTime(savedAt!.toIso8601String())}' : ''}',
              style: TextStyle(
                color: fg,
                fontSize: 13.5,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

void toast(
  BuildContext context,
  String message, {
  String? action,
  VoidCallback? onAction,
}) {
  final messenger = ScaffoldMessenger.of(context);
  messenger.hideCurrentSnackBar();
  messenger.showSnackBar(
    SnackBar(
      content: Text(message),
      duration: Duration(seconds: action == null ? 3 : 5),
      action: action == null
          ? null
          : SnackBarAction(label: action, onPressed: onAction ?? () {}),
    ),
  );
}

/// Confirm a destructive step.
Future<bool> confirm(
  BuildContext context, {
  required String title,
  required String body,
  required String action,
  String cancel = 'Cancel',
}) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(title, style: display(context, 22)),
      content: Text(
        body,
        style: TextStyle(color: Palette.of(context).graphite2, height: 1.45),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, false),
          child: Text(cancel),
        ),
        FilledButton(
          style: FilledButton.styleFrom(
            backgroundColor: Palette.of(context).bad,
            foregroundColor: Palette.of(context).onBad,
          ),
          onPressed: () => Navigator.pop(context, true),
          child: Text(action),
        ),
      ],
    ),
  );
  return ok ?? false;
}
