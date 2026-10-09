"use client";
import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Check } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "./ui/button";
import { Logo } from "./ui/logo";
import { ErrorNotice } from "./ui/field";

// Illustrative only: a sample week drawn in the workspace's own vocabulary.
const H = 34;
const sampleSlots: [number, number, number, string, string][] = [
  [0, 9, 10, "DS", "theory"],
  [0, 11, 13, "DBMS", "lab"],
  [1, 10, 11, "CN", "theory"],
  [2, 9, 11, "OS Lab", "lab"],
  [3, 12, 13, "DS Tut", "tutorial"],
  [4, 10, 11, "EM-III", "theory"],
  [4, 13, 14, "CN", "theory"],
];
const sampleDue: [number, string, string, string][] = [
  [0, "DS Exp 3", "23:59 · done", "completed"],
  [1, "CN quiz", "12:15", "due"],
  [2, "DBMS ER diagram", "17:00 · overdue", "overdue"],
  [3, "OS write-up", "23:59", "due"],
];
const kinds: Record<string, string> = {
  theory: "Theory",
  lab: "Lab",
  tutorial: "Tutorial",
};

export function SignIn({ callbackError = false }: { callbackError?: boolean }) {
  const [error, setError] = useState<Error | null>(
    callbackError
      ? new Error(
          "Sign-in could not be completed. Use your verified @somaiya.edu Google account and try again.",
        )
      : null,
  );
  const [pending, setPending] = useState(false);
  async function login() {
    setPending(true);
    setError(null);
    try {
      const r = await api<{ url: string }>("/auth/start", "POST");
      window.location.assign(r.url);
    } catch (e) {
      setError(e as Error);
      setPending(false);
    }
  }
  return (
    <main id="main" className="signin">
      <section className="signin-story">
        <div className="signin-timing" aria-hidden="true">
          {Array.from({ length: 14 }, (_, i) => (
            <span key={i} className="tmark" />
          ))}
        </div>
        <Link className="brand" href="/" aria-label="DueCare">
          <Logo size={36} />
        </Link>
        <div>
          <h1>
            Everything due, <em>on one week</em>.
          </h1>
          <p className="lead">
            DueCare collects assignments and tests from Gmail, Classroom, and
            your own notes, and shows them next to your classes.
          </p>
          <ul className="signin-benefits">
            <li>
              <Check size={18} aria-hidden="true" />
              See what&rsquo;s due, done, and late at a glance
            </li>
            <li>
              <Check size={18} aria-hidden="true" />
              Marked done when you submit
            </li>
            <li>
              <Check size={18} aria-hidden="true" />
              Asks you only when something is unclear
            </li>
          </ul>
        </div>
        <figure className="sample" aria-label="Sample week sheet">
          <div className="sample-head" aria-hidden="true">
            <div />
            {["Mon", "Tue", "Wed", "Thu", "Fri"].map((d, i) => (
              <div key={d}>
                <span className="printed">{d}</span>
                <strong>{6 + i}</strong>
              </div>
            ))}
          </div>
          <div className="sample-due" aria-hidden="true">
            <div className="printed">Due</div>
            {[0, 1, 2, 3, 4].map((day) => (
              <div key={day}>
                {sampleDue
                  .filter((d) => d[0] === day)
                  .map(([, title, meta, status]) => (
                    <span key={title} className={"due-item " + status}>
                      <span className="due-text">
                        <span className="due-title">{title}</span>
                        <span className="due-meta">{meta}</span>
                      </span>
                    </span>
                  ))}
              </div>
            ))}
          </div>
          <div
            className="sample-body"
            aria-hidden="true"
            style={{ "--hour": H + "px" } as React.CSSProperties}
          >
            <div className="sample-rail">
              {Array.from({ length: 6 }, (_, i) => (
                <span key={i} className="tmark" style={{ top: i * H }} />
              ))}
            </div>
            {[0, 1, 2, 3, 4].map((day) => (
              <div className="sample-col" key={day}>
                {sampleSlots
                  .filter((s) => s[0] === day)
                  .map(([, from, to, name, kind]) => (
                    <div
                      key={name + from}
                      className={"slot-box " + kind}
                      style={{
                        top: (from - 9) * H + 1,
                        height: (to - from) * H - 2,
                      }}
                    >
                      <span className="slot-name">{name}</span>
                      <span className="slot-time">{kinds[kind]}</span>
                    </div>
                  ))}
              </div>
            ))}
          </div>
          <figcaption className="sample-caption">
            <span>Sample week, for illustration</span>
            <span>All times IST</span>
          </figcaption>
        </figure>
      </section>
      <section className="signin-form">
        <h2>Sign in to DueCare</h2>
        <p>Use your Somaiya Google account to get started.</p>
        <dl className="signin-fields">
          <div>
            <dt>Institution</dt>
            <dd>KJSSE</dd>
          </div>
          <div>
            <dt>Programme</dt>
            <dd>BTech</dd>
          </div>
          <div>
            <dt>Account</dt>
            <dd>@somaiya.edu</dd>
          </div>
          <div>
            <dt>Sources</dt>
            <dd>Read-only</dd>
          </div>
        </dl>
        <Button onClick={login} disabled={pending} className="w-full">
          {pending ? "Connecting…" : "Continue with Google"}
          <ArrowRight size={17} />
        </Button>
        <ErrorNotice error={error} />
        <p className="text-sm text-secondary">
          Access is available to verified @somaiya.edu accounts. Google will
          also ask to let DueCare read your Gmail and Classroom (read-only) so
          your assignments and tests appear automatically.
        </p>
      </section>
    </main>
  );
}
