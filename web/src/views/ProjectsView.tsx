import type { ReactNode } from "react";

import { Card } from "../components/Card";
import { Callout } from "../components/Callout";
import { ProjectList } from "../components/ProjectList";
import { RegisterForm } from "../components/RegisterForm";
import { Headline, Highlight, SectionTitle } from "../components/Typography";
import { useProjects, useRegisterProject } from "../hooks/useProjects";
import { useNavigate } from "../router/context";
import { errorText } from "../lib/errors";
import { projectRoute } from "../routes";

/** Landing view: pick a project (FR31) or register a new one. */
export function ProjectsView(): ReactNode {
  const projects = useProjects();
  const register = useRegisterProject();
  const navigate = useNavigate();

  return (
    <div className="flex flex-col gap-32">
      <header className="flex flex-col gap-8">
        <Headline>
          Project <Highlight tone="signal">context</Highlight>.
        </Headline>
        <p className="text-body text-fey-graphite">
          One shared briefing per project — read by every agent, written by any.
        </p>
      </header>

      <div className="grid gap-24 md:grid-cols-[1fr_1fr]">
        <Card>
          <div className="flex flex-col gap-16">
            <SectionTitle>Projects</SectionTitle>
            {projects.isPending ? (
              <p className="text-body text-fey-graphite">Loading…</p>
            ) : projects.isError ? (
              <Callout tone="alert">{errorText(projects.error)}</Callout>
            ) : (
              <ProjectList
                projects={projects.data}
                selected={null}
                hrefFor={(name) => projectRoute(name, "dashboard")}
              />
            )}
          </div>
        </Card>

        <Card>
          <div className="flex flex-col gap-16">
            <SectionTitle>Register a project</SectionTitle>
            <RegisterForm
              pending={register.isPending}
              error={errorText(register.error)}
              onSubmit={(input) => {
                register.mutate(input, {
                  onSuccess: (created) => {
                    navigate(projectRoute(created.name, "dashboard"));
                  },
                });
              }}
            />
          </div>
        </Card>
      </div>
    </div>
  );
}
