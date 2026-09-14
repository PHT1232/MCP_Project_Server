import { useEffect, type ReactNode } from "react";

import { AppShell } from "./components/AppShell";
import { Card } from "./components/Card";
import { useProject } from "./hooks/useProjects";
import { useRefreshAll } from "./hooks/useRefresh";
import { matchPath, useLocation, useNavigate } from "./router/context";
import { AI_SETTINGS_ROUTE, PROJECT_VIEWS, projectRoute, type ProjectViewName } from "./routes";
import { AiSettingsView } from "./views/AiSettingsView";
import { CodeMapView } from "./views/CodeMapView";
import { DashboardView } from "./views/DashboardView";
import { IndexView } from "./views/IndexView";
import { ProjectsView } from "./views/ProjectsView";
import { RequirementsView } from "./views/RequirementsView";

interface Resolved {
  project: string | null;
  view: ProjectViewName | null;
  redirectTo: string | null;
}

function resolve(path: string): Resolved {
  if (path === "/" || path === "") {
    return { project: null, view: null, redirectTo: null };
  }
  const viewMatch = matchPath("/projects/:project/:view", path);
  if (viewMatch) {
    const project = viewMatch.project ?? "";
    const view = viewMatch.view ?? "";
    if ((PROJECT_VIEWS as readonly string[]).includes(view)) {
      return { project, view: view as ProjectViewName, redirectTo: null };
    }
    return { project, view: null, redirectTo: projectRoute(project, "dashboard") };
  }
  const bare = matchPath("/projects/:project", path);
  if (bare) {
    const project = bare.project ?? "";
    return {
      project,
      view: null,
      redirectTo: projectRoute(project, "dashboard"),
    };
  }
  return { project: null, view: null, redirectTo: "/" };
}

function ProjectView({
  project,
  view,
}: {
  project: string;
  view: ProjectViewName;
}): ReactNode {
  switch (view) {
    case "dashboard":
      return <DashboardView project={project} />;
    case "requirements":
      return <RequirementsView project={project} />;
    case "index":
      return <IndexView project={project} />;
    case "code-map":
      return <CodeMapView project={project} />;
  }
}

export function App(): ReactNode {
  const path = useLocation();
  const navigate = useNavigate();
  const globalAiSettings = path === AI_SETTINGS_ROUTE;
  const { project, view, redirectTo } = globalAiSettings
    ? { project: null, view: null, redirectTo: null }
    : resolve(path);

  useEffect(() => {
    if (redirectTo !== null) {
      navigate(redirectTo, { replace: true });
    }
  }, [redirectTo, navigate]);

  const projectRow = useProject(project);
  const refresh = useRefreshAll(project, globalAiSettings);

  let content: ReactNode;
  if (redirectTo !== null) {
    content = (
      <Card>
        <p className="text-body text-fey-graphite">Loading…</p>
      </Card>
    );
  } else if (globalAiSettings) {
    content = <AiSettingsView />;
  } else if (project === null || view === null) {
    content = <ProjectsView />;
  } else {
    content = <ProjectView project={project} view={view} />;
  }

  return (
    <AppShell
      project={project}
      statusLine={projectRow?.status_line ?? null}
      refresh={refresh.refresh}
      isRefreshing={refresh.isRefreshing}
      lastRefreshedAt={refresh.lastRefreshedAt}
      refreshEnabled={project !== null || globalAiSettings}
    >
      {content}
    </AppShell>
  );
}
