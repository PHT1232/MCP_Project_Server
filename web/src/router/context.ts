/**
 * Router primitives with no JSX — the context object, its hooks, and path
 * matching. The `RouterProvider` / `Link` components live in `./router`.
 */
import { createContext, useContext } from "react";

export interface RouterValue {
  path: string;
  navigate: (to: string, options?: { replace?: boolean }) => void;
}

export const RouterContext = createContext<RouterValue | null>(null);

export function useRouter(): RouterValue {
  const value = useContext(RouterContext);
  if (value === null) {
    throw new Error("useRouter must be used within a RouterProvider");
  }
  return value;
}

export function useLocation(): string {
  return useRouter().path;
}

export function useNavigate(): RouterValue["navigate"] {
  return useRouter().navigate;
}

/**
 * Match `pattern` (with `:name` segments) against `path`. Returns the captured
 * params, or `null` if it does not match. A `*` segment matches the rest.
 */
export function matchPath(
  pattern: string,
  path: string,
): Record<string, string> | null {
  const pSegs = pattern.split("/").filter(Boolean);
  const aSegs = path.split("/").filter(Boolean);
  const params: Record<string, string> = {};

  for (let i = 0; i < pSegs.length; i += 1) {
    const p = pSegs[i];
    if (p === "*") {
      return params;
    }
    const a = aSegs[i];
    if (a === undefined) {
      return null;
    }
    if (p?.startsWith(":") === true) {
      params[p.slice(1)] = decodeURIComponent(a);
    } else if (p !== a) {
      return null;
    }
  }
  return pSegs.length === aSegs.length ? params : null;
}
