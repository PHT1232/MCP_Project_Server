/**
 * A tiny History-API router — enough for the shell's handful of routes without a
 * dependency. The server ships an SPA catch-all (pcs.web_static) so deep links
 * and reloads resolve to `index.html` and this router takes over on the client.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type AnchorHTMLAttributes,
  type ReactNode,
} from "react";

import { RouterContext, useNavigate, type RouterValue } from "./context";

export function RouterProvider({ children }: { children: ReactNode }): ReactNode {
  const [path, setPath] = useState<string>(() => window.location.pathname || "/");

  useEffect(() => {
    const onPop = (): void => {
      setPath(window.location.pathname || "/");
    };
    window.addEventListener("popstate", onPop);
    return () => {
      window.removeEventListener("popstate", onPop);
    };
  }, []);

  const navigate = useCallback<RouterValue["navigate"]>((to, options) => {
    if (options?.replace === true) {
      window.history.replaceState(null, "", to);
    } else {
      window.history.pushState(null, "", to);
    }
    setPath(to.split("?")[0] ?? "/");
    window.scrollTo(0, 0);
  }, []);

  const value = useMemo<RouterValue>(() => ({ path, navigate }), [path, navigate]);

  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>;
}

type LinkProps = AnchorHTMLAttributes<HTMLAnchorElement> & {
  to: string;
  replace?: boolean;
};

export function Link({
  to,
  replace,
  onClick,
  children,
  ...rest
}: LinkProps): ReactNode {
  const navigate = useNavigate();
  return (
    <a
      href={to}
      onClick={(event) => {
        onClick?.(event);
        if (
          event.defaultPrevented ||
          event.button !== 0 ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey
        ) {
          return;
        }
        event.preventDefault();
        navigate(to, replace === true ? { replace: true } : undefined);
      }}
      {...rest}
    >
      {children}
    </a>
  );
}
