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

/// Corner radii: rounded for touch, while the oval bubble stays the brand's signature shape.
abstract final class Radii {
  static const small = 10.0;
  static const medium = 14.0;
  static const card = 18.0;
  static const sheet = 26.0;
}

ThemeData duecareTheme(Brightness brightness) {
  final ink = brightness == Brightness.dark ? Palette.dark : Palette.light;
  final dark = brightness == Brightness.dark;
  final base = ThemeData(brightness: brightness, useMaterial3: true);
  // Calling the family once registers it with the engine; every style then names it.
  final text = base.textTheme.apply(
    fontFamily: fetchFonts ? GoogleFonts.bricolageGrotesque().fontFamily : null,
    bodyColor: ink.graphite,
    displayColor: ink.graphite,
  );
  RoundedRectangleBorder round(double r, [BorderSide side = BorderSide.none]) =>
      RoundedRectangleBorder(borderRadius: BorderRadius.circular(r), side: side);
  OutlineInputBorder line(Color c, [double w = 1]) =>
      OutlineInputBorder(borderRadius: BorderRadius.circular(Radii.medium), borderSide: BorderSide(color: c, width: w));
  const buttonText = TextStyle(fontSize: 15, fontWeight: FontWeight.w700, letterSpacing: 0.1);
  final container = dark ? const Color(0xFF241F26) : const Color(0xFFF7EEF2);
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
      secondaryContainer: ink.inkTint,
      onSecondaryContainer: ink.graphite,
      error: ink.bad,
      onError: ink.onBad,
      surface: ink.sheet,
      onSurface: ink.graphite,
      onSurfaceVariant: ink.graphite2,
      surfaceTint: Colors.transparent,
      surfaceContainerLowest: ink.sheet,
      surfaceContainerLow: ink.sheet,
      surfaceContainer: container,
      surfaceContainerHigh: container,
      surfaceContainerHighest: ink.inkTint,
      outline: ink.inkLine,
      outlineVariant: ink.inkRule,
    ),
    textTheme: text.copyWith(
      bodyLarge: text.bodyLarge?.copyWith(fontSize: 16, height: 1.45),
      bodyMedium: text.bodyMedium?.copyWith(fontSize: 15, height: 1.45),
      bodySmall: text.bodySmall?.copyWith(fontSize: 13, color: ink.graphite2),
      titleMedium: text.titleMedium?.copyWith(fontWeight: FontWeight.w700),
    ),
    textSelectionTheme: TextSelectionThemeData(cursorColor: ink.ink, selectionColor: ink.inkTint, selectionHandleColor: ink.ink),
    dividerTheme: DividerThemeData(color: ink.inkRule, thickness: 1, space: 1),
    appBarTheme: AppBarTheme(
      backgroundColor: ink.paper,
      surfaceTintColor: Colors.transparent,
      foregroundColor: ink.graphite,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: _face(fontSize: 20, fontWeight: FontWeight.w800, color: ink.graphite),
    ),
    // Depth comes from tone, not shadow: sheet-white cards on the paper ground.
    cardTheme: CardThemeData(elevation: 0, shape: round(Radii.card), color: ink.sheet, margin: EdgeInsets.zero),
    dialogTheme: DialogThemeData(elevation: 0, backgroundColor: ink.sheet, shape: round(Radii.sheet)),
    bottomSheetTheme: BottomSheetThemeData(
      elevation: 0,
      backgroundColor: ink.sheet,
      modalBackgroundColor: ink.sheet,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(Radii.sheet))),
      showDragHandle: true,
      dragHandleColor: ink.inkLine,
    ),
    popupMenuTheme: PopupMenuThemeData(elevation: 2, color: ink.sheet, shape: round(Radii.medium)),
    menuTheme: MenuThemeData(style: MenuStyle(shape: WidgetStatePropertyAll(round(Radii.medium)))),
    snackBarTheme: SnackBarThemeData(
      elevation: 0,
      backgroundColor: ink.band,
      contentTextStyle: TextStyle(color: dark ? ink.graphite : ink.sheet, fontSize: 15),
      actionTextColor: ink.due,
      shape: round(Radii.medium),
      behavior: SnackBarBehavior.floating,
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: ink.graphite,
        foregroundColor: ink.onGraphite,
        disabledBackgroundColor: ink.inkRule,
        minimumSize: const Size(64, 50),
        padding: const EdgeInsets.symmetric(horizontal: 22),
        shape: round(Radii.medium),
        textStyle: buttonText,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: ink.graphite,
        minimumSize: const Size(64, 50),
        padding: const EdgeInsets.symmetric(horizontal: 20),
        side: BorderSide(color: ink.inkLine),
        shape: round(Radii.medium),
        textStyle: buttonText,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: ink.ink,
        minimumSize: const Size(48, 44),
        shape: round(Radii.small),
        textStyle: buttonText,
      ),
    ),
    iconButtonTheme: IconButtonThemeData(style: IconButton.styleFrom(foregroundColor: ink.graphite)),
    floatingActionButtonTheme: FloatingActionButtonThemeData(
      backgroundColor: ink.graphite,
      foregroundColor: ink.onGraphite,
      elevation: 0,
      focusElevation: 0,
      hoverElevation: 0,
      highlightElevation: 0,
      shape: round(20),
      extendedTextStyle: buttonText,
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: ink.sheet,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      height: 70,
      indicatorColor: ink.inkTint,
      labelTextStyle: WidgetStateProperty.resolveWith(
        (s) => TextStyle(fontSize: 12.5, fontWeight: s.contains(WidgetState.selected) ? FontWeight.w800 : FontWeight.w600, color: ink.graphite),
      ),
      iconTheme: WidgetStateProperty.resolveWith(
        (s) => IconThemeData(color: s.contains(WidgetState.selected) ? ink.ink : ink.graphite2, size: 24),
      ),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: ink.sheet,
      selectedColor: ink.graphite,
      disabledColor: ink.inkWash,
      checkmarkColor: ink.onGraphite,
      side: BorderSide(color: ink.inkRule),
      shape: const StadiumBorder(),
      // Selected chips are filled graphite, so their label turns light.
      labelStyle: TextStyle(
        fontSize: 14,
        fontWeight: FontWeight.w600,
        color: WidgetStateColor.resolveWith((s) => s.contains(WidgetState.selected) ? ink.onGraphite : ink.graphite),
      ),
      secondaryLabelStyle: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: ink.onGraphite),
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      showCheckmark: false,
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: ButtonStyle(
        shape: WidgetStatePropertyAll(round(Radii.medium)),
        side: WidgetStatePropertyAll(BorderSide(color: ink.inkRule)),
        minimumSize: const WidgetStatePropertyAll(Size(48, 46)),
        backgroundColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? ink.graphite : ink.sheet),
        foregroundColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? ink.onGraphite : ink.graphite),
        textStyle: const WidgetStatePropertyAll(TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: container,
      isDense: false,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
      hintStyle: TextStyle(color: ink.graphite2),
      border: line(Colors.transparent),
      enabledBorder: line(Colors.transparent),
      focusedBorder: line(ink.ink, 1.6),
      errorBorder: line(ink.bad),
      focusedErrorBorder: line(ink.bad, 1.6),
      errorStyle: TextStyle(color: ink.bad, fontWeight: FontWeight.w600, fontSize: 13),
    ),
    checkboxTheme: CheckboxThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
      side: BorderSide(color: ink.inkLine, width: 1.6),
      fillColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? ink.graphite : Colors.transparent),
      checkColor: WidgetStatePropertyAll(ink.onGraphite),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? ink.onGraphite : ink.inkLine),
      trackColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? ink.ink : container),
      trackOutlineColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? ink.ink : ink.inkLine),
    ),
    radioTheme: RadioThemeData(fillColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? ink.ink : ink.inkLine)),
    progressIndicatorTheme: ProgressIndicatorThemeData(color: ink.ink, linearTrackColor: ink.inkTint, circularTrackColor: Colors.transparent),
    datePickerTheme: DatePickerThemeData(
      elevation: 0,
      backgroundColor: ink.sheet,
      shape: round(Radii.sheet),
      headerBackgroundColor: ink.sheet,
      headerForegroundColor: ink.graphite,
      todayBorder: BorderSide(color: ink.ink),
      todayForegroundColor: WidgetStatePropertyAll(ink.ink),
      dayBackgroundColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? ink.graphite : null),
    ),
    timePickerTheme: TimePickerThemeData(
      elevation: 0,
      backgroundColor: ink.sheet,
      shape: round(Radii.sheet),
      hourMinuteShape: round(Radii.medium),
      dayPeriodShape: round(Radii.medium),
      dialBackgroundColor: container,
      dialHandColor: ink.ink,
    ),
    listTileTheme: ListTileThemeData(
      iconColor: ink.ink,
      textColor: ink.graphite,
      minVerticalPadding: 12,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16),
      titleTextStyle: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: ink.graphite),
      subtitleTextStyle: TextStyle(fontSize: 13.5, color: ink.graphite2, height: 1.35),
    ),
    expansionTileTheme: ExpansionTileThemeData(shape: const Border(), collapsedShape: const Border(), iconColor: ink.ink, collapsedIconColor: ink.ink),
    badgeTheme: BadgeThemeData(backgroundColor: ink.bad, textColor: ink.onBad),
    iconTheme: IconThemeData(color: ink.graphite),
    splashFactory: InkSparkle.splashFactory,
    pageTransitionsTheme: const PageTransitionsTheme(builders: {TargetPlatform.android: PredictiveBackPageTransitionsBuilder()}),
  );
}
