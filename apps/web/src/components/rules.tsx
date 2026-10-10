"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, SlidersHorizontal } from "lucide-react";
import { api } from "@/lib/api";
import type { Rule, RuleCondition, Subject } from "@/lib/types";
import { Button } from "./ui/button";
import { ErrorNotice } from "./ui/field";

type Draft = Omit<Rule, "id" | "position" | "revision" | "affects">;
type Doing = "critical" | "high" | "medium" | "low" | "hide";
type Target = "subjectId" | "taskType" | "keyword" | "sender" | "source";

const doings: [Doing, string][] = [
  ["high", "Make high priority"],
  ["critical", "Make critical priority"],
  ["medium", "Make medium priority"],
  ["low", "Make low priority"],
  ["hide", "Hide"],
];
const targets: [Target, string][] = [
  ["subjectId", "a subject"],
  ["taskType", "tests or assignments"],
  ["keyword", "work containing a word"],
  ["sender", "mail from a sender"],
  ["source", "Gmail or Classroom"],
];

/** A rule as one plain sentence: "Make ITVC work high priority", "Hide work containing “seminar”". */
export function describe(rule: Draft, subjects: Subject[]) {
  const value = (c: RuleCondition) =>
    Array.isArray(c.value) ? c.value.join(", ") : c.value;
  let what = "work";
  const parts: string[] = [];
  for (const c of rule.conditions) {
    const v = value(c);
    if (c.field === "taskType") what = v === "test" ? "tests" : "assignments";
    else if (c.field === "subjectId") {
      // One course can be several subjects (ITVC theory and tutorial): name it once.
      const ids = Array.isArray(c.value) ? c.value : [c.value];
      const names = [
        ...new Set(
          ids
            .map((id) => subjects.find((s) => s.id === id)?.name)
            .filter(Boolean),
        ),
      ];
      parts.unshift(names.join(" / ") || "a subject");
    } else if (c.field === "subjectKind") parts.unshift(v);
    else if (c.field === "source")
      parts.push("from " + (v === "gmail" ? "Gmail" : "Classroom"));
    else if (c.field === "sender") parts.push("from " + v);
    else if (c.field === "keyword") parts.push("containing “" + v + "”");
    else if (c.field === "assessmentLabel") parts.push("labelled “" + v + "”");
  }
  const subject =
    parts.length &&
    !parts[0].startsWith("from") &&
    !parts[0].startsWith("containing") &&
    !parts[0].startsWith("labelled")
      ? parts.shift() + " "
      : "";
  const tail = parts.length ? " " + parts.join(" ") : "";
  return rule.action.type === "priority"
    ? `Make ${subject}${what}${tail} ${rule.action.priority} priority`
    : `Hide ${subject}${what}${tail}`;
}

function draftOf(
  doing: Doing,
  target: Target,
  value: string,
  subjects: Subject[],
): Draft {
  const rule: Draft = {
    name: "",
    enabled: true,
    match: "all",
    exceptions: [],
    conditions: [
      {
        field: target,
        op: target === "keyword" ? "contains" : "equals",
        value: value.trim(),
      },
    ],
    action:
      doing === "hide"
        ? { type: "exclude" }
        : { type: "priority", priority: doing },
  };
  return { ...rule, name: describe(rule, subjects).slice(0, 200) };
}

function Builder({
  subjects,
  onPreview,
}: {
  subjects: Subject[];
  onPreview: (d: Draft) => void;
}) {
  const [doing, setDoing] = useState<Doing>("high");
  const [target, setTarget] = useState<Target>("subjectId");
  const [value, setValue] = useState("");
  const choices: Partial<Record<Target, [string, string][]>> = {
    subjectId: subjects.map((s) => [s.id, s.name + " · " + s.kind]),
    taskType: [
      ["test", "Tests"],
      ["assignment", "Assignments"],
    ],
    source: [
      ["gmail", "Gmail"],
      ["classroom", "Classroom"],
    ],
  };
  const options = choices[target];
  return (
    <form
      className="rule-builder"
      onSubmit={(e) => {
        e.preventDefault();
        onPreview(draftOf(doing, target, value, subjects));
      }}
    >
      <select
        aria-label="Do"
        value={doing}
        onChange={(e) => setDoing(e.target.value as Doing)}
      >
        {doings.map(([v, label]) => (
          <option key={v} value={v}>
            {label}
          </option>
        ))}
      </select>
      <span>for</span>
      <select
        aria-label="For"
        value={target}
        onChange={(e) => {
          setTarget(e.target.value as Target);
          setValue("");
        }}
      >
        {targets.map(([v, label]) => (
          <option key={v} value={v}>
            {label}
          </option>
        ))}
      </select>
      {options ? (
        <select
          aria-label="Which"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        >
          <option value="">Choose…</option>
          {options.map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
      ) : (
        <input
          aria-label="Which"
          placeholder={
            target === "sender" ? "name@somaiya.edu" : "e.g. seminar"
          }
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      )}
      <Button variant="outline" disabled={!value.trim()}>
        Preview
      </Button>
    </form>
  );
}

export function Rules({ subjects }: { subjects: Subject[] }) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["rules"],
    queryFn: () => api<{ items: Rule[] }>("/rules"),
  });
  const [sentence, setSentence] = useState("");
  const [preview, setPreview] = useState<Draft | null>(null);
  const [unsupported, setUnsupported] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);
  // Rules apply to every task at once, so lists, counts and the week view all change with them.
  const refresh = () =>
    Promise.all(
      ["rules", "tasks", "task", "overview"].map((key) =>
        client.invalidateQueries({ queryKey: [key] }),
      ),
    );
  const read = useMutation({
    mutationFn: () =>
      api<{ rule: Draft; unsupported: string | null }>(
        "/rules/interpret",
        "POST",
        {
          instruction: sentence,
        },
      ),
    onSuccess: (out) => {
      setPreview({ ...out.rule, exceptions: out.rule.exceptions || [] });
      setUnsupported(out.unsupported);
    },
  });
  const save = useMutation({
    mutationFn: (d: Draft) =>
      api("/rules", "POST", {
        ...d,
        name: describe(d, subjects).slice(0, 200),
      }),
    onSuccess: async () => {
      setPreview(null);
      setSentence("");
      setUnsupported(null);
      await refresh();
    },
  });
  const toggle = useMutation({
    mutationFn: (r: Rule) =>
      api("/rules/" + r.id, "PATCH", {
        revision: r.revision,
        name: r.name,
        enabled: !r.enabled,
        match: r.match,
        conditions: r.conditions,
        exceptions: r.exceptions,
        action: r.action,
        instruction: r.instruction,
      }),
    // The switch flips at once; it reverts if saving fails.
    onMutate: (r: Rule) => {
      client.setQueryData<{ items: Rule[] }>(["rules"], (old) =>
        old
          ? {
              items: old.items.map((x) =>
                x.id === r.id ? { ...x, enabled: !r.enabled } : x,
              ),
            }
          : old,
      );
    },
    onError: refresh,
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (r: Rule) =>
      api("/rules/" + r.id + "?revision=" + r.revision, "DELETE"),
    onSuccess: refresh,
  });
  const items = query.data?.items || [];
  return (
    <>
      <div className="section-bar">
        <div>
          <h2>Rules</h2>
          <p className="text-secondary">
            Tell DueCare what matters to you. Rules apply to all your tasks
            right away, and to new ones as they arrive. Turning a rule off
            undoes it.
          </p>
        </div>
      </div>
      <section className="panel rule-add">
        <form
          className="nl-rule"
          onSubmit={(e) => {
            e.preventDefault();
            read.mutate();
          }}
        >
          <label htmlFor="nl-rule">Add a rule</label>
          <div className="nl-row">
            <input
              id="nl-rule"
              value={sentence}
              onChange={(e) => setSentence(e.target.value)}
              placeholder="e.g. make ITVC high priority · hide seminar mail · tests are critical"
            />
            <Button disabled={read.isPending || sentence.trim().length < 3}>
              {read.isPending ? "Reading…" : "Add"}
            </Button>
          </div>
        </form>
        <ErrorNotice error={read.error} />
        {!preview && (
          <button
            type="button"
            className="link-button"
            onClick={() => setBuilding(!building)}
          >
            {building ? "Hide the builder" : "Or build it yourself"}
          </button>
        )}
        {building && !preview && (
          <Builder
            subjects={subjects}
            onPreview={(d) => {
              setPreview(d);
              setUnsupported(null);
            }}
          />
        )}
        {preview && (
          <div className="rule-preview" role="status">
            <p>
              <strong>{describe(preview, subjects)}.</strong>
            </p>
            {unsupported && (
              <p className="text-secondary text-sm">
                Left out (not something rules can do): {unsupported}
              </p>
            )}
            <div className="rule-preview-actions">
              <Button
                disabled={save.isPending}
                onClick={() => save.mutate(preview)}
              >
                Save rule
              </Button>
              <Button
                variant="ghost"
                onClick={() => {
                  setPreview(null);
                  setBuilding(true);
                }}
              >
                Not right? Build it instead
              </Button>
            </div>
            <ErrorNotice error={save.error} />
          </div>
        )}
      </section>
      <ErrorNotice
        error={query.error || toggle.error || remove.error}
        retry={() => query.refetch()}
      />
      {query.isPending ? (
        <p className="empty-small" role="status">
          Loading rules…
        </p>
      ) : items.length === 0 ? (
        <div className="empty panel">
          <SlidersHorizontal size={28} />
          <h3>No rules yet</h3>
          <p>
            Without rules, every task you get is shown, with priority based on
            its deadline.
          </p>
        </div>
      ) : (
        <ul className="panel rule-list">
          {items.map((r) => (
            <li key={r.id} className={r.enabled ? "" : "disabled"}>
              <div className="rule-text">
                <strong>{describe(r, subjects)}</strong>
                <span>
                  {r.enabled
                    ? `Applies to ${r.affects} ${r.affects === 1 ? "task" : "tasks"}`
                    : "Off"}
                </span>
              </div>
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={r.enabled}
                  disabled={toggle.isPending}
                  onChange={() => toggle.mutate(r)}
                />
                On
              </label>
              <Button
                size="icon"
                variant="ghost"
                aria-label={"Delete rule: " + describe(r, subjects)}
                disabled={remove.isPending}
                onClick={() => remove.mutate(r)}
              >
                <Trash2 size={15} />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <p className="form-help">
        Hidden work is kept, just out of your lists; find it under Tasks → Show
        hidden. If two priority rules match the same task, the older rule wins.
        A priority you set on a task yourself always wins.
      </p>
    </>
  );
}
