import type { ReactNode } from "react";

import { Card } from "../components/Card";
import { Callout } from "../components/Callout";
import { PillButton } from "../components/PillButton";
import { SectionTitle } from "../components/Typography";
import { useExportProjectContext } from "../hooks/useExport";
import { useBriefing } from "../hooks/useProjects";
import { errorText } from "../lib/errors";
import { FocusPanel } from "./FocusPanel";
import { OverviewPanel } from "./OverviewPanel";
import { SectionPanel } from "./SectionPanel";

/** FR36 — the non-graph context dashboard for one project. */
export function DashboardView({ project }: { project: string }): ReactNode {
  const briefing = useBriefing(project);
  const exportMutation = useExportProjectContext(project);

  return (
    <div className="flex flex-col gap-24">
      <OverviewPanel project={project} />
      <FocusPanel project={project} />
      <SectionPanel
        project={project}
        section="blockers"
        title="Blockers"
        description="What is stopping progress right now."
      />
      <SectionPanel
        project={project}
        section="bugs"
        title="Bugs"
        description="Known defects worth an agent's attention."
      />
      <SectionPanel
        project={project}
        section="conventions"
        title="Conventions"
        description="How this codebase wants to be worked on."
      />
      <SectionPanel
        project={project}
        section="decisions"
        title="Decisions"
        description="Choices made, with the reasoning behind them."
      />

      <Card surface="elevated">
        <div className="flex flex-col gap-16">
          <SectionTitle>Export project context</SectionTitle>
          <p className="text-body text-fey-graphite">
            Download every context section in full as Markdown or JSON.
            Requirements stay entry-level — no contracts nested underneath.
          </p>
          {exportMutation.isError ? (
            <Callout tone="alert">{errorText(exportMutation.error)}</Callout>
          ) : null}
          <div className="flex flex-wrap gap-12">
            <PillButton
              size="sm"
              disabled={exportMutation.isPending}
              onClick={() => {
                exportMutation.mutate("markdown");
              }}
            >
              Download Markdown
            </PillButton>
            <PillButton
              size="sm"
              disabled={exportMutation.isPending}
              onClick={() => {
                exportMutation.mutate("json");
              }}
            >
              Download JSON
            </PillButton>
          </div>
        </div>
      </Card>

      <Card surface="elevated">
        <div className="flex flex-col gap-16">
          <SectionTitle>Assembled briefing</SectionTitle>
          <p className="text-body text-fey-graphite">
            The exact text `get_project_briefing` returns — your edits above land
            here on the next refresh.
          </p>
          {briefing.isPending ? (
            <p className="text-body text-fey-graphite">Loading…</p>
          ) : briefing.isError ? (
            <Callout tone="alert">{errorText(briefing.error)}</Callout>
          ) : (
            <pre className="overflow-x-auto whitespace-pre-wrap text-body text-fey-mist">
              {briefing.data.briefing}
            </pre>
          )}
        </div>
      </Card>
    </div>
  );
}
