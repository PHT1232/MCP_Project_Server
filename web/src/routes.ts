/**
 * The shell's route map. Deep links work because the server serves an SPA
 * catch-all (pcs.web_static) that falls back to `index.html`.
 *
 * | Path                                  | View                        |
 * | ------------------------------------- | --------------------------- |
 * | `/`                                   | ProjectsView (picker)       |
 * | `/settings/ai`                         | Global AI settings          |
 * | `/projects/:project/dashboard`        | DashboardView (FR36)        |
 * | `/projects/:project/requirements`     | RequirementsView (FR36a)    |
 * | `/projects/:project/index`            | IndexView (FR37)            |
 * | `/projects/:project/code-map`         | CodeMapView — T07 mounts here|
 *
 * `/projects/:project` redirects to `.../dashboard`.
 */

export const PROJECT_VIEWS = [
  "dashboard",
  "requirements",
  "index",
  "code-map",
] as const;

export type ProjectViewName = (typeof PROJECT_VIEWS)[number];

export function projectRoute(project: string, view: ProjectViewName): string {
  return `/projects/${encodeURIComponent(project)}/${view}`;
}

export const NAV_ITEMS: { view: ProjectViewName; label: string }[] = [
  { view: "dashboard", label: "Dashboard" },
  { view: "requirements", label: "Requirements" },
  { view: "index", label: "Index" },
  { view: "code-map", label: "Code map" },
];

export const AI_SETTINGS_ROUTE = "/settings/ai";
