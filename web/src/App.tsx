import { useState, type ReactNode } from "react";

import { BriefingPanel } from "./components/BriefingPanel";
import { Card } from "./components/Card";
import { ProjectList } from "./components/ProjectList";
import { RegisterForm } from "./components/RegisterForm";
import { useBriefing, useProjects, useRegisterProject } from "./hooks/useProjects";

function errorText(error: unknown): string | null {
  if (error === null || error === undefined) {
    return null;
  }
  return error instanceof Error ? error.message : "Request failed";
}

export function App(): ReactNode {
  const [selected, setSelected] = useState<string | null>(null);

  const projects = useProjects();
  const briefing = useBriefing(selected);
  const register = useRegisterProject();

  return (
    <main className="mx-auto flex max-w-[var(--page-max-width)] flex-col gap-32 px-24 py-40">
      <header className="flex flex-col gap-8">
        <nav>
          <span className="border-b border-fey-signal pb-4 text-body font-medium text-fey-white">
            Projects
          </span>
        </nav>
        <h1 className="text-display font-bold text-fey-white">
          Project <span className="text-fey-signal">context</span>.
        </h1>
        <p className="text-body text-fey-graphite">
          One shared briefing per project — read by every agent, written by any.
        </p>
      </header>

      <div className="grid gap-24 md:grid-cols-[1fr_2fr]">
        <Card>
          <h2 className="mb-16 text-heading-sm text-fey-white">Projects</h2>
          {projects.isPending ? (
            <p className="text-body text-fey-graphite">Loading…</p>
          ) : projects.isError ? (
            <p className="text-body text-fey-ember">
              {errorText(projects.error)}
            </p>
          ) : (
            <ProjectList
              projects={projects.data}
              selected={selected}
              onSelect={setSelected}
            />
          )}
        </Card>

        <div className="flex flex-col gap-24">
          <Card>
            <h2 className="mb-16 text-heading-sm text-fey-white">
              Register a project
            </h2>
            <RegisterForm
              pending={register.isPending}
              error={errorText(register.error)}
              onSubmit={(input) => {
                register.mutate(input, {
                  onSuccess: (created) => {
                    setSelected(created.name);
                  },
                });
              }}
            />
          </Card>

          <Card>
            <h2 className="mb-16 text-heading-sm text-fey-white">Briefing</h2>
            <BriefingPanel
              project={selected}
              text={briefing.data?.briefing}
              loading={briefing.isFetching}
              error={errorText(briefing.error)}
            />
          </Card>
        </div>
      </div>
    </main>
  );
}
