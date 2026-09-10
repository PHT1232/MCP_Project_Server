import type { ReactElement, ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";

/** Render a component tree with a fresh, retry-free QueryClient. */
export function renderWithClient(ui: ReactElement): RenderResult & {
  client: QueryClient;
} {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  const result = render(
    <QueryClientProvider client={client}>{ui as ReactNode}</QueryClientProvider>,
  );
  return { ...result, client };
}
