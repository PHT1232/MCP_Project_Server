/**
 * Turn the top two tiers of a `get_code_map` response into a read-down
 * "codebase map" document (FR32) — a low-resolution written overview of the
 * project's shape, not an interactive graph. The deep detail (symbols, source,
 * dependency lists) stays the agent's job over MCP and the inspector's on click.
 *
 * Pure: no React, no DOM — unit-tested in `codemapDoc.test.ts`.
 */
import type { CodeMap, CodeMapOverlay, Entry } from "../api/types";
import { overlayTone, type OverlayTone } from "./codemap";

/** A directory / file one level below a top-level area. */
export interface DocChild {
  path: string;
  label: string;
  fileCount: number;
  language: string | null;
  tone: OverlayTone | null;
}

/** A top-level area of the repository. */
export interface DocArea {
  path: string;
  label: string;
  kind: "directory" | "file";
  language: string | null;
  fileCount: number;
  loc: number;
  fanIn: number;
  fanOut: number;
  tone: OverlayTone | null;
  /** Human overlay phrases, e.g. `["2 blockers", "current focus"]`. */
  badges: string[];
  /** Labels of the other in-repo areas this one imports. */
  dependsOn: string[];
  children: DocChild[];
  /** Children beyond the ones listed (kept short so the doc stays readable). */
  moreChildren: number;
}

export interface HotSpot {
  path: string;
  reasons: string[];
}

export interface CodeMapDoc {
  projectName: string;
  totalFiles: number;
  languages: string[];
  lastCommit: string | null;
  overview: string | null;
  areas: DocArea[];
  /** Rendered sentences: `"web → server"`. */
  connections: string[];
}

const MAX_CHILDREN = 6;

function plural(n: number, one: string): string {
  return `${String(n)} ${one}${n === 1 ? "" : "s"}`;
}

function overlayBadges(o: CodeMapOverlay): string[] {
  const out: string[] = [];
  if (o.blockers > 0) out.push(plural(o.blockers, "blocker"));
  if (o.bugs > 0) out.push(plural(o.bugs, "bug"));
  if (o.focus > 0) out.push("current focus");
  if (o.requirements > 0) out.push(plural(o.requirements, "requirement"));
  if (o.hot && o.blockers === 0 && o.bugs === 0) out.push("hot");
  return out;
}

function bucket<K, V>(map: Map<K, Set<V>>, key: K): Set<V> {
  let set = map.get(key);
  if (set === undefined) {
    set = new Set<V>();
    map.set(key, set);
  }
  return set;
}

/**
 * Build the document from the top tier (`top`, aggregates + inter-area edges)
 * and, when available, one level deeper (`detail`, for the per-area child list).
 */
export function buildCodeMapDoc(
  top: CodeMap,
  detail: CodeMap | undefined,
  opts: { overview?: string | null } = {},
): CodeMapDoc {
  const byId = new Map(top.nodes.map((node) => [node.id, node] as const));

  // Children grouped by their top-level path segment (drop the area node itself).
  const childrenByArea = new Map<string, DocChild[]>();
  for (const node of detail?.nodes ?? []) {
    const seg = node.path.split("/")[0] ?? node.path;
    if (node.path === seg) {
      continue;
    }
    bucketList(childrenByArea, seg).push({
      path: node.path,
      label: node.path.slice(seg.length + 1) || node.label,
      fileCount: node.file_count,
      language: node.language,
      tone: overlayTone(node.overlay),
    });
  }

  // Inter-area dependency edges → per-area "depends on" + a flat sentence list.
  const dependsOn = new Map<string, Set<string>>();
  const bySource = new Map<string, Set<string>>();
  for (const edge of top.edges) {
    const source = byId.get(edge.source);
    const target = byId.get(edge.target);
    if (source === undefined || target === undefined || source.id === target.id) {
      continue;
    }
    bucket(dependsOn, source.path).add(target.label);
    bucket(bySource, source.label).add(target.label);
  }
  const connections = [...bySource.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([src, targets]) => `${src} → ${[...targets].sort().join(", ")}`);

  const areas: DocArea[] = top.nodes
    .slice()
    .sort((a, b) => b.file_count - a.file_count || a.path.localeCompare(b.path))
    .map((node) => {
      const kids = (childrenByArea.get(node.path) ?? [])
        .slice()
        .sort((a, b) => b.fileCount - a.fileCount || a.path.localeCompare(b.path));
      return {
        path: node.path,
        label: node.label,
        kind: node.kind === "file" ? "file" : "directory",
        language: node.language,
        fileCount: node.file_count,
        loc: node.loc,
        fanIn: node.fan_in,
        fanOut: node.fan_out,
        tone: overlayTone(node.overlay),
        badges: overlayBadges(node.overlay),
        dependsOn: [...(dependsOn.get(node.path) ?? [])].sort(),
        children: kids.slice(0, MAX_CHILDREN),
        moreChildren: Math.max(0, kids.length - MAX_CHILDREN),
      };
    });

  const languages = new Set<string>();
  for (const area of areas) {
    if (area.language !== null && area.language !== "") {
      languages.add(area.language);
    }
    for (const child of area.children) {
      if (child.language !== null && child.language !== "") {
        languages.add(child.language);
      }
    }
  }

  return {
    projectName: top.project_name,
    totalFiles:
      top.stats.total_files ?? areas.reduce((sum, area) => sum + area.fileCount, 0),
    languages: [...languages].sort(),
    lastCommit: top.generated_from.last_commit ?? null,
    overview: opts.overview ?? null,
    areas,
    connections,
  };
}

function bucketList<K, V>(map: Map<K, V[]>, key: K): V[] {
  let list = map.get(key);
  if (list === undefined) {
    list = [];
    map.set(key, list);
  }
  return list;
}

/**
 * The files the open blockers and bugs point at (FR33) — the "where the trouble
 * is" section of the document, straight from the context store's `linked_files`.
 */
export function hotSpotsFromEntries(
  blockers: readonly Entry[],
  bugs: readonly Entry[],
): HotSpot[] {
  const byPath = new Map<string, string[]>();
  const add = (files: readonly string[], reason: string): void => {
    for (const file of files) {
      const key = file.trim().replace(/^\/+|\/+$/g, "");
      if (key === "") {
        continue;
      }
      const reasons = bucketList(byPath, key);
      if (!reasons.includes(reason)) {
        reasons.push(reason);
      }
    }
  };
  for (const entry of blockers) {
    add(entry.linked_files, `blocker: ${entry.headline}`);
  }
  for (const entry of bugs) {
    add(entry.linked_files, `bug: ${entry.headline}`);
  }
  return [...byPath.entries()]
    .map(([path, reasons]) => ({ path, reasons }))
    .sort(
      (a, b) => b.reasons.length - a.reasons.length || a.path.localeCompare(b.path),
    );
}
