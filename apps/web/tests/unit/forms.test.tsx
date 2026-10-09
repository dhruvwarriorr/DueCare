import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ProfileForm } from "@/components/profile-form";
import { TaskEditor } from "@/components/task-editor";
import { localTime, utcTime } from "@/lib/api";
import type { Profile } from "@/lib/types";
function wrap(element: React.ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      {element}
    </QueryClientProvider>,
  );
}
describe("manual data entry", () => {
  it("converts IST fields without using the browser timezone", () => {
    expect(localTime("2026-10-20T18:29:00Z")).toBe("2026-10-20T23:59");
    expect(utcTime("2026-10-20T23:59")).toBe("2026-10-20T18:29:00.000Z");
  });
  it("asks for one profile batch and preserves roll number as text", () => {
    const p = {
      id: "id",
      revision: 1,
      identity: {
        id: "id",
        email: "fixture@somaiya.edu",
        name: "Fixture",
        photo: null,
      },
      theme: "system",
      onboardingComplete: false,
      branchOptions: [{ code: "COMPS", name: "Computer Engineering" }],
    } as Profile;
    wrap(<ProfileForm profile={p} />);
    expect(screen.getAllByLabelText("Batch")).toHaveLength(1);
    expect(screen.getByLabelText("Roll number")).toHaveAttribute(
      "type",
      "text",
    );
    expect(screen.getByLabelText("Branch")).toBeRequired();
    expect(screen.getByRole("option", { name: "COMPS" })).toHaveValue("COMPS");
    for (const label of [
      "Institution",
      "Programme",
      "Department",
      "Admission year",
      "General batch",
    ])
      expect(screen.queryByLabelText(label)).not.toBeInTheDocument();
  });
  it("asks only for a deadline date and optional time", () => {
    wrap(<TaskEditor subjects={[]} onClose={vi.fn()} />);
    const time = screen.getByLabelText("Deadline time (optional)");
    expect(time).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Deadline date"), {
      target: { value: "2026-10-20" },
    });
    expect(time).not.toBeDisabled();
    expect(
      screen.getByText("Without a time, it's due by 23:59 IST that day."),
    ).toBeInTheDocument();
    for (const label of [
      "Status",
      "Instructions",
      "Estimated effort (minutes)",
      "Timing",
    ])
      expect(screen.queryByLabelText(label)).not.toBeInTheDocument();
  });
});
