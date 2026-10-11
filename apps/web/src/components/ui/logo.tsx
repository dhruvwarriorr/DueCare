import { useId } from "react";

// The mark: an answer bubble with a printed D, half filled in rose the way a student marks
// an answer. Same 100-unit geometry as the Android icon (apps/mobile/tool/mark.py).
const D = "M34,37 H53 A13,13 0 0 1 53,63 H34 Z M44,45 V55 H53 A5,5 0 0 0 53,45 Z";

export function LogoMark({ size = 30 }: { size?: number }) {
  const id = useId();
  return (
    <svg
      className="logo-mark"
      width={size * 1.2}
      height={size * 0.78}
      viewBox="4 20.5 92 59"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <clipPath id={`${id}-in`}>
          <rect x="11.5" y="27.5" width="77" height="45" rx="22.5" />
        </clipPath>
        <clipPath id={`${id}-pencil`}>
          <polygon className="logo-pencil" points="-10,-10 64.2,-10 39.8,110 -10,110" />
        </clipPath>
      </defs>
      <path d={D} fillRule="evenodd" fill="var(--graphite)" />
      <g clipPath={`url(#${id}-in)`}>
        <g clipPath={`url(#${id}-pencil)`}>
          <rect x="0" y="0" width="100" height="100" fill="var(--ink)" />
          <path d={D} fillRule="evenodd" fill="var(--sheet)" />
        </g>
      </g>
      <rect x="8" y="24" width="84" height="52" rx="26" fill="none" stroke="var(--ink)" strokeWidth="7" />
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
