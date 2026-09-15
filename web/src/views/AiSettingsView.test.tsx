import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { queryKeys } from "../api/queryKeys";
import type { AiSettings } from "../api/types";
import { renderWithClient } from "../test/renderWithClient";
import { AiSettingsView } from "./AiSettingsView";

const SETTINGS: AiSettings = {
  embedding: { backend: "openai", base_url: "https://embedding.example.test", model: "embed-v1", dimensions: 1536, batch_size: 64, timeout_seconds: 30, api_key_configured: true, source: "environment" },
  summary: { backend: "openai", base_url: "https://summary.example.test", model: "summary-v1", timeout_seconds: 45, api_key_configured: false, source: "default" },
  reindex_required: true,
};
const PROJECTS = [{ id: "1", name: "acme", root_path: "/acme", status_line: "ready", briefing_token_budget: 1, prepare_task_token_budget: 1, headline_max_chars: 1, detail_max_chars: 1, expiry_policy: "none", expiry_days: null }];

function response(body: unknown, ok = true): Response {
  return { ok, status: ok ? 200 : 400, statusText: ok ? "OK" : "Bad Request", json: () => Promise.resolve(body) } as Response;
}
function body(call: unknown): unknown {
  if (!Array.isArray(call) || typeof (call[1] as RequestInit).body !== "string") throw new Error("request body missing");
  return JSON.parse((call[1] as RequestInit).body as string) as unknown;
}
function fetchForSettings(): ReturnType<typeof vi.fn> {
  return vi.fn<typeof fetch>().mockImplementation((input) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url === "/api/admin/ai-settings") return Promise.resolve(response(SETTINGS));
    if (url === "/api/projects") return Promise.resolve(response(PROJECTS));
    if (url.endsWith("/reindex")) return Promise.resolve(response({ state: "ready" }));
    return Promise.reject(new Error(`unexpected ${url}`));
  });
}

async function renderSettings(fetchMock = fetchForSettings()) {
  vi.stubGlobal("fetch", fetchMock);
  const rendered = renderWithClient(<AiSettingsView />);
  await screen.findByRole("heading", { name: "Embedding provider" });
  return { ...rendered, fetchMock };
}

describe("AI settings", () => {
  it("renders independent forms with blank in-memory secret fields", async () => {
    await renderSettings();
    expect(screen.getByRole("heading", { name: "Global AI settings" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Summary provider" })).toBeTruthy();
    expect(screen.getAllByRole("textbox").length).toBeGreaterThan(2);
    expect(screen.getByPlaceholderText("Configured")).toHaveProperty("value", "");
    expect(screen.getByPlaceholderText("Not configured")).toHaveProperty("value", "");
  });

  it("updates UI from the redacted PATCH response without caching submitted credentials", async () => {
    const secret = "api-secret-value";
    const token = "admin-secret-value";
    const updated: AiSettings = {
      ...SETTINGS,
      embedding: {
        ...SETTINGS.embedding,
        model: "embed-v2",
        api_key_configured: false,
        source: "persisted",
      },
      reindex_required: false,
    };
    const fetchMock = fetchForSettings();
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(SETTINGS)));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(PROJECTS)));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(updated)));
    const { client } = await renderSettings(fetchMock);
    const form = screen.getByRole("button", { name: "Save embedding settings" }).closest("form");
    if (!form) throw new Error("embedding form missing");
    const key = within(form).getByPlaceholderText("Configured");
    const admin = within(form).getAllByDisplayValue("").at(-1);
    if (!admin) throw new Error("admin token missing");
    fireEvent.change(within(form).getByLabelText("Model"), { target: { value: "embed-v2" } });
    fireEvent.change(key, { target: { value: secret } });
    fireEvent.change(admin, { target: { value: token } });
    fireEvent.click(within(form).getByRole("button", { name: "Save embedding settings" }));
    await within(form).findByText("Settings saved.");
    expect(key).toHaveProperty("value", "");
    expect(admin).toHaveProperty("value", "");
    expect(within(form).getByLabelText("Model")).toHaveProperty("value", "embed-v2");
    expect(within(form).getByText("No API key")).toBeTruthy();
    expect(within(form).getByText("Source: Saved override")).toBeTruthy();
    expect(screen.queryByText("Reindex required")).toBeNull();
    expect(client.getQueryData(queryKeys.aiSettings)).toEqual(updated);
    expect(JSON.stringify(client.getQueryCache().getAll())).not.toContain(secret);
    expect(JSON.stringify(client.getMutationCache().getAll())).not.toContain(secret);
    expect(JSON.stringify(client.getMutationCache().getAll())).not.toContain(token);
    const headers = new Headers((fetchMock.mock.calls.at(-1)?.[1] as RequestInit).headers);
    expect(headers.get("x-pcs-admin-token")).toBe(token);
  });

  it("preserves nonsecret values, redacts reflected secrets, and supports explicit clearing", async () => {
    const secret = "never-render-this-secret";
    const fetchMock = fetchForSettings();
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(SETTINGS)));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response(PROJECTS)));
    fetchMock.mockImplementationOnce(() => Promise.resolve(response({ error: `invalid ${secret}` }, false)));
    const { fetchMock: calls } = await renderSettings(fetchMock);
    const form = screen.getByRole("button", { name: "Save summary settings" }).closest("form");
    if (!form) throw new Error("summary form missing");
    const model = within(form).getByLabelText("Model");
    fireEvent.change(model, { target: { value: "summary-v2" } });
    fireEvent.change(within(form).getByPlaceholderText("Not configured"), { target: { value: secret } });
    fireEvent.click(within(form).getByRole("button", { name: "Save summary settings" }));
    await within(form).findByRole("alert");
    expect(model).toHaveProperty("value", "summary-v2");
    expect(screen.queryByText(new RegExp(secret))).toBeNull();
    const embeddingForm = screen.getByRole("button", { name: "Save embedding settings" }).closest("form");
    if (!embeddingForm) throw new Error("embedding form missing");
    fireEvent.click(within(embeddingForm).getByRole("button", { name: "Clear saved key" }));
    fireEvent.click(within(embeddingForm).getByRole("button", { name: "Save embedding settings" }));
    await waitFor(() => { expect(calls.mock.calls.length).toBeGreaterThan(3); });
    expect(body(calls.mock.calls.at(-1))).toMatchObject({ embedding: { api_key: null } });
  });

  it("selects a project for full reindex and invalidates AI settings", async () => {
    const { client, fetchMock } = await renderSettings();
    await screen.findByRole("option", { name: "acme" });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const projectPicker = screen.getAllByRole("combobox")[0];
    if (!projectPicker) throw new Error("project picker missing");
    fireEvent.change(projectPicker, { target: { value: "acme" } });
    fireEvent.click(screen.getByRole("button", { name: "Run full reindex" }));
    await waitFor(() => { expect(fetchMock.mock.calls.some((call) => call[0] === "/api/projects/acme/reindex")).toBe(true); });
    expect(body(fetchMock.mock.calls.find((call) => call[0] === "/api/projects/acme/reindex"))).toEqual({ incremental: false });
    await waitFor(() => { expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.aiSettings }); });
  });
});
