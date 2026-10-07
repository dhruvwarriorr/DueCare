"use client";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Profile } from "@/lib/types";
import { Field, ErrorNotice } from "./ui/field";
import { Button } from "./ui/button";
const schema = z.object({
  institution: z.string().trim().min(1),
  programme: z.string().trim().min(1),
  department: z.string().trim().min(1),
  admissionYear: z.number().int().min(1950).max(2200),
  classYear: z.string().trim().min(1),
  currentSemester: z.number().int().min(1).max(30),
  division: z.string().trim().min(1),
  generalBatch: z.string().trim().min(1),
  rollNumber: z.string().trim().min(1),
  theme: z.enum(["system", "light", "dark"]),
});
type Values = z.infer<typeof schema>;
export function ProfileForm({ profile }: { profile: Profile }) {
  const query = useQueryClient();
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      institution: profile.institution || "",
      programme: profile.programme || "",
      department: profile.department || "",
      admissionYear: profile.admissionYear,
      classYear: profile.classYear || "",
      currentSemester: profile.currentSemester,
      division: profile.division || "",
      generalBatch: profile.generalBatch || "",
      rollNumber: profile.rollNumber || "",
      theme: profile.theme,
    },
  });
  const save = useMutation({
    mutationFn: (values: Values) =>
      api<Profile>("/me", "PATCH", { ...values, revision: profile.revision }),
    onSuccess: async (p) => {
      query.setQueryData(["me"], p);
      await query.invalidateQueries({ queryKey: ["overview"] });
      await query.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
  const fields = [
    ["institution", "Institution"],
    ["programme", "Programme"],
    ["department", "Department"],
    ["admissionYear", "Admission year"],
    ["classYear", "Class / year"],
    ["currentSemester", "Current semester"],
    ["division", "Division"],
    ["generalBatch", "General batch"],
    ["rollNumber", "Roll number"],
  ] as const;
  return (
    <form
      onSubmit={form.handleSubmit((v) => save.mutate(v))}
      className="panel form-panel"
    >
      <div className="mb-6">
        <h2>
          {profile.onboardingComplete
            ? "Academic profile"
            : "Set up your academic profile"}
        </h2>
        <p className="text-secondary mt-2">
          Your class, semester, division, and batch give your work the right
          context.
        </p>
      </div>
      <div className="identity-row">
        <span className="avatar">
          {profile.identity.name?.slice(0, 1) || "S"}
        </span>
        <div>
          <strong>{profile.identity.name || "Somaiya student"}</strong>
          <p className="text-secondary text-sm">{profile.identity.email}</p>
        </div>
      </div>
      <div className="form-grid">
        {fields.map(([name, label]) => (
          <Field
            key={name}
            label={label}
            id={name}
            error={form.formState.errors[name]?.message}
          >
            <input
              id={name}
              required
              type={
                name === "admissionYear" || name === "currentSemester"
                  ? "number"
                  : "text"
              }
              {...form.register(name, {
                valueAsNumber:
                  name === "admissionYear" || name === "currentSemester",
              })}
            />
          </Field>
        ))}
        <Field label="Appearance" id="theme">
          <select id="theme" {...form.register("theme")}>
            <option value="system">System</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select>
        </Field>
      </div>
      <p className="form-help">
        Enter your batch once. It applies to every theory, lab, and tutorial
        subject. Roll numbers retain leading zeros.
      </p>
      <ErrorNotice error={save.error} />
      <div className="form-footer">
        <span role="status">{save.isSuccess ? "Profile saved" : ""}</span>
        <Button disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save profile"}
        </Button>
      </div>
    </form>
  );
}
