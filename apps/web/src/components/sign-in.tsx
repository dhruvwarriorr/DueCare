"use client";
import Link from "next/link";
import { useState } from "react";
import { Check, ArrowRight, BookOpen } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "./ui/button";
import { ErrorNotice } from "./ui/field";
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
        <Link className="brand" href="/">
          DueCare<span className="brand-mark">d.</span>
        </Link>
        <div>
          <p className="eyebrow">YOUR ACADEMIC WORKSPACE</p>
          <h1>
            Make room for
            <br />
            what comes next.
          </h1>
          <p className="lead">
            Assignments, tests, and your weekly schedule.
            <br />
            One place to keep everything in view.
          </p>
          <ul className="signin-benefits">
            <li>
              <Check size={18} />
              Track work on your own terms
            </li>
            <li>
              <Check size={18} />
              Keep theory, labs, and tutorials distinct
            </li>
            <li>
              <Check size={18} />
              See what is due and what is done
            </li>
          </ul>
        </div>
        <p className="text-secondary text-sm">
          Built for the Somaiya community.
        </p>
      </section>
      <section className="signin-form">
        <BookOpen className="text-primary" size={32} />
        <h2>Welcome to DueCare</h2>
        <p>Use your Somaiya Google account to get started.</p>
        <Button onClick={login} disabled={pending} className="w-full">
          {pending ? "Connecting…" : "Continue with Google"}
          <ArrowRight size={17} />
        </Button>
        <ErrorNotice error={error} />
        <p className="text-xs text-secondary">
          Access is available to verified @somaiya.edu accounts.
        </p>
      </section>
    </main>
  );
}
