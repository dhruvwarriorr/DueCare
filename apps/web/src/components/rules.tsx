"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  Sparkles,
  Trash2,
  SlidersHorizontal,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Rule, RuleCondition, Subject } from "@/lib/types";
import { Button } from "./ui/button";
import { ErrorNotice, Field } from "./ui/field";

type Draft = Omit<Rule, "id" | "position" | "revision">;
const fieldLabels: Record<RuleCondition["field"], string> = {
  keyword: "Text contains",
  sender: "Sender",
  source: "Source",
  subjectId: "Subject",
  subjectKind: "Subject kind",
  taskType: "Task type",
  assessmentLabel: "Assessment label",
};
const blank: Draft = {
  name: "",
  enabled: true,
  match: "all",
  conditions: [{ field: "keyword", op: "contains", value: "" }],
  exceptions: [],
  action: { type: "exclude" },
};

function describe(rule: Draft, subjects: Subject[]) {
  const cond = rule.conditions
    .map((c) => {
      const value = Array.isArray(c.value) ? c.value.join(", ") : c.value;
      const shown =
        c.field === "subjectId"
          ? subjects.find((s) => s.id === value)?.name || value
          : value;
      const what =
        c.field === "keyword" ? "the text" : fieldLabels[c.field].toLowerCase();
      return `${what} ${c.op === "contains" ? "contains" : "is"} “${shown}”`;
    })
    .join(rule.match === "all" ? " and " : " or ");
  const act =
    rule.action.type === "priority"
      ? `set priority to ${rule.action.priority}`
      : rule.action.type === "exclude"
        ? "don’t add the task"
        : "add the task";
  return `When ${cond}, ${act}.`;
}

function Editor({
  subjects,
  initial,
  onDone,
}: {
  subjects: Subject[];
  initial?: Draft;
  onDone: () => void;
}) {
  const client = useQueryClient();
  const [draft, setDraft] = useState<Draft>(initial || blank);
  const cond = draft.conditions[0];
  const save = useMutation({
    mutationFn: () => api("/rules", "POST", draft),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["rules"] });
      onDone();
    },
  });
  const setCond = (patch: Partial<RuleCondition>) =>
    setDraft({
      ...draft,
      conditions: [{ ...cond, ...patch }, ...draft.conditions.slice(1)],
    });
  const valueInput =
    cond.field === "subjectId" ? (
      <select
        id="rule-value"
        value={String(cond.value)}
        onChange={(e) => setCond({ value: e.target.value })}
      >
        <option value="">Choose a subject</option>
        {subjects.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name} · {s.kind}
          </option>
        ))}
      </select>
    ) : cond.field === "taskType" ||
      cond.field === "subjectKind" ||
      cond.field === "source" ? (
      <select
        id="rule-value"
        value={String(cond.value)}
        onChange={(e) => setCond({ value: e.target.value })}
      >
        <option value="">Choose</option>
        {{
          taskType: ["assignment", "test"],
          subjectKind: ["theory", "lab", "tutorial"],
          source: ["gmail", "classroom"],
        }[cond.field].map((v) => (
          <option key={v}>{v}</option>
        ))}
      </select>
    ) : (
      <input
        id="rule-value"
        value={String(cond.value)}
        onChange={(e) => setCond({ value: e.target.value })}
      />
    );
  return (
    <form
      className="panel rule-editor"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <div className="form-grid">
        <Field id="rule-name" label="Rule name">
          <input
            id="rule-name"
            required
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
        </Field>
        <Field id="rule-field" label="When">
          <select
            id="rule-field"
            value={cond.field}
            onChange={(e) => {
              const field = e.target.value as RuleCondition["field"];
              setCond({
                field,
                op: field === "keyword" ? "contains" : "equals",
                value: "",
              });
            }}
          >
            {Object.entries(fieldLabels).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </Field>
        <Field id="rule-value" label="Value">
          {valueInput}
        </Field>
        <Field id="rule-action" label="Then">
          <select
            id="rule-action"
            value={
              draft.action.type === "priority"
                ? "priority:" + draft.action.priority
                : draft.action.type
            }
            onChange={(e) => {
              const [type, priority] = e.target.value.split(":");
              setDraft({
                ...draft,
                action:
                  type === "priority"
                    ? { type: "priority", priority }
                    : { type: type as "include" | "exclude" },
              });
            }}
          >
            <option value="exclude">Don’t add the task</option>
            <option value="include">Add the task</option>
            {["critical", "high", "medium", "low"].map((p) => (
              <option key={p} value={"priority:" + p}>
                Set priority: {p}
              </option>
            ))}
          </select>
        </Field>
      </div>
      {draft.conditions.length > 1 && (
        <p className="text-sm text-secondary">
          Plus {draft.conditions.length - 1} more condition(s) from the preview.
        </p>
      )}
      <p className="text-sm">{describe(draft, subjects)}</p>
      <ErrorNotice error={save.error} />
      <div className="form-footer">
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button disabled={save.isPending || !String(cond.value).trim()}>
          Save rule
        </Button>
      </div>
    </form>
  );
}

export function Rules({ subjects }: { subjects: Subject[] }) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["rules"],
    queryFn: () => api<{ items: Rule[] }>("/rules"),
  });
  const [editing, setEditing] = useState<Draft | null>(null);
  const [instruction, setInstruction] = useState("");
  const [unsupported, setUnsupported] = useState<string | null>(null);
  const refresh = () => client.invalidateQueries({ queryKey: ["rules"] });
  const interpret = useMutation({
    mutationFn: () =>
      api<{ rule: Draft; unsupported: string | null }>(
        "/rules/interpret",
        "POST",
        { instruction },
      ),
    onSuccess: (out) => {
      // A preview only: nothing is active until the student saves it.
      setEditing({ ...out.rule, exceptions: out.rule.exceptions || [] });
      setUnsupported(out.unsupported);
    },
  });
  const update = useMutation({
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
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (r: Rule) =>
      api("/rules/" + r.id + "?revision=" + r.revision, "DELETE"),
    onSuccess: refresh,
  });
  const order = useMutation({
    mutationFn: (ids: string[]) => api("/rules/order", "PUT", { ids }),
    onSuccess: refresh,
  });
  const items = query.data?.items || [];
  const move = (i: number, d: number) => {
    const ids = items.map((r) => r.id);
    [ids[i], ids[i + d]] = [ids[i + d], ids[i]];
    order.mutate(ids);
  };
  return (
    <>
      <div className="section-bar">
        <div>
          <h2>Rules</h2>
          <p className="text-secondary">
            Rules apply to newly detected work, in order: the first matching
            relevance rule decides whether a task is added, and the first
            matching priority rule sets priority. Sender blocks and
            class/division/batch checks always come first, and rules never hide
            submission evidence.
          </p>
        </div>
        <Button
          onClick={() => {
            setEditing(blank);
            setUnsupported(null);
          }}
        >
          <SlidersHorizontal size={16} />
          New rule
        </Button>
      </div>
      <form
        className="panel nl-rule"
        onSubmit={(e) => {
          e.preventDefault();
          interpret.mutate();
        }}
      >
        <Field id="nl-rule" label="Describe a rule in your own words">
          <input
            id="nl-rule"
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder="Make every DBMS test high priority"
          />
        </Field>
        <Button
          variant="outline"
          disabled={interpret.isPending || instruction.trim().length < 3}
        >
          <Sparkles size={15} />
          Preview rule
        </Button>
      </form>
      <ErrorNotice error={interpret.error} />
      {unsupported && (
        <p className="sync-line warn mb-4">
          Not supported and left out: {unsupported}
        </p>
      )}
      {editing && (
        <Editor
          key={JSON.stringify(editing)}
          subjects={subjects}
          initial={editing}
          onDone={() => setEditing(null)}
        />
      )}
      <ErrorNotice
        error={query.error || update.error || remove.error || order.error}
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
            Without rules, applicable assignments and tests are added with
            deadline-based priority.
          </p>
        </div>
      ) : (
        <ol className="panel rule-list">
          {items.map((r, i) => (
            <li key={r.id} className={r.enabled ? "" : "disabled"}>
              <span className="rule-order">{i + 1}</span>
              <div className="rule-text">
                <strong>{r.name}</strong>
                <span>{describe(r, subjects)}</span>
              </div>
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={r.enabled}
                  disabled={update.isPending}
                  onChange={() => update.mutate(r)}
                />
                Enabled
              </label>
              <Button
                size="icon"
                variant="ghost"
                aria-label={"Move " + r.name + " up"}
                disabled={i === 0 || order.isPending}
                onClick={() => move(i, -1)}
              >
                <ArrowUp size={15} />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                aria-label={"Move " + r.name + " down"}
                disabled={i === items.length - 1 || order.isPending}
                onClick={() => move(i, 1)}
              >
                <ArrowDown size={15} />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                aria-label={"Delete " + r.name}
                disabled={remove.isPending}
                onClick={() => remove.mutate(r)}
              >
                <Trash2 size={15} />
              </Button>
            </li>
          ))}
        </ol>
      )}
      <p className="form-help">
        Rule changes apply to future imports. Use “Reprocess” on a source to
        apply them to earlier mail.
      </p>
    </>
  );
}
