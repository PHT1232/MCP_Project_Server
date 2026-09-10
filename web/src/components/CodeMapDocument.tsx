import type { ReactNode } from "react";

import type { CodeMapDoc, DocArea, HotSpot } from "../lib/codemapDoc";
import { CodeMapLegend } from "./CodeMapLegend";
import { StatusBadge } from "./StatusBadge";
import { Caption, SectionTitle } from "./Typography";

function plural(n: number, one: string): string {
  return `${String(n)} ${one}${n === 1 ? "" : "s"}`;
}

interface CodeMapDocumentProps {
  doc: CodeMapDoc;
  hotSpots: HotSpot[];
  legend: readonly string[];
  /** Open a path in the inspector (locates + expands the map as needed). */
  onSelectPath: (path: string) => void;
}

function PathButton({
  path,
  label,
  onSelectPath,
  strong = false,
}: {
  path: string;
  label: string;
  onSelectPath: (path: string) => void;
  strong?: boolean;
}): ReactNode {
  return (
    <button
      type="button"
      onClick={() => {
        onSelectPath(path);
      }}
      className={`text-left text-body underline-offset-2 hover:underline ${
        strong ? "text-fey-white hover:text-fey-mist" : "text-fey-mist hover:text-fey-white"
      }`}
    >
      {label}
    </button>
  );
}

function AreaBlock({
  area,
  onSelectPath,
}: {
  area: DocArea;
  onSelectPath: (path: string) => void;
}): ReactNode {
  const suffix = area.kind === "directory" ? "/" : "";
  return (
    <div className="flex flex-col gap-6 border-l border-fey-smoke pl-16">
      <div className="flex flex-wrap items-baseline gap-8">
        <PathButton
          path={area.path}
          label={`${area.label}${suffix}`}
          onSelectPath={onSelectPath}
          strong
        />
        {area.tone !== null && (
          <StatusBadge tone={area.tone}>{area.badges[0] ?? area.tone}</StatusBadge>
        )}
      </div>

      <Caption>
        {plural(area.fileCount, "file")}
        {area.loc > 0 ? ` · ${area.loc.toLocaleString()} LOC` : ""}
        {area.language !== null ? ` · ${area.language}` : ""}
        {area.fanIn > 0 || area.fanOut > 0
          ? ` · imported by ${String(area.fanIn)}, imports ${String(area.fanOut)}`
          : ""}
      </Caption>

      {area.badges.length > 1 && (
        <div className="flex flex-wrap gap-6">
          {area.badges.slice(1).map((badge) => (
            <span key={badge} className="text-caption uppercase text-fey-graphite">
              {badge}
            </span>
          ))}
        </div>
      )}

      {area.dependsOn.length > 0 && (
        <Caption>Depends on {area.dependsOn.join(", ")}</Caption>
      )}

      {area.children.length > 0 && (
        <ul className="flex flex-col gap-4">
          {area.children.map((child) => (
            <li key={child.path} className="flex flex-wrap items-baseline gap-8">
              <PathButton
                path={child.path}
                label={child.label}
                onSelectPath={onSelectPath}
              />
              <span className="text-caption text-fey-graphite">
                {plural(child.fileCount, "file")}
              </span>
              {child.tone !== null && (
                <StatusBadge tone={child.tone}>{child.tone}</StatusBadge>
              )}
            </li>
          ))}
          {area.moreChildren > 0 && (
            <li className="text-caption text-fey-graphite">
              +{String(area.moreChildren)} more
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

/**
 * FR32 — the code map as a read-down document: an overview, the top-level
 * structure with per-area metrics and dependencies, the open hot spots, and how
 * the areas connect. Every path is a button that opens the inspector below.
 */
export function CodeMapDocument({
  doc,
  hotSpots,
  legend,
  onSelectPath,
}: CodeMapDocumentProps): ReactNode {
  return (
    <div className="flex flex-col gap-24">
      {doc.overview !== null && doc.overview !== "" && (
        <section className="flex flex-col gap-8">
          <SectionTitle>Overview</SectionTitle>
          <p className="whitespace-pre-wrap text-body text-fey-mist">{doc.overview}</p>
        </section>
      )}

      <section className="flex flex-col gap-16">
        <SectionTitle>Structure</SectionTitle>
        <CodeMapLegend legend={legend} />
        {doc.areas.length === 0 ? (
          <p className="text-body text-fey-graphite">No indexed files.</p>
        ) : (
          doc.areas.map((area) => (
            <AreaBlock key={area.path} area={area} onSelectPath={onSelectPath} />
          ))
        )}
      </section>

      {hotSpots.length > 0 && (
        <section className="flex flex-col gap-8">
          <SectionTitle>Hot spots</SectionTitle>
          <ul className="flex flex-col gap-8">
            {hotSpots.map((spot) => (
              <li key={spot.path} className="flex flex-col gap-4">
                <PathButton
                  path={spot.path}
                  label={spot.path}
                  onSelectPath={onSelectPath}
                  strong
                />
                {spot.reasons.map((reason) => (
                  <span key={reason} className="text-caption text-fey-graphite">
                    {reason}
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="flex flex-col gap-8">
        <SectionTitle>How it connects</SectionTitle>
        {doc.connections.length === 0 ? (
          <p className="text-body text-fey-graphite">
            No cross-area dependencies were resolved in the index.
          </p>
        ) : (
          <ul className="flex flex-col gap-4">
            {doc.connections.map((line) => (
              <li key={line} className="text-body text-fey-mist">
                {line}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
