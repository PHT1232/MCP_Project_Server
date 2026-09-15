import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { RouterProvider } from "./router/router";
import { renderWithClient } from "./test/renderWithClient";

const settings = {
  embedding: { backend: "local", base_url: "http://localhost:11434", model: "embed", dimensions: 768, batch_size: 16, timeout_seconds: 30, api_key_configured: false, source: "default" },
  summary: { backend: "local", base_url: "http://localhost:11434", model: "summary", timeout_seconds: 30, api_key_configured: false, source: "default" },
  reindex_required: false,
};

describe("global AI settings route", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/settings/ai");
    vi.stubGlobal("scrollTo", vi.fn());
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockImplementation((input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const body: unknown = url === "/api/admin/ai-settings" ? settings : [];
      return Promise.resolve({ ok: true, status: 200, statusText: "OK", json: () => Promise.resolve(body) } as Response);
    }));
  });

  it("opens without a selected project and manually refreshes settings", async () => {
    renderWithClient(<RouterProvider><App /></RouterProvider>);
    expect(await screen.findByRole("heading", { name: "Global AI settings" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "AI settings" }).getAttribute("href")).toBe("/settings/ai");
    const refresh = screen.getByRole("button", { name: "Refresh" });
    expect(refresh).toHaveProperty("disabled", false);
    fireEvent.click(refresh);
    await waitFor(() => {
      const settingsCalls = vi
        .mocked(fetch)
        .mock.calls.filter(([input]) => input === "/api/admin/ai-settings");
      expect(settingsCalls).toHaveLength(2);
    });
  });
});
