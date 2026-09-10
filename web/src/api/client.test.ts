import { describe, expect, it, vi } from "vitest";

import { ApiError, getBriefing, listProjects, registerProject } from "./client";

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

function initOf(fetchMock: ReturnType<typeof vi.fn>): RequestInit {
  const call: unknown = fetchMock.mock.calls[0];
  if (!Array.isArray(call) || call.length < 2) {
    throw new Error("fetch was not called with an init argument");
  }
  return call[1] as RequestInit;
}

describe("api client", () => {
  it("lists projects from GET /api/projects", async () => {
    const fetchMock = mockFetch([{ id: "1", name: "acme", root_path: "/r" }]);

    const projects = await listProjects();

    expect(fetchMock).toHaveBeenCalledWith("/api/projects", expect.anything());
    expect(projects).toEqual([{ id: "1", name: "acme", root_path: "/r" }]);
  });

  it("posts JSON to register a project", async () => {
    const fetchMock = mockFetch(
      { id: "2", name: "beta", root_path: "/b" },
      true,
      201,
    );

    await registerProject({ name: "beta", root_path: "/b", overview: "hi" });

    const init = initOf(fetchMock);
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
});
