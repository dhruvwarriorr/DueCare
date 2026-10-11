import 'dart:math' as math;

import 'package:flutter/material.dart';

/// DueCare's own icons, drawn from the answer sheet: oval bubbles, ruled lines, a pencil and an
/// eraser. One 24-unit grid, one rounded 1.7 stroke; [DueIcon.filled] marks the selected state.
/// System controls (back, close, chevrons, overflow) stay Material so Android feels native.
enum DueIcons {
  week,
  tasks,
  review,
  more,
  add,
  activity,
  month,
  search,
  filter,
  sort,
  edit,
  erase,
  done,
  clock,
  event,
  subjects,
  sources,
  rules,
  notifications,
  profile,
  privacy,
  signOut,
  mail,
  classroom,
  upload,
  fresh,
  reopen,
  flag,
  send,
  quiet,
  link,
  offline,
  undated,
}

/// An icon from either family: a [DueIcons] glyph or a Material [IconData].
Widget glyph(Object icon, {double? size, Color? color, bool filled = false}) => switch (icon) {
      DueIcons i => DueIcon(i, size: size, color: color, filled: filled),
      IconData i => Icon(i, size: size, color: color),
      _ => throw ArgumentError('Not an icon: $icon'),
    };

class DueIcon extends StatelessWidget {
  const DueIcon(this.icon, {super.key, this.size, this.color, this.filled = false, this.semanticLabel});

  final DueIcons icon;
  final double? size;
  final Color? color;
  final bool filled;
  final String? semanticLabel;

  @override
  Widget build(BuildContext context) {
    final theme = IconTheme.of(context);
    final s = size ?? theme.size ?? 24;
    final c = color ?? theme.color ?? Colors.black;
    final paint = CustomPaint(size: Size.square(s), painter: _Glyph(icon, c, filled));
    return semanticLabel == null ? ExcludeSemantics(child: paint) : Semantics(label: semanticLabel, child: paint);
  }
}

class _Glyph extends CustomPainter {
  _Glyph(this.icon, this.color, this.filled);

  final DueIcons icon;
  final Color color;
  final bool filled;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 24);
    final stroke = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.7
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    final fill = Paint()..color = color;
    final hair = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.25
      ..strokeCap = StrokeCap.round;
    Rect oval(double cx, double cy, double w, double h) => Rect.fromCenter(center: Offset(cx, cy), width: w, height: h);
    void line(double x0, double y0, double x1, double y1, [Paint? p]) => canvas.drawLine(Offset(x0, y0), Offset(x1, y1), p ?? stroke);
    void bubble(double cx, double cy, double w, double h, {bool solid = false}) {
      final r = oval(cx, cy, w, h);
      if (solid) canvas.drawOval(r, fill);
      canvas.drawOval(r, stroke);
    }

    RRect sheet([double top = 4.5]) => RRect.fromLTRBR(3, top, 21, 19.5, const Radius.circular(3.4));
    // An arc of radius 7 around the centre, with an arrowhead at its end.
    void arrowArc(double start, double sweep) {
      final r = Rect.fromCircle(center: const Offset(12, 12), radius: 7);
      canvas.drawArc(r, start, sweep, false, stroke);
      final end = start + sweep;
      final tip = Offset(12 + 7 * math.cos(end), 12 + 7 * math.sin(end));
      final dir = sweep > 0 ? end + math.pi / 2 : end - math.pi / 2;
      for (final side in [-0.6, 0.6]) {
        final a = dir + math.pi + side;
        canvas.drawLine(tip, tip + Offset(math.cos(a), math.sin(a)) * 3.2, stroke);
      }
    }

    Path bell() => Path()
      ..moveTo(6, 16.5)
      ..lineTo(6, 11.5)
      ..cubicTo(6, 8.2, 8.7, 5.5, 12, 5.5)
      ..cubicTo(15.3, 5.5, 18, 8.2, 18, 11.5)
      ..lineTo(18, 16.5);

    switch (icon) {
      case DueIcons.week:
        final frame = sheet();
        if (filled) {
          canvas.save();
          canvas.clipRect(const Rect.fromLTRB(0, 0, 24, 9.5));
          canvas.drawRRect(frame, fill);
          canvas.restore();
        }
        canvas.drawRRect(frame, stroke);
        line(3, 9.5, 21, 9.5);
        // Day columns under the header rule, one deadline marked.
        line(9, 9.5, 9, 19.5, hair);
        line(15, 9.5, 15, 19.5, hair);
        bubble(12, 14.6, 3.6, 2.6, solid: filled);
      case DueIcons.tasks:
        for (final y in [6.0, 12.0, 18.0]) {
          bubble(5.3, y, 4.2, 3, solid: filled);
          line(10.2, y, 20.5, y);
        }
      case DueIcons.review:
        final r = oval(12, 12, 18.4, 11);
        canvas.saveLayer(const Rect.fromLTWH(0, 0, 24, 24), Paint());
        if (filled) canvas.drawOval(r, fill);
        canvas.drawOval(r, stroke);
        // The "do not write" hatch: waiting for the student's decision.
        canvas.save();
        canvas.clipPath(Path()..addOval(r.deflate(1.4)));
        final hatch = filled ? (Paint()
          ..blendMode = BlendMode.clear
          ..strokeWidth = 1.5
          ..strokeCap = StrokeCap.round) : hair;
        for (final x in [-2.0, 3.5, 9.0, 14.5]) {
          canvas.drawLine(Offset(x, 18), Offset(x + 12, 6), hatch);
        }
        canvas.restore();
        canvas.restore();
      case DueIcons.more:
        for (final (x, y) in [(7.2, 8.2), (16.8, 8.2), (7.2, 15.8), (16.8, 15.8)]) {
          bubble(x, y, 6.4, 4.6, solid: filled);
        }
      case DueIcons.add:
        line(12, 5, 12, 19);
        line(5, 12, 19, 12);
      case DueIcons.activity:
        if (filled) canvas.drawPath(bell()..close(), fill);
        canvas.drawPath(bell(), stroke);
        line(4.3, 16.5, 19.7, 16.5);
        line(12, 3.6, 12, 5.5);
        bubble(12, 19.6, 3.6, 1.9);
      case DueIcons.notifications:
        canvas.drawPath(bell(), stroke);
        line(4.3, 16.5, 19.7, 16.5);
        line(12, 3.6, 12, 5.5);
        bubble(12, 19.6, 3.6, 1.9);
        canvas.drawPath(Path()
          ..moveTo(3, 7.5)
          ..quadraticBezierTo(2, 10, 3, 12.5), stroke);
        canvas.drawPath(Path()
          ..moveTo(21, 7.5)
          ..quadraticBezierTo(22, 10, 21, 12.5), stroke);
      case DueIcons.month:
        canvas.drawRRect(sheet(), stroke);
        line(3, 9.5, 21, 9.5);
        // Ruled week rows, with one day marked.
        line(6.5, 13.2, 17.5, 13.2, hair);
        line(6.5, 16.6, 11.5, 16.6, hair);
        bubble(15.5, 16.6, 3.2, 2.1, solid: true);
      case DueIcons.event:
        canvas.drawRRect(sheet(), stroke);
        line(3, 9.5, 21, 9.5);
        line(8, 2.8, 8, 5.6);
        line(16, 2.8, 16, 5.6);
        bubble(15, 14.8, 4.2, 2.9, solid: true);
      case DueIcons.search:
        canvas.drawCircle(const Offset(10.5, 10.5), 6, stroke);
        line(15, 15, 20, 20);
      case DueIcons.filter:
        for (final (y, x) in [(7.0, 15.0), (12.0, 8.0), (17.0, 13.0)]) {
          bubble(x, y, 4.4, 3.2);
          line(3.5, y, x - 2.2, y);
          line(x + 2.2, y, 20.5, y);
        }
      case DueIcons.sort:
        line(4, 7, 20, 7);
        line(4, 12, 15, 12);
        line(4, 17, 10, 17);
      case DueIcons.edit:
        canvas.drawPath(Path()
          ..moveTo(15.3, 4.7)
          ..lineTo(19.3, 8.7)
          ..lineTo(8.6, 19.4)
          ..lineTo(4.6, 19.4)
          ..lineTo(4.6, 15.4)
          ..close(), stroke);
        line(13.1, 6.9, 17.1, 10.9);
      case DueIcons.erase:
        canvas.drawPath(Path()
          ..moveTo(3.8, 15.4)
          ..lineTo(12.8, 6.4)
          ..lineTo(19.6, 13.2)
          ..lineTo(13.4, 19.4)
          ..lineTo(7.8, 19.4)
          ..close(), stroke);
        line(8.4, 10.8, 15, 17.4);
        line(13.4, 19.4, 20.4, 19.4);
      case DueIcons.done:
        final r = oval(12, 12, 18.4, 11.6);
        final check = Path()
          ..moveTo(8.4, 12.2)
          ..lineTo(11, 14.6)
          ..lineTo(15.9, 9.6);
        if (filled) {
          canvas.saveLayer(const Rect.fromLTWH(0, 0, 24, 24), Paint());
          canvas.drawOval(r, fill);
          canvas.drawOval(r, stroke);
          canvas.drawPath(check, Paint()
            ..blendMode = BlendMode.clear
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1.9
            ..strokeCap = StrokeCap.round
            ..strokeJoin = StrokeJoin.round);
          canvas.restore();
        } else {
          canvas.drawOval(r, stroke);
          canvas.drawPath(check, stroke);
        }
      case DueIcons.clock:
        canvas.drawCircle(const Offset(12, 12), 8.2, stroke);
        canvas.drawPath(Path()
          ..moveTo(12, 7.6)
          ..lineTo(12, 12)
          ..lineTo(15, 13.8), stroke);
      case DueIcons.subjects:
        canvas.drawRRect(RRect.fromLTRBR(4.5, 3.5, 16, 17.5, const Radius.circular(2.2)), stroke);
        canvas.drawPath(Path()
          ..moveTo(8, 20.5)
          ..lineTo(16.5, 20.5)
          ..cubicTo(17.9, 20.5, 19, 19.4, 19, 18)
          ..lineTo(19, 7.5), stroke);
        line(7.6, 8, 12.9, 8, hair);
        line(7.6, 11, 12.9, 11, hair);
        line(7.6, 14, 10.8, 14, hair);
      case DueIcons.sources:
        arrowArc(-math.pi * 5 / 6, math.pi * 2 / 3);
        arrowArc(math.pi / 6, math.pi * 2 / 3);
      case DueIcons.reopen:
        arrowArc(-math.pi / 2 + 0.55, math.pi * 2 - 1.1);
      case DueIcons.rules:
        canvas.drawRRect(RRect.fromLTRBR(3, 4.6, 12.4, 9.4, const Radius.circular(2.4)), stroke);
        canvas.drawCircle(const Offset(10, 7), 1.35, fill);
        line(15, 7, 21, 7);
        canvas.drawRRect(RRect.fromLTRBR(3, 14.6, 12.4, 19.4, const Radius.circular(2.4)), stroke);
        canvas.drawCircle(const Offset(5.4, 17), 1.35, fill);
        line(15, 17, 21, 17);
      case DueIcons.profile:
        canvas.drawCircle(const Offset(12, 8.3), 3.6, stroke);
        canvas.drawPath(Path()
          ..moveTo(5, 19.8)
          ..cubicTo(5.6, 15.9, 8.4, 13.8, 12, 13.8)
          ..cubicTo(15.6, 13.8, 18.4, 15.9, 19, 19.8), stroke);
      case DueIcons.privacy:
        canvas.drawRRect(RRect.fromLTRBR(5, 10.5, 19, 20, const Radius.circular(2.4)), stroke);
        canvas.drawPath(Path()
          ..moveTo(8.2, 10.5)
          ..lineTo(8.2, 8.2)
          ..cubicTo(8.2, 6.1, 9.9, 4.4, 12, 4.4)
          ..cubicTo(14.1, 4.4, 15.8, 6.1, 15.8, 8.2)
          ..lineTo(15.8, 10.5), stroke);
        bubble(12, 15.2, 2.8, 2, solid: true);
      case DueIcons.signOut:
        canvas.drawPath(Path()
          ..moveTo(10, 4.5)
          ..lineTo(6.5, 4.5)
          ..cubicTo(5.4, 4.5, 4.5, 5.4, 4.5, 6.5)
          ..lineTo(4.5, 17.5)
          ..cubicTo(4.5, 18.6, 5.4, 19.5, 6.5, 19.5)
          ..lineTo(10, 19.5), stroke);
        line(10.5, 12, 20, 12);
        canvas.drawPath(Path()
          ..moveTo(16.5, 8.5)
          ..lineTo(20, 12)
          ..lineTo(16.5, 15.5), stroke);
      case DueIcons.mail:
        canvas.drawRRect(RRect.fromLTRBR(3, 5.5, 21, 18.5, const Radius.circular(2.6)), stroke);
        canvas.drawPath(Path()
          ..moveTo(3.8, 7.3)
          ..lineTo(12, 12.8)
          ..lineTo(20.2, 7.3), stroke);
      case DueIcons.classroom:
        canvas.drawPath(Path()
          ..moveTo(2.5, 9.6)
          ..lineTo(12, 5.2)
          ..lineTo(21.5, 9.6)
          ..lineTo(12, 14)
          ..close(), stroke);
        canvas.drawPath(Path()
          ..moveTo(6.5, 11.6)
          ..lineTo(6.5, 15.4)
          ..cubicTo(9.6, 18.1, 14.4, 18.1, 17.5, 15.4)
          ..lineTo(17.5, 11.6), stroke);
        line(21.5, 9.6, 21.5, 14.5);
      case DueIcons.upload:
        canvas.drawPath(Path()
          ..moveTo(4.5, 14.5)
          ..lineTo(4.5, 17.5)
          ..cubicTo(4.5, 18.6, 5.4, 19.5, 6.5, 19.5)
          ..lineTo(17.5, 19.5)
          ..cubicTo(18.6, 19.5, 19.5, 18.6, 19.5, 17.5)
          ..lineTo(19.5, 14.5), stroke);
        line(12, 15, 12, 4.6);
        canvas.drawPath(Path()
          ..moveTo(8, 8.5)
          ..lineTo(12, 4.5)
          ..lineTo(16, 8.5), stroke);
      case DueIcons.fresh:
        canvas.drawPath(Path()
          ..moveTo(12, 3.5)
          ..cubicTo(12.6, 9, 15, 11.4, 20.5, 12)
          ..cubicTo(15, 12.6, 12.6, 15, 12, 20.5)
          ..cubicTo(11.4, 15, 9, 12.6, 3.5, 12)
          ..cubicTo(9, 11.4, 11.4, 9, 12, 3.5)
          ..close(), stroke);
      case DueIcons.flag:
        line(6, 3.5, 6, 20.5);
        canvas.drawPath(Path()
          ..moveTo(6, 4.5)
          ..lineTo(17.5, 4.5)
          ..lineTo(14.8, 8)
          ..lineTo(17.5, 11.5)
          ..lineTo(6, 11.5), stroke);
      case DueIcons.send:
        canvas.drawPath(Path()
          ..moveTo(3.5, 11.5)
          ..lineTo(20.5, 4)
          ..lineTo(14.5, 20.5)
          ..lineTo(11, 13.5)
          ..close(), stroke);
        line(11, 13.5, 20.5, 4);
      case DueIcons.quiet:
        canvas.drawPath(Path()
          ..moveTo(18.5, 14.8)
          ..cubicTo(13.4, 16.6, 8, 12.9, 8.6, 7.4)
          ..cubicTo(8.7, 6.2, 9.1, 5.1, 9.7, 4.2)
          ..cubicTo(5.9, 5.3, 3.4, 9.1, 4.1, 13.1)
          ..cubicTo(4.9, 17.8, 9.4, 20.8, 14, 20)
          ..cubicTo(16.1, 19.6, 17.7, 18.5, 18.5, 14.8)
          ..close(), stroke);
        bubble(17.5, 6.5, 3.4, 2.3);
      case DueIcons.link:
        // Two answer bubbles joined: the same work, seen twice.
        canvas.drawRRect(RRect.fromLTRBR(2.5, 8.2, 13.5, 15.8, const Radius.circular(3.8)), stroke);
        canvas.drawRRect(RRect.fromLTRBR(10.5, 8.2, 21.5, 15.8, const Radius.circular(3.8)), stroke);
      case DueIcons.offline:
        for (final (r, a) in [(8.0, 0.0), (4.6, 0.0)]) {
          canvas.drawArc(Rect.fromCircle(center: const Offset(12, 17), radius: r), math.pi * 1.2 + a, math.pi * 0.6, false, stroke);
        }
        canvas.drawCircle(const Offset(12, 17), 1.3, fill);
        line(4.5, 4.5, 19.5, 19.5);
      case DueIcons.undated:
        canvas.drawRRect(sheet(), stroke);
        line(3, 9.5, 21, 9.5);
        line(8, 2.8, 8, 5.6);
        line(16, 2.8, 16, 5.6);
        // An empty bubble: no date marked yet.
        bubble(12, 14.6, 5, 3.2);
    }
  }

  @override
  bool shouldRepaint(_Glyph old) => old.icon != icon || old.color != color || old.filled != filled;
}
