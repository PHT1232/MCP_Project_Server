import type { ReactNode } from "react";

interface BriefingPanelProps {
  project: string | null;
  text: string | undefined;
  loading: boolean;
  error: string | null;
}

/** Renders the plain-text briefing returned by GET /api/projects/{p}/briefing. */
export function BriefingPanel({
  project,
  text,
  loading,
  error,
}: BriefingPanelProps): ReactNode {
  if (project === null) {
    return (
      <p className="text-body text-fey-graphite">
        Select a project to see its briefing.
      </p>
    );
  }
  if (loading) {
    return <p className="text-body text-fey-graphite">Loading briefing…</p>;
  }
  if (error !== null) {
    return <p className="text-body text-fey-ember">{error}</p>;
  }
  return (
    <pre className="overflow-x-auto whitespace-pre-wrap text-body text-fey-mist">
      {text ?? ""}
    </pre>
  );
}
