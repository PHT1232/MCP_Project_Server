import { afterEach, describe, expect, it, vi } from "vitest";

import { downloadFile } from "./download";

describe("downloadFile", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("creates a Blob link with the given filename and content, then clicks it", () => {
    const createObjectURL = vi.fn().mockReturnValue("blob:mock-url");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });

    const click = vi.fn();
    const remove = vi.fn();
    const anchor = {
      href: "",
      download: "",
      rel: "",
      click,
      remove,
    } as unknown as HTMLAnchorElement;
    const createElement = vi
      .spyOn(document, "createElement")
      .mockReturnValue(anchor);
    const appendChild = vi
      .spyOn(document.body, "appendChild")
      .mockImplementation((node) => node);

    downloadFile("demo-context.md", "# hello\n", "text/markdown; charset=utf-8");

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const blob = createObjectURL.mock.calls[0]?.[0] as Blob;
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe("text/markdown; charset=utf-8");

    expect(createElement).toHaveBeenCalledWith("a");
    expect(anchor.href).toBe("blob:mock-url");
    expect(anchor.download).toBe("demo-context.md");
    expect(anchor.rel).toBe("noopener");
    expect(appendChild).toHaveBeenCalledWith(anchor);
    expect(click).toHaveBeenCalledTimes(1);
    expect(remove).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
  });
});
