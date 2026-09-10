import type { ReactNode } from "react";

import { useProjects } from "../hooks/useProjects";
import { useNavigate } from "../router/context";
import { Select } from "./fields";

interface ProjectPickerProps {
  current: string | null;
  /** Route to open on pick, `{name}` substituted. */
  hrefFor: (name: string) => string;
}

/** Header project switcher (FR31). */
export function ProjectPicker({
  current,
  hrefFor,
}: ProjectPickerProps): ReactNode {
  const projects = useProjects();
  const navigate = useNavigate();

  if (!projects.data || projects.data.length === 0) {
    return null;
  }

  return (
    <label className="flex items-center gap-8 text-caption uppercase text-fey-graphite">
      Project
      <Select
        value={current ?? ""}
        onChange={(event) => {
          if (event.target.value !== "") {
            navigate(hrefFor(event.target.value));
          }
        }}
      >
        {current === null && <option value="">Select…</option>}
        {projects.data.map((project) => (
          <option key={project.id} value={project.name}>
            {project.name}
          </option>
        ))}
      </Select>
    </label>
  );
}
