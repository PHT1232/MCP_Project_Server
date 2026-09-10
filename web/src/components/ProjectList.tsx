import type { ReactNode } from "react";

import type { Project } from "../api/types";
import { Link } from "../router/router";

interface ProjectListProps {
  projects: Project[];
  /** Currently-open project name, if any (gets the Signal underline). */
  selected: string | null;
  /** Route to open when a project is picked, `{name}` substituted. */
  hrefFor: (name: string) => string;
}

/**
 * The project picker (FR31): each row is a name + its one-line status. The open
 * row carries the single Fey Signal underline (DESIGN.md "Pill Navigation
 * Button" active state) — Signal as a navigation accent, not a status colour.
 */
export function ProjectList({
  projects,
  selected,
  hrefFor,
}: ProjectListProps): ReactNode {
  if (projects.length === 0) {
    return (
      <p className="text-body text-fey-graphite">
        No projects yet — register one to get started.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-14">
      {projects.map((project) => {
        const active = project.name === selected;
        return (
          <li key={project.id}>
            <Link
              to={hrefFor(project.name)}
              className={`flex flex-col gap-4 border-b pb-8 no-underline ${
                active ? "border-fey-signal" : "border-fey-smoke"
              }`}
            >
              <span
                className={`text-body font-medium ${
                  active ? "text-fey-white" : "text-fey-mist"
                }`}
              >
                {project.name}
              </span>
              <span className="text-caption uppercase text-fey-graphite">
                {project.status_line || "no status yet"}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
