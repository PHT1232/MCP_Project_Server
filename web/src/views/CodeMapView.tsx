import type { ReactNode } from "react";

import { Card } from "../components/Card";
import { SectionTitle } from "../components/Typography";

/**
 * Seam for T07. The code-map graph, node inspector and code-search UI are out of
 * T06's scope; this route exists so T07 can mount its view here without touching
 * the shell. Route: `/projects/:project/code-map` (see `src/routes.ts`).
 */
export function CodeMapView({ project }: { project: string }): ReactNode {
  return (
    <Card>
      <div className="flex flex-col gap-8">
        <SectionTitle>Code map</SectionTitle>
        <p className="text-body text-fey-graphite">
          The interactive code map for <span className="text-fey-mist">{project}</span>{" "}
          arrives in T07. This route and its nav slot are already wired.
        </p>
      </div>
    </Card>
  );
}
