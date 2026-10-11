import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// The Answer Sheet palette (apps/web/DESIGN.md). Rose prints structure, graphite carries text
/// and action, and green, yellow and red show a deadline's status only.
@immutable
class Palette extends ThemeExtension<Palette> {
  const Palette({
    required this.paper,
    required this.sheet,
    required this.ink,
    required this.inkLine,
    required this.inkRule,
    required this.inkTint,
    required this.inkWash,
    required this.graphite,
    required this.graphite2,
    required this.onGraphite,
    required this.good,
    required this.goodTint,
    required this.onGood,
    required this.due,
    required this.dueLine,
    required this.dueTint,
    required this.dueText,
    required this.onDue,
    required this.bad,
    required this.badTint,
    required this.badText,
    required this.onBad,
    required this.band,
    required this.scrim,
  });

  final Color paper, sheet, ink, inkLine, inkRule, inkTint, inkWash, graphite, graphite2, onGraphite;
  final Color good, goodTint, onGood, due, dueLine, dueTint, dueText, onDue, bad, badTint, badText;
  final Color onBad, band, scrim;

  static const light = Palette(
    paper: Color(0xFFF4F5F8),
    sheet: Color(0xFFFFFFFF),
    ink: Color(0xFFC21C58),
    inkLine: Color(0xFFD4668B),
    inkRule: Color(0xFFEFC3D2),
    inkTint: Color(0xFFFBE4EC),
    inkWash: Color(0xFFFDF3F7),
    graphite: Color(0xFF18171B),
    graphite2: Color(0xFF5D4A53),
    onGraphite: Color(0xFFFFFFFF),
    good: Color(0xFF1D7440),
    goodTint: Color(0xFFE5F5EA),
    onGood: Color(0xFFFFFFFF),
    due: Color(0xFFF5C400),
    dueLine: Color(0xFFD9AD00),
    dueTint: Color(0xFFFFF6D6),
    dueText: Color(0xFF7A5800),
    onDue: Color(0xFF2B2100),
    bad: Color(0xFFC8261E),
    badTint: Color(0xFFFDE8E5),
    badText: Color(0xFFB4231B),
    onBad: Color(0xFFFFFFFF),
    band: Color(0xFF18171B),
    scrim: Color(0x8C18171B),
  );

  static const dark = Palette(
    paper: Color(0xFF121014),
    sheet: Color(0xFF1A171C),
    ink: Color(0xFFFF6F9C),
    inkLine: Color(0xFFB94E76),
    inkRule: Color(0xFF3F2430),
    inkTint: Color(0xFF33202A),
    inkWash: Color(0xFF221B21),
    graphite: Color(0xFFEFEAEC),
    graphite2: Color(0xFFB8A7AF),
    onGraphite: Color(0xFF141216),
    good: Color(0xFF4FC37F),
    goodTint: Color(0xFF15301F),
    onGood: Color(0xFF0E1A12),
    due: Color(0xFFF5C518),
    dueLine: Color(0xFFC9A10F),
    dueTint: Color(0xFF33290A),
    dueText: Color(0xFFF5C84B),
    onDue: Color(0xFF1F1800),
    bad: Color(0xFFFF6B5E),
    badTint: Color(0xFF3A1715),
    badText: Color(0xFFFF7B70),
    onBad: Color(0xFF1A0806),
    band: Color(0xFF2B262D),
    scrim: Color(0x99000000),
  );

  static Palette of(BuildContext context) => Theme.of(context).extension<Palette>()!;

  @override
  Palette copyWith() => this;

  @override
  Palette lerp(Palette? other, double t) => t < 0.5 || other == null ? this : other;
}

/// Bricolage Grotesque, fetched once and cached by google_fonts. Tests turn it off and use the
/// platform font, since they run without a network.
bool fetchFonts = true;

TextStyle _face({double? fontSize, FontWeight? fontWeight, double? letterSpacing, double? height, Color? color, List<FontFeature>? fontFeatures}) {
  final style = TextStyle(
    fontSize: fontSize,
    fontWeight: fontWeight,
    letterSpacing: letterSpacing,
    height: height,
    color: color,
    fontFeatures: fontFeatures,
  );
  return fetchFonts ? GoogleFonts.bricolageGrotesque(textStyle: style) : style;
}

/// Printed caps: field names, day names, row labels and statuses (the Printed Caps Rule).
TextStyle printed(BuildContext context, {Color? color, double size = 11.5}) => _face(
      fontSize: size,
      fontWeight: FontWeight.w700,
      letterSpacing: size * 0.09,
      height: 1.2,
      color: color ?? Palette.of(context).ink,
    );

/// The condensed face for headings and every numeral, with tabular figures (the Tabular Rule).
TextStyle display(BuildContext context, double size, {FontWeight weight = FontWeight.w800, Color? color}) =>
    _face(
      fontSize: size,
      fontWeight: weight,
      height: 1.05,
      letterSpacing: -0.01 * size,
      color: color ?? Palette.of(context).graphite,
      fontFeatures: const [FontFeature.tabularFigures()],
    );

ThemeData duecareTheme(Brightness brightness) {
  final ink = brightness == Brightness.dark ? Palette.dark : Palette.light;
  final base = ThemeData(brightness: brightness, useMaterial3: true);
  // Calling the family once registers it with the engine; every style then names it.
  final text = base.textTheme.apply(
    fontFamily: fetchFonts ? GoogleFonts.bricolageGrotesque().fontFamily : null,
    bodyColor: ink.graphite,
    displayColor: ink.graphite,
  );
  const square = RoundedRectangleBorder(borderRadius: BorderRadius.zero);
  OutlineInputBorder line(Color c, [double w = 1]) =>
      OutlineInputBorder(borderRadius: BorderRadius.zero, borderSide: BorderSide(color: c, width: w));
  return base.copyWith(
    extensions: [ink],
    scaffoldBackgroundColor: ink.paper,
    canvasColor: ink.sheet,
    colorScheme: ColorScheme(
      brightness: brightness,
      primary: ink.graphite,
      onPrimary: ink.onGraphite,
      secondary: ink.ink,
      onSecondary: ink.sheet,
      error: ink.ink,
      onError: ink.sheet,
      surface: ink.sheet,
      onSurface: ink.graphite,
      surfaceTint: Colors.transparent,
      outline: ink.inkLine,
      outlineVariant: ink.inkRule,
    ),
    textTheme: text.copyWith(
      bodyMedium: text.bodyMedium?.copyWith(fontSize: 15, height: 1.55),
      bodySmall: text.bodySmall?.copyWith(fontSize: 13, color: ink.graphite2),
    ),
    textSelectionTheme: TextSelectionThemeData(cursorColor: ink.ink, selectionColor: ink.inkTint),
    dividerTheme: DividerThemeData(color: ink.inkRule, thickness: 1, space: 1),
    appBarTheme: AppBarTheme(
      backgroundColor: ink.sheet,
      foregroundColor: ink.graphite,
      elevation: 0,
      scrolledUnderElevation: 0,
      shape: Border(bottom: BorderSide(color: ink.graphite)),
      titleTextStyle: _face(fontSize: 22, fontWeight: FontWeight.w800, color: ink.graphite),
    ),
    // The No-Shadow and One Curve Rules: no elevation and square corners everywhere.
    cardTheme: CardThemeData(elevation: 0, shape: square, color: ink.sheet, margin: EdgeInsets.zero),
    dialogTheme: DialogThemeData(
      elevation: 0,
      backgroundColor: ink.sheet,
      shape: Border(top: BorderSide(color: ink.graphite, width: 6), bottom: BorderSide(color: ink.graphite)),
    ),
    bottomSheetTheme: BottomSheetThemeData(
      elevation: 0,
      backgroundColor: ink.sheet,
      modalBackgroundColor: ink.sheet,
      shape: Border(top: BorderSide(color: ink.graphite, width: 6)),
      showDragHandle: false,
    ),
    popupMenuTheme: PopupMenuThemeData(
      elevation: 0,
      color: ink.sheet,
      shape: Border.all(color: ink.graphite),
    ),
    snackBarTheme: SnackBarThemeData(
      elevation: 0,
      backgroundColor: ink.band,
      contentTextStyle: TextStyle(color: brightness == Brightness.dark ? ink.graphite : ink.sheet),
      actionTextColor: ink.due,
      shape: square,
      behavior: SnackBarBehavior.floating,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: ink.sheet,
      isDense: true,
      contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
      hintStyle: TextStyle(color: ink.graphite2),
      border: line(ink.inkLine),
      enabledBorder: line(ink.inkLine),
      focusedBorder: line(ink.graphite, 2),
      errorBorder: line(ink.ink),
      focusedErrorBorder: line(ink.ink, 2),
      errorStyle: TextStyle(color: ink.ink, fontWeight: FontWeight.w600, fontSize: 13),
    ),
    checkboxTheme: CheckboxThemeData(
      shape: square,
      side: BorderSide(color: ink.inkLine),
      fillColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? ink.graphite : ink.sheet),
      checkColor: WidgetStatePropertyAll(ink.onGraphite),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? ink.onGraphite : ink.inkLine),
      trackColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? ink.graphite : ink.sheet),
      trackOutlineColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? ink.graphite : ink.inkLine),
    ),
    radioTheme: RadioThemeData(fillColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? ink.graphite : ink.inkLine)),
    progressIndicatorTheme: ProgressIndicatorThemeData(color: ink.ink, linearTrackColor: ink.inkTint),
    datePickerTheme: DatePickerThemeData(
      elevation: 0,
      backgroundColor: ink.sheet,
      shape: Border(top: BorderSide(color: ink.graphite, width: 6)),
      headerBackgroundColor: ink.graphite,
      headerForegroundColor: ink.onGraphite,
      dayShape: const WidgetStatePropertyAll(square),
      todayBorder: BorderSide(color: ink.ink),
    ),
    timePickerTheme: TimePickerThemeData(
      elevation: 0,
      backgroundColor: ink.sheet,
      shape: Border(top: BorderSide(color: ink.graphite, width: 6)),
      hourMinuteShape: square,
      dayPeriodShape: square,
    ),
    listTileTheme: ListTileThemeData(iconColor: ink.graphite, textColor: ink.graphite, minVerticalPadding: 12),
    iconTheme: IconThemeData(color: ink.graphite),
    splashFactory: NoSplash.splashFactory,
    highlightColor: ink.inkWash,
    hoverColor: ink.inkWash,
  );
}
