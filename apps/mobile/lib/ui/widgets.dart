import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/deadline.dart';
import '../core/ist.dart';
import 'theme.dart';

enum Variant { primary, outline, ghost, destructive }

/// Square, compact buttons (DESIGN.md › Buttons). Primary is graphite; destructive is rose.
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
    final (bg, fg, border) = switch (variant) {
      Variant.primary => (c.graphite, c.onGraphite, c.graphite),
      Variant.outline => (c.sheet, c.graphite, c.graphite),
      Variant.ghost => (Colors.transparent, c.graphite, Colors.transparent),
      Variant.destructive => (c.ink, c.sheet, c.ink),
    };
    final disabled = onPressed == null;
    final child = Row(
      mainAxisSize: expand ? MainAxisSize.max : MainAxisSize.min,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        if (icon != null) ...[Icon(icon, size: small ? 15 : 17, color: fg), const SizedBox(width: 8)],
        Flexible(
          child: Text(
            label,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(fontWeight: FontWeight.w600, fontSize: small ? 13 : 14, color: fg),
          ),
        ),
      ],
    );
    return Opacity(
      opacity: disabled ? 0.5 : 1,
      child: Material(
        color: bg,
        shape: Border.all(color: border),
        child: InkWell(
          onTap: onPressed,
          hoverColor: variant == Variant.primary ? c.ink : c.inkWash,
          child: ConstrainedBox(
            constraints: BoxConstraints(minHeight: small ? 36 : 44),
            child: Padding(padding: EdgeInsets.symmetric(horizontal: small ? 12 : 18), child: Center(widthFactor: expand ? null : 1, heightFactor: 1, child: child)),
          ),
        ),
      ),
    );
  }
}

/// The oval answer-sheet bubble, the only curve in the system.
class Bubble extends StatelessWidget {
  const Bubble({super.key, this.fill, this.stroke, this.small = false, this.child});

  final Color? fill;
  final Color? stroke;
  final bool small;
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Container(
      width: small ? 14 : 20,
      height: small ? 10 : 13,
      alignment: Alignment.center,
      decoration: ShapeDecoration(
        color: fill ?? c.sheet,
        shape: StadiumBorder(side: BorderSide(color: stroke ?? c.inkLine, width: 1.2)),
      ),
      child: child,
    );
  }
}

/// Printed caps label: field names, day names, row labels and statuses.
class Printed extends StatelessWidget {
  const Printed(this.text, {super.key, this.color, this.size = 11.5});

  final String text;
  final Color? color;
  final double size;

  @override
  Widget build(BuildContext context) => Text(text.toUpperCase(), style: printed(context, color: color, size: size));
}

({Color bg, Color fg, Color line}) statusColors(BuildContext context, String status) {
  final c = Palette.of(context);
  return switch (status) {
    'completed' => (bg: c.good, fg: c.onGood, line: c.good),
    'missed' => (bg: c.badTint, fg: c.badText, line: c.bad),
    'overdue' => (bg: c.bad, fg: c.onBad, line: c.bad),
    _ => (bg: c.due, fg: c.onDue, line: c.dueLine),
  };
}

/// Status pill: yellow due, green done, red-tint struck-through missed (the Status Colour Rule).
class StatusPill extends StatelessWidget {
  const StatusPill(this.status, {super.key});

  final String status;

  @override
  Widget build(BuildContext context) {
    final s = statusColors(context, status);
    return Container(
      height: 26,
      padding: const EdgeInsets.symmetric(horizontal: 10),
      alignment: Alignment.center,
      decoration: BoxDecoration(color: s.bg, border: Border.all(color: s.line)),
      child: Text(
        statusWord(status).toUpperCase(),
        style: printed(context, color: s.fg, size: 12).copyWith(
          decoration: status == 'missed' ? TextDecoration.lineThrough : null,
          decorationColor: s.fg,
        ),
      ),
    );
  }
}

/// A plain tag beside a status: "assignment", "high priority".
class Tag extends StatelessWidget {
  const Tag(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Container(
      height: 26,
      padding: const EdgeInsets.symmetric(horizontal: 10),
      alignment: Alignment.center,
      decoration: BoxDecoration(color: c.inkWash, border: Border.all(color: c.inkRule)),
      child: Text(text.toUpperCase(), style: printed(context, color: c.graphite, size: 11.5)),
    );
  }
}

/// A working surface: sheet white framed in Rose Line.
class Panel extends StatelessWidget {
  const Panel({super.key, required this.child, this.padding = const EdgeInsets.all(18), this.hatched = false, this.margin});

  final Widget child;
  final EdgeInsets padding;
  final EdgeInsets? margin;

  /// Waiting for the student's review (the Hatch Rule).
  final bool hatched;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Container(
      margin: margin,
      decoration: BoxDecoration(color: c.sheet, border: Border.all(color: c.inkLine)),
      child: hatched
          ? CustomPaint(painter: HatchPainter(c.inkTint), child: Padding(padding: padding, child: child))
          : Padding(padding: padding, child: child),
    );
  }
}

/// The -45° "do not write" hatch: Rose Tint 2px every 7px.
class HatchPainter extends CustomPainter {
  HatchPainter(this.color);

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..strokeWidth = 2;
    canvas.save();
    canvas.clipRect(Offset.zero & size);
    for (double x = -size.height; x < size.width; x += 7) {
      canvas.drawLine(Offset(x, 0), Offset(x + size.height, size.height), paint);
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(HatchPainter old) => old.color != color;
}

/// A page heading with its explanation, as the web's section bars.
class SectionHeader extends StatelessWidget {
  const SectionHeader({super.key, required this.title, this.subtitle, this.actions = const []});

  final String title;
  final String? subtitle;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(0, 4, 0, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: display(context, 30)),
          if (subtitle != null) ...[
            const SizedBox(height: 6),
            Text(subtitle!, style: TextStyle(color: c.graphite2, fontSize: 14, height: 1.45)),
          ],
          if (actions.isNotEmpty) ...[const SizedBox(height: 12), Wrap(spacing: 8, runSpacing: 8, children: actions)],
        ],
      ),
    );
  }
}

/// An error answer in a rose frame on Rose Wash, with an optional retry.
class ErrorNotice extends StatelessWidget {
  const ErrorNotice(this.error, {super.key, this.retry});

  final Object? error;
  final VoidCallback? retry;

  @override
  Widget build(BuildContext context) {
    if (error == null) return const SizedBox.shrink();
    final c = Palette.of(context);
    final message = error is ApiError ? (error as ApiError).message : 'Something went wrong. Please try again';
    final fields = error is ApiError ? (error as ApiError).fields : const <String, String>{};
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: c.inkWash, border: Border.all(color: c.ink)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(message, style: TextStyle(color: c.ink, fontWeight: FontWeight.w600, fontSize: 14)),
          for (final e in fields.entries)
            Text('${e.key}: ${e.value}', style: TextStyle(color: c.ink, fontSize: 13)),
          if (retry != null) ...[
            const SizedBox(height: 8),
            DueButton(label: 'Try again', small: true, variant: Variant.outline, onPressed: retry),
          ],
        ],
      ),
    );
  }
}

class Notice extends StatelessWidget {
  const Notice(this.text, {super.key, this.warn = false});

  final String text;
  final bool warn;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: warn ? c.dueTint : c.inkWash, border: Border.all(color: warn ? c.dueLine : c.inkRule)),
      child: Text(text, style: TextStyle(fontSize: 14, color: warn ? c.graphite : c.graphite)),
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.icon, required this.title, required this.body, this.action});

  final IconData icon;
  final String title;
  final String body;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Panel(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 32),
      child: Column(
        children: [
          Icon(icon, size: 28, color: c.ink),
          const SizedBox(height: 10),
          Text(title, textAlign: TextAlign.center, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
          const SizedBox(height: 6),
          Text(body, textAlign: TextAlign.center, style: TextStyle(color: c.graphite2, fontSize: 14)),
          if (action != null) ...[const SizedBox(height: 14), action!],
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
        padding: const EdgeInsets.symmetric(vertical: 24),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
            const SizedBox(width: 10),
            Flexible(child: Text(text, style: TextStyle(color: Palette.of(context).graphite2))),
          ],
        ),
      );
}

/// A printed field label above its control, with an inline error.
class Field extends StatelessWidget {
  const Field({super.key, required this.label, required this.child, this.error, this.help});

  final String label;
  final Widget child;
  final String? error;
  final String? help;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Printed(label, size: 12),
          const SizedBox(height: 6),
          child,
          if (error != null) ...[
            const SizedBox(height: 4),
            Text(error!, style: TextStyle(color: c.ink, fontSize: 13, fontWeight: FontWeight.w600)),
          ],
          if (help != null) ...[
            const SizedBox(height: 4),
            Text(help!, style: TextStyle(color: c.graphite2, fontSize: 13)),
          ],
        ],
      ),
    );
  }
}

/// A square field that opens a sheet of bubble rows: empty rose bubbles for choices, a filled
/// graphite bubble for the current one (DESIGN.md › Select menus).
class SelectField<T> extends StatelessWidget {
  const SelectField({
    super.key,
    required this.value,
    required this.options,
    required this.onChanged,
    this.placeholder = 'Choose…',
    this.title,
    this.enabled = true,
  });

  final T? value;
  final List<(T, String)> options;
  final ValueChanged<T> onChanged;
  final String placeholder;
  final String? title;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    final current = options.where((o) => o.$1 == value).firstOrNull;
    return Opacity(
      opacity: enabled ? 1 : 0.5,
      child: InkWell(
        onTap: enabled ? () => _open(context) : null,
        child: Container(
          constraints: const BoxConstraints(minHeight: 44),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(color: c.sheet, border: Border.all(color: c.inkLine)),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  current?.$2 ?? placeholder,
                  style: TextStyle(fontSize: 15, color: current == null ? c.graphite2 : c.graphite),
                ),
              ),
              Icon(Icons.expand_more, color: c.ink, size: 20),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _open(BuildContext context) async {
    final picked = await showModalBottomSheet<(T,)>(
      context: context,
      isScrollControlled: true,
      builder: (context) => _SelectSheet<T>(title: title, options: options, value: value),
    );
    if (picked != null) onChanged(picked.$1);
  }
}

class _SelectSheet<T> extends StatelessWidget {
  const _SelectSheet({required this.title, required this.options, required this.value});

  final String? title;
  final List<(T, String)> options;
  final T? value;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * 0.7),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (title != null)
              Padding(padding: const EdgeInsets.fromLTRB(20, 16, 20, 8), child: Text(title!, style: display(context, 22))),
            Flexible(
              child: ListView(
                shrinkWrap: true,
                children: [
                  for (final o in options)
                    InkWell(
                      onTap: () => Navigator.pop(context, (o.$1,)),
                      child: Container(
                        constraints: const BoxConstraints(minHeight: 48),
                        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                        decoration: BoxDecoration(border: Border(bottom: BorderSide(color: c.inkRule))),
                        child: Row(
                          children: [
                            Bubble(fill: o.$1 == value ? c.graphite : null, stroke: o.$1 == value ? c.graphite : null),
                            const SizedBox(width: 12),
                            Expanded(child: Text(o.$2, style: const TextStyle(fontSize: 15))),
                          ],
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
  }
}

/// A row of ruled cells, each with a bubble and a caption (the OMR field).
class BubbleChoice<T> extends StatelessWidget {
  const BubbleChoice({super.key, required this.value, required this.options, required this.onChanged});

  final T? value;
  final List<(T, String)> options;
  final ValueChanged<T>? onChanged;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Container(
      decoration: BoxDecoration(border: Border.all(color: c.inkLine), color: c.sheet),
      child: IntrinsicHeight(
        child: Row(
          children: [
            for (final (i, o) in options.indexed)
              Expanded(
                child: InkWell(
                  onTap: onChanged == null ? null : () => onChanged!(o.$1),
                  child: Container(
                    constraints: const BoxConstraints(minHeight: 44),
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 8),
                    decoration: BoxDecoration(border: i == 0 ? null : Border(left: BorderSide(color: c.inkRule))),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Bubble(fill: o.$1 == value ? c.graphite : null, stroke: o.$1 == value ? c.graphite : null),
                        const SizedBox(height: 4),
                        Text(o.$2, textAlign: TextAlign.center, style: TextStyle(fontSize: 13, fontWeight: o.$1 == value ? FontWeight.w700 : FontWeight.w500)),
                      ],
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// Date and optional time fields holding IST values ("YYYY-MM-DD" and "HH:MM").
class DateField extends StatelessWidget {
  const DateField({super.key, required this.value, required this.onChanged, this.placeholder = 'Choose a date'});

  final String value;
  final ValueChanged<String> onChanged;
  final String placeholder;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return _PickerBox(
      text: value.isEmpty ? placeholder : formatDay(value, withYear: true),
      empty: value.isEmpty,
      icon: Icons.calendar_today_outlined,
      onClear: value.isEmpty ? null : () => onChanged(''),
      onTap: () async {
        final today = todayKey();
        final initial = DateTime.parse(value.isEmpty ? today : value);
        final picked = await showDatePicker(
          context: context,
          initialDate: initial,
          firstDate: DateTime(2020),
          lastDate: DateTime(2100),
          builder: (context, child) => Theme(
            data: Theme.of(context).copyWith(colorScheme: Theme.of(context).colorScheme.copyWith(primary: c.graphite)),
            child: child!,
          ),
        );
        if (picked != null) {
          onChanged('${picked.year}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}');
        }
      },
    );
  }
}

class TimeField extends StatelessWidget {
  const TimeField({super.key, required this.value, required this.onChanged, this.enabled = true, this.placeholder = 'Add a time'});

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
                  final parts = value.isEmpty ? [23, 59] : value.split(':').map(int.parse).toList();
                  final picked = await showTimePicker(
                    context: context,
                    initialTime: TimeOfDay(hour: parts[0], minute: parts[1]),
                    builder: (context, child) => MediaQuery(
                      data: MediaQuery.of(context).copyWith(alwaysUse24HourFormat: true),
                      child: child!,
                    ),
                  );
                  if (picked != null) onChanged(clock(picked.hour * 60 + picked.minute));
                },
        ),
      );
}

class _PickerBox extends StatelessWidget {
  const _PickerBox({required this.text, required this.empty, required this.icon, required this.onTap, this.onClear});

  final String text;
  final bool empty;
  final IconData icon;
  final VoidCallback? onTap;
  final VoidCallback? onClear;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return InkWell(
      onTap: onTap,
      child: Container(
        constraints: const BoxConstraints(minHeight: 44),
        padding: const EdgeInsets.only(left: 12),
        decoration: BoxDecoration(color: c.sheet, border: Border.all(color: c.inkLine)),
        child: Row(
          children: [
            Icon(icon, size: 17, color: c.ink),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                text,
                style: display(context, 15, weight: FontWeight.w600, color: empty ? c.graphite2 : c.graphite),
              ),
            ),
            if (onClear != null)
              IconButton(onPressed: onClear, icon: Icon(Icons.close, size: 18, color: c.graphite2), tooltip: 'Clear'),
          ],
        ),
      ),
    );
  }
}

/// The "bubble heart" mark: a rose square on its point with a yellow (due) and a green (done)
/// bubble for lobes, and a small rose diamond restoring the centre.
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
        CustomPaint(size: Size.square(size), painter: _MarkPainter(c.ink, c.due, c.good)),
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
    Offset pt(double x, double y) => Offset((x - 5) / 70 * size.width, (y - 12) / 70 * size.height);
    Path diamond(List<(double, double)> points) => Path()..addPolygon([for (final (x, y) in points) pt(x, y)], true);
    final rose = Paint()..color = ink;
    canvas.drawPath(diamond([(40, 22), (68, 50), (40, 78), (12, 50)]), rose);
    canvas.drawOval(Rect.fromPoints(pt(6, 16), pt(46, 56)), Paint()..color = due);
    canvas.drawOval(Rect.fromPoints(pt(34, 16), pt(74, 56)), Paint()..color = good);
    canvas.drawPath(diamond([(40, 36), (54, 50), (40, 64), (26, 50)]), rose);
  }

  @override
  bool shouldRepaint(_MarkPainter old) => old.ink != ink || old.due != due || old.good != good;
}

/// Shown when the server cannot be reached: what is on screen is the saved copy.
class OfflineBanner extends StatelessWidget {
  const OfflineBanner({super.key, required this.savedAt});

  final DateTime? savedAt;

  @override
  Widget build(BuildContext context) {
    final c = Palette.of(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      color: c.band,
      child: Text(
        'Can’t reach DueCare right now'
        '${savedAt != null ? ' · showing what was saved at ${formatTime(savedAt!.toIso8601String())}' : ''}'
        '. Changes will need a connection.',
        style: TextStyle(color: Theme.of(context).brightness == Brightness.dark ? c.graphite : c.sheet, fontSize: 13),
      ),
    );
  }
}

void toast(BuildContext context, String message, {String? action, VoidCallback? onAction}) {
  final messenger = ScaffoldMessenger.of(context);
  messenger.hideCurrentSnackBar();
  messenger.showSnackBar(
    SnackBar(
      content: Text(message),
      duration: const Duration(seconds: 6),
      action: action == null ? null : SnackBarAction(label: action, onPressed: onAction ?? () {}),
    ),
  );
}

/// Confirm a destructive step in a square dialog with a graphite top rule.
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
      title: Text(title, style: display(context, 24)),
      content: Text(body),
      actions: [
        DueButton(label: cancel, variant: Variant.outline, onPressed: () => Navigator.pop(context, false)),
        DueButton(label: action, variant: Variant.destructive, onPressed: () => Navigator.pop(context, true)),
      ],
    ),
  );
  return ok ?? false;
}
