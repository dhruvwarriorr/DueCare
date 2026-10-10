"use client";
// A deadline time without the browser's spin-wheel: common college times in one tap, or hour,
// minute and am/pm as ordinary dropdowns. Value is 24-hour "HH:MM", or "" for no time.
const QUICK: [string, string][] = [
  ["", "No time"],
  ["09:00", "9:00 am"],
  ["13:30", "1:30 pm"],
  ["17:00", "5:00 pm"],
  ["23:59", "11:59 pm"],
];
const HOURS = Array.from({ length: 12 }, (_, i) => i + 1);
const MINUTES = Array.from({ length: 12 }, (_, i) => i * 5);

function parts(value: string) {
  // Stored times may carry seconds ("09:00:00").
  value = (value || "").slice(0, 5);
  if (!/^\d{2}:\d{2}$/.test(value)) return null;
  const [h, m] = value.split(":").map(Number);
  return { hour: h % 12 || 12, minute: m, pm: h >= 12 };
}
function join(hour: number, minute: number, pm: boolean) {
  const h = (hour % 12) + (pm ? 12 : 0);
  return String(h).padStart(2, "0") + ":" + String(minute).padStart(2, "0");
}

export function TimePicker({
  id,
  value,
  onChange,
  disabled,
  label,
  quick = true,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  /** Names the dropdowns when no visible label points at them ("Starts for Mon 9:00"). */
  label?: string;
  /** Common deadline times; off for class timetables. */
  quick?: boolean;
}) {
  const name = (part: string) =>
    label ? label + " " + part.toLowerCase() : part;
  const p = parts(value);
  // A time set elsewhere (11:59, 1:35) keeps its exact minute in the list.
  const minutes =
    p && !MINUTES.includes(p.minute)
      ? [...MINUTES, p.minute].sort((a, b) => a - b)
      : MINUTES;
  const set = (
    change: Partial<{ hour: number; minute: number; pm: boolean }>,
  ) => {
    const base = p || { hour: 12, minute: 0, pm: false };
    onChange(
      join(
        change.hour ?? base.hour,
        change.minute ?? base.minute,
        change.pm ?? base.pm,
      ),
    );
  };
  return (
    <div className="time-picker">
      <div className="time-custom">
        <select
          id={id}
          aria-label={name("Hour")}
          disabled={disabled}
          value={p ? p.hour : ""}
          onChange={(e) => set({ hour: Number(e.target.value) })}
        >
          <option value="" disabled>
            Hour
          </option>
          {HOURS.map((h) => (
            <option key={h} value={h}>
              {h}
            </option>
          ))}
        </select>
        <span aria-hidden="true">:</span>
        <select
          aria-label={name("Minute")}
          disabled={disabled}
          value={p ? p.minute : ""}
          onChange={(e) => set({ minute: Number(e.target.value) })}
        >
          <option value="" disabled>
            Min
          </option>
          {minutes.map((m) => (
            <option key={m} value={m}>
              {String(m).padStart(2, "0")}
            </option>
          ))}
        </select>
        <div
          className="seg"
          role="group"
          aria-label={name("Morning or afternoon")}
        >
          {(["am", "pm"] as const).map((half) => (
            <button
              key={half}
              type="button"
              disabled={disabled}
              aria-pressed={Boolean(p) && p!.pm === (half === "pm")}
              onClick={() => set({ pm: half === "pm" })}
            >
              {half}
            </button>
          ))}
        </div>
      </div>
      {quick && (
        <div className="time-quick" role="group" aria-label="Common times">
          {QUICK.map(([v, text]) => (
            <button
              key={text}
              type="button"
              disabled={disabled}
              aria-pressed={(value || "").slice(0, 5) === v}
              onClick={() => onChange(v)}
            >
              {text}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
