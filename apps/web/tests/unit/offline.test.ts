import { describe, it, expect, beforeEach } from "vitest";
import { QueryClient, dehydrate } from "@tanstack/react-query";
import { clearSavedData, restoreSaved } from "@/lib/offline";

describe("saved data", () => {
  beforeEach(() => localStorage.clear());
  it("restores the last saved tasks and forgets them on sign-out", () => {
    const source = new QueryClient();
    source.setQueryData(["tasks", "sort=date"], { pages: [{ items: [{ id: "t1" }] }] });
    localStorage.setItem(
      "duecare.saved.v1",
      JSON.stringify({ at: "2026-10-10T12:00:00Z", state: dehydrate(source) }),
    );
    const client = new QueryClient();
    expect(restoreSaved(client)).toBe("2026-10-10T12:00:00Z");
    expect(client.getQueryData(["tasks", "sort=date"])).toEqual({
      pages: [{ items: [{ id: "t1" }] }],
    });
    clearSavedData();
    expect(restoreSaved(new QueryClient())).toBeNull();
  });
  it("ignores missing or damaged saved data", () => {
    expect(restoreSaved(new QueryClient())).toBeNull();
    localStorage.setItem("duecare.saved.v1", "{not json");
    expect(restoreSaved(new QueryClient())).toBeNull();
  });
});
