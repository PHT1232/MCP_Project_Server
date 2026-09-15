import type { ReactNode } from "react";

import { AI_SETTINGS_ROUTE, NAV_ITEMS, projectRoute } from "../routes";
import { Link } from "../router/router";
import { PillButton } from "./PillButton";
import { PillNav, PillNavLink } from "./PillNav";
import { ProjectPicker } from "./ProjectPicker";

interface AppShellProps {
  project: string | null;
  statusLine: string | null;
  refresh: () => void;
  isRefreshing: boolean;
  lastRefreshedAt: string | null;
  refreshEnabled?: boolean;
  children: ReactNode;
}

/** The application frame: title, project switcher, nav, manual refresh, view. */
export function AppShell({
  project,
  statusLine,
  refresh,
  isRefreshing,
  lastRefreshedAt,
  refreshEnabled = project !== null,
  children,
}: AppShellProps): ReactNode {
  return (
    <div className="mx-auto flex max-w-[var(--page-max-width)] flex-col gap-24 px-24 py-40">
      <header className="flex flex-col gap-16">
        <div className="flex flex-wrap items-center justify-between gap-16">
          <Link
            to="/"
            className="text-heading-sm font-medium text-fey-white no-underline"
          >
            Project context
          </Link>
          <div className="flex flex-wrap items-center gap-16">
            <Link className="text-body text-fey-cornflower no-underline" to={AI_SETTINGS_ROUTE}>
              AI settings
            </Link>
            <ProjectPicker
              current={project}
              hrefFor={(name) => projectRoute(name, "dashboard")}
            />
            <div className="flex items-center gap-8">
              <PillButton
                size="sm"
                onClick={refresh}
                disabled={!refreshEnabled || isRefreshing}
              >
                {isRefreshing ? "Refreshing…" : "Refresh"}
              </PillButton>
              <span className="text-caption uppercase text-fey-graphite">
                {lastRefreshedAt === null
                  ? "as of page load"
                  : `refreshed ${new Date(lastRefreshedAt).toLocaleTimeString()}`}
              </span>
            </div>
          </div>
        </div>

        {project !== null && (
          <div className="flex flex-col gap-10">
            {statusLine !== null && statusLine !== "" && (
              <p className="text-body text-fey-graphite">{statusLine}</p>
            )}
            <PillNav>
              {NAV_ITEMS.map((item) => (
                <PillNavLink
                  key={item.view}
                  to={projectRoute(project, item.view)}
                >
                  {item.label}
                </PillNavLink>
              ))}
            </PillNav>
          </div>
        )}
      </header>

      <main>{children}</main>
    </div>
  );
}
