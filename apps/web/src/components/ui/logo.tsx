// The mark: a heart built from the answer sheet's shapes. A rose square turned on
// its point, with two bubbles for the lobes: yellow (due) and green (done).
export function LogoMark({ size = 30 }: { size?: number }) {
  return (
    <svg
      className="logo-mark"
      width={size}
      height={size}
      viewBox="5 12 70 70"
      aria-hidden="true"
      focusable="false"
    >
      <polygon points="40,22 68,50 40,78 12,50" fill="var(--ink)" />
      <circle className="lobe-left" cx="26" cy="36" r="20" fill="var(--due)" />
      <circle className="lobe-right" cx="54" cy="36" r="20" fill="var(--good)" />
      <polygon points="40,36 54,50 40,64 26,50" fill="var(--ink)" />
    </svg>
  );
}

export function Logo({ size = 30 }: { size?: number }) {
  return (
    <span className="logo">
      <LogoMark size={size} />
      <span className="logo-word">DueCare</span>
    </span>
  );
}
