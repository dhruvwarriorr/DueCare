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
    for (const label of ["Institution", "Programme", "Department", "Admission year", "General batch"])
      expect(screen.queryByLabelText(label)).not.toBeInTheDocument();
  });
  it("shows attempt-window timing and keeps task status outside the editor", () => {
    wrap(<TaskEditor subjects={[]} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Type"), {
      target: { value: "test" },
    });
    fireEvent.change(screen.getByLabelText("Timing"), {
      target: { value: "attempt_window" },
    });
    expect(
      screen.getByText(
        "The closing time determines when an incomplete test is missed.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Status")).not.toBeInTheDocument();
  });
});
