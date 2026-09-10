import type { ReactNode } from "react";

import type { Project } from "../api/types";

interface ProjectListProps {
  projects: Project[];
  selected: string | null;
  onSelect: (name: string) => void;
}

/**
 * The project picker. The selected row carries the one Fey Signal underline
 * (DESIGN.md "Pill Navigation Button" active state) — the page's single
 * chromatic accent.
 */
export function ProjectList({
  projects,
  selected,
  onSelect,
}: ProjectListProps): ReactNode {
  if (projects.length === 0) {
    return (
      <p className="text-body text-fey-graphite">
        No projects yet — register one to get started.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-8">
      {projects.map((project) => {
        const active = project.name === selected;
        return (
          <li key={project.id}>
            <button
              type="button"
              onClick={() => {
                onSelect(project.name);
              }}
              className={
                active
                  ? "border-b border-fey-signal pb-4 text-body font-medium text-fey-white"
                  : "border-b border-transparent pb-4 text-body text-fey-graphite"
              }
            >
              {project.name}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
