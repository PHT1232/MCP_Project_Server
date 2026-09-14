import { describe, expect, it, vi } from "vitest";

import {
  addEntry,
  ApiError,
  createAcceptanceCriterion,
  createRequirementInvariant,
  deleteAcceptanceCriterion,
  deleteRequirementInvariant,
  getAiSettings,
  getBriefing,
  getCodeMap,
  getIndexStatus,
  getRequirementContract,
  getRequirementEvidence,
  getSection,
  getSource,
  listProjects,
  listRequirements,
  registerProject,
  reindex,
  reviewRequirementCompliance,
  resolveEntry,
  searchCode,
  setFocus,
  syncRequirements,
  updateAcceptanceCriterion,
  updateAiSettings,
  updateEntry,
  updateRequirementInvariant,
} from "./client";

function mockFetch(body: unknown, ok = true, status = 200): ReturnType<typeof vi.fn> {
  const response = {
    ok,
    status,
    statusText: ok ? "OK" : "Error",
    json: (): Promise<unknown> => Promise.resolve(body),
  };
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(response as Response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function callOf(
  fetchMock: ReturnType<typeof vi.fn>,
): { url: string; init: RequestInit } {
  const call: unknown = fetchMock.mock.calls[0];
  if (!Array.isArray(call)) {
    throw new Error("fetch was not called");
  }
  return { url: call[0] as string, init: (call[1] ?? {}) as RequestInit };
}

describe("api client", () => {
  it("GETs and PATCHes global AI settings", async () => {
    const valid = {
      embedding: { backend: "openai", base_url: "https://embed.test", model: "embed", dimensions: 3, batch_size: 2, timeout_seconds: 10, api_key_configured: false, source: "default" },
      summary: { backend: "openai", base_url: "https://summary.test", model: "summary", timeout_seconds: 10, api_key_configured: false, source: "default" },
      reindex_required: false,
    };
    const fetchMock = mockFetch(valid);

    await getAiSettings();
    expect(callOf(fetchMock).url).toBe("/api/admin/ai-settings");

    fetchMock.mockClear();
    await updateAiSettings({
      summary: {
        backend: "openai",
        base_url: "https://api.example.test",
        model: "summary-model",
        timeout_seconds: 30,
        api_key: null,
      },
    }, "admin-token");
    const { url, init } = callOf(fetchMock);
    expect(url).toBe("/api/admin/ai-settings");
    expect(init.method).toBe("PATCH");
    expect(init.body).toBe(
      JSON.stringify({
        summary: {
          backend: "openai",
          base_url: "https://api.example.test",
          model: "summary-model",
          timeout_seconds: 30,
          api_key: null,
        },
      }),
    );
  });

  it("lists projects from GET /api/projects", async () => {
    const fetchMock = mockFetch([
      { id: "1", name: "acme", root_path: "/r", status_line: "idle" },
    ]);

    const projects = await listProjects();

    expect(fetchMock).toHaveBeenCalledWith("/api/projects", expect.anything());
    expect(projects[0]?.name).toBe("acme");
  });

  it("posts JSON to register a project", async () => {
    const fetchMock = mockFetch(
      { id: "2", name: "beta", root_path: "/b" },
      true,
      201,
    );

    await registerProject({ name: "beta", root_path: "/b", overview: "hi" });

    const { init } = callOf(fetchMock);
    expect(init.method).toBe("POST");
    expect(init.body).toBe(
      JSON.stringify({ name: "beta", root_path: "/b", overview: "hi" }),
    );
  });

  it("encodes the project name in the briefing URL", async () => {
    const fetchMock = mockFetch({ project: "a b", briefing: "text" });

    await getBriefing("a b");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/a%20b/briefing",
      expect.anything(),
    );
  });

  it("throws ApiError with the server's project list on 404", async () => {
    mockFetch(
      { error: "Unknown project 'ghost'.", available: ["acme"] },
      false,
      404,
    );

    const failure: unknown = await getBriefing("ghost").catch(
      (error: unknown) => error,
    );
    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(404);
    expect((failure as ApiError).available).toEqual(["acme"]);
  });

  it("gets a section, optionally including resolved entries", async () => {
    const fetchMock = mockFetch({ section: "blockers", entries: [] });

    await getSection("p", "blockers");
    expect(callOf(fetchMock).url).toBe("/api/projects/p/sections/blockers");

    fetchMock.mockClear();
    await getSection("p", "blockers", true);
    expect(callOf(fetchMock).url).toBe(
      "/api/projects/p/sections/blockers?include_resolved=true",
    );
  });

  it("POSTs a new entry", async () => {
    const fetchMock = mockFetch({ id: "e1", section: "blockers" }, true, 201);

    await addEntry("p", { section: "blockers", headline: "h", detail: "d" });

    const { url, init } = callOf(fetchMock);
    expect(url).toBe("/api/projects/p/entries");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(
      JSON.stringify({ section: "blockers", headline: "h", detail: "d" }),
    );
  });

  it("PATCHes an entry by id", async () => {
    const fetchMock = mockFetch({ id: "e1" });

    await updateEntry("p", "e1", { detail: "new" });

    const { url, init } = callOf(fetchMock);
    expect(url).toBe("/api/projects/p/entries/e1");
    expect(init.method).toBe("PATCH");
  });

  it("POSTs to resolve an entry", async () => {
    const fetchMock = mockFetch({ id: "e1", status: "resolved" });

    await resolveEntry("p", "e1");

    const { url, init } = callOf(fetchMock);
    expect(url).toBe("/api/projects/p/entries/e1/resolve");
    expect(init.method).toBe("POST");
  });

  it("PUTs the current focus (replace semantics)", async () => {
    const fetchMock = mockFetch({ id: "p", name: "p" });

    await setFocus("p", "ship T06");

    const { url, init } = callOf(fetchMock);
    expect(url).toBe("/api/projects/p/focus");
    expect(init.method).toBe("PUT");
    expect(init.body).toBe(JSON.stringify({ text: "ship T06" }));
  });

  it("lists requirements with counts", async () => {
    const fetchMock = mockFetch({
      requirements: [],
      done_count: 3,
      total_count: 8,
    });

    const result = await listRequirements("p");

    expect(callOf(fetchMock).url).toBe("/api/projects/p/requirements");
    expect(result.done_count).toBe(3);
    expect(result.total_count).toBe(8);
  });

  it("reads contract and evidence drill-down endpoints with encoded ids", async () => {
    const fetchMock = mockFetch({ criteria: [], invariants: [] });

    await getRequirementContract("a b", "req/1");
    expect(callOf(fetchMock).url).toBe(
      "/api/projects/a%20b/requirements/req%2F1/contract",
    );

    fetchMock.mockClear();
    await getRequirementEvidence("a b", "req/1");
    expect(callOf(fetchMock).url).toBe(
      "/api/projects/a%20b/requirements/req%2F1/evidence",
    );
  });

  it("POSTs and PATCHes contract authoring routes with encoded ids", async () => {
    const fetchMock = mockFetch({ id: "inv-1" }, true, 201);

    await createRequirementInvariant("a b", "req/1", {
      statement: "Keep adapters thin.",
      kind: "architecture",
      risk: "high",
    });
    expect(callOf(fetchMock).url).toBe(
      "/api/projects/a%20b/requirements/req%2F1/invariants",
    );
    expect(callOf(fetchMock).init.method).toBe("POST");

    fetchMock.mockClear();
    await createAcceptanceCriterion("a b", "inv/1", {
      statement: "Cover MCP and HTTP.",
      evidence_kind: "test",
    });
    expect(callOf(fetchMock).url).toBe(
      "/api/projects/a%20b/requirements/invariants/inv%2F1/criteria",
    );

    fetchMock.mockClear();
    await updateRequirementInvariant("a b", "inv/1", { risk: "low" });
    expect(callOf(fetchMock).url).toBe(
      "/api/projects/a%20b/requirements/invariants/inv%2F1",
    );
    expect(callOf(fetchMock).init.method).toBe("PATCH");
    expect(callOf(fetchMock).init.body).toBe(JSON.stringify({ risk: "low" }));

    fetchMock.mockClear();
    await updateAcceptanceCriterion("a b", "ac/1", { required: false });
    expect(callOf(fetchMock).init.method).toBe("PATCH");
    expect(callOf(fetchMock).url).toBe(
      "/api/projects/a%20b/requirements/criteria/ac%2F1",
    );
  });

  it("DELETEs invariants and criteria", async () => {
    const fetchMock = mockFetch({ id: "inv-1", status: "deleted" });

    await deleteRequirementInvariant("a b", "inv/1");
    expect(callOf(fetchMock).url).toBe(
      "/api/projects/a%20b/requirements/invariants/inv%2F1",
    );
    expect(callOf(fetchMock).init.method).toBe("DELETE");

    fetchMock.mockClear();
    await deleteAcceptanceCriterion("a b", "ac/1");
    expect(callOf(fetchMock).url).toBe(
      "/api/projects/a%20b/requirements/criteria/ac%2F1",
    );
    expect(callOf(fetchMock).init.method).toBe("DELETE");
  });

  it("GETs compliance with repeated, encoded requirement_id params", async () => {
    const fetchMock = mockFetch({ requirements: [] });

    await reviewRequirementCompliance("a b", ["req/1", "req two"]);

    const { url, init } = callOf(fetchMock);
    expect(url).toBe(
      "/api/projects/a%20b/requirements/compliance?requirement_id=req%2F1&requirement_id=req+two",
    );
    expect(init.method).toBeUndefined();
    expect(init.body).toBeUndefined();
  });

  it("POSTs a requirements sync", async () => {
    const fetchMock = mockFetch({ ok: true, requirements: [] });

    await syncRequirements("p");

    const { url, init } = callOf(fetchMock);
    expect(url).toBe("/api/projects/p/requirements/sync");
    expect(init.method).toBe("POST");
  });

  it("gets the index status", async () => {
    const fetchMock = mockFetch({ semantic_available: false });

    await getIndexStatus("p");

    expect(callOf(fetchMock).url).toBe("/api/projects/p/index");
  });

  it("POSTs a reindex with the incremental flag", async () => {
    const fetchMock = mockFetch({ semantic_available: false });

    await reindex("p", false);

    const { url, init } = callOf(fetchMock);
    expect(url).toBe("/api/projects/p/reindex");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ incremental: false }));
  });

  it("gets the top tier of the code map with no scope (FR32a)", async () => {
    const fetchMock = mockFetch({ nodes: [], edges: [], scope: null });

    await getCodeMap("p");

    expect(callOf(fetchMock).url).toBe("/api/projects/p/code-map");
  });

  it("gets a code-map subtree with scope + depth", async () => {
    const fetchMock = mockFetch({ nodes: [], edges: [], scope: "services" });

    await getCodeMap("p", "services", 2);

    expect(callOf(fetchMock).url).toBe(
      "/api/projects/p/code-map?scope=services&depth=2",
    );
  });

  it("gets read-only source with an encoded path", async () => {
    const fetchMock = mockFetch({ path: "a b.py", content: "x", truncated: false });

    await getSource("p", "src/a b.py");

    expect(callOf(fetchMock).url).toBe(
      "/api/projects/p/source?path=src%2Fa+b.py",
    );
  });

  it("searches code with the q param and a limit", async () => {
    const fetchMock = mockFetch({ hits: [], semantic_available: false, mode: "keyword" });

    await searchCode("p", "make_invoice", { limit: 30 });

    expect(callOf(fetchMock).url).toBe(
      "/api/projects/p/search?q=make_invoice&limit=30",
    );
  });
});

describe("AI settings response validation", () => {
  it("rejects malformed GET responses before they enter typed state", async () => {
    mockFetch({ embedding: {}, summary: {}, reindex_required: "no" });
    await expect(getAiSettings()).rejects.toMatchObject({ name: "ApiError", status: 502 });
  });

  it("rejects malformed PATCH responses", async () => {
    mockFetch({ embedding: null, summary: {}, reindex_required: false });
    await expect(updateAiSettings({}, "admin")).rejects.toBeInstanceOf(ApiError);
  });
});
