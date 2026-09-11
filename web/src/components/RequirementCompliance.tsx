import { useState, type ReactNode } from "react";

import type {
  Requirement,
  RequirementComplianceException,
  RequirementComplianceRow as ComplianceRow,
} from "../api/types";
import { useRequirementComplianceDetail } from "../hooks/useRequirementCompliance";
import { errorText } from "../lib/errors";
import { Callout } from "./Callout";
import { PillButton } from "./PillButton";
import { RequirementStatusBadge, StatusBadge, type BadgeTone } from "./StatusBadge";

function exceptionsOf(
  row: ComplianceRow,
  kind: RequirementComplianceException["kind"],
): RequirementComplianceException[] {
  return row.exceptions.filter((exception) => exception.kind === kind);
}

function validationLabel(row: ComplianceRow): string {
  if (!row.configured) return "Not configured";
  if (exceptionsOf(row, "stale").length > 0 || row.validation === "stale") {
    return "Stale";
  }
  if (exceptionsOf(row, "missing").length > 0) return "Missing";
  return "Current";
}

function validationTone(row: ComplianceRow): BadgeTone {
  const label = validationLabel(row);
  if (label === "Current") return "growth";
  if (label === "Not configured") return "graphite";
  return "ember";
}

function reviewLabel(row: ComplianceRow): string {
  if (!row.configured || row.review === "not-configured") return "Not configured";
  return row.review === "passed" ? "Passed" : "Failed";
}

function exceptionLabel(exception: RequirementComplianceException): string {
  return exception.criterion_key ?? exception.invariant_key;
}

function exceptionMetadata(exception: RequirementComplianceException): string {
  return [
    exception.criterion_id,
    exception.violation_id,
    exception.invariant_id,
    ...exception.file_refs,
  ].filter((value): value is string => value !== undefined && value !== "").join(" · ");
}

function Detail({ project, row }: { project: string; row: ComplianceRow }): ReactNode {
  const { contract, evidence } = useRequirementComplianceDetail(
    project,
    row.requirement_id,
    true,
  );
  const missing = exceptionsOf(row, "missing");
  const stale = exceptionsOf(row, "stale");
  const reviewMissing = exceptionsOf(row, "review-missing");
  const reviewFailed = exceptionsOf(row, "review-failed");
  const reviewStale = exceptionsOf(row, "review-stale");
  const blocking = exceptionsOf(row, "blocking");
  const openBlockingViolations = evidence.data?.violations.filter(
    (violation) => violation.status === "open" && violation.severity === "blocking",
  );
  const openWarningViolations = evidence.data?.violations.filter(
    (violation) => violation.status === "open" && violation.severity === "warning",
  );
  const validation = validationLabel(row);

  return (
    <div className="flex flex-col gap-14 border-t border-fey-smoke pt-14">
      <dl className="grid gap-10 text-body text-fey-mist sm:grid-cols-2">
        <div>
          <dt className="text-caption uppercase text-fey-graphite">Acceptance criteria</dt>
          <dd>{row.configured ? `${String(row.ac_verified)}/${String(row.ac_total)} verified` : "Not configured"}</dd>
        </div>
        <div>
          <dt className="text-caption uppercase text-fey-graphite">Validation</dt>
          <dd className={validation === "Current" ? "text-fey-growth" : validation === "Not configured" ? "text-fey-graphite" : "text-fey-ember"}>{validation}</dd>
        </div>
        <div>
          <dt className="text-caption uppercase text-fey-graphite">Independent review</dt>
          <dd>{reviewLabel(row)}</dd>
        </div>
        <div>
          <dt className="text-caption uppercase text-fey-graphite">Blocking violations</dt>
          <dd className={blocking.length > 0 ? "font-semibold text-fey-ember" : "text-fey-growth"}>{String(blocking.length)} open blocking</dd>
        </div>
      </dl>

      {stale.length > 0 && <Callout tone="alert" title="Stale validation">{stale.map(exceptionLabel).join(" · ")}</Callout>}
      {missing.length > 0 && <Callout tone="alert" title="Missing implementation evidence">{missing.map(exceptionLabel).join(" · ")}</Callout>}
      {reviewMissing.map((exception) => (
        <Callout key={exception.criterion_id ?? exception.invariant_id} tone="alert" title={`Independent review missing · ${exceptionLabel(exception)}`}>
          Record passing review evidence from an independent reviewer.
        </Callout>
      ))}
      {reviewFailed.map((exception) => (
        <Callout key={exception.criterion_id ?? exception.invariant_id} tone="alert" title={`Independent review failed · ${exceptionLabel(exception)}`}>
          Record a new passing review from an independent reviewer.
        </Callout>
      ))}
      {reviewStale.map((exception) => (
        <Callout key={exception.criterion_id ?? exception.invariant_id} tone="alert" title={`Independent review stale · ${exceptionLabel(exception)}`}>
          Re-run independent review against the current requirement revision.
        </Callout>
      ))}
      {blocking.map((exception) => (
        <Callout key={exception.violation_id ?? exception.invariant_id} tone="alert" title={`Blocking violation · ${exception.invariant_key}`}>
          {exceptionMetadata(exception)}
        </Callout>
      ))}
      {row.omitted_exceptions > 0 && (
        <Callout tone="alert" title="Additional exceptions omitted">
          {String(row.omitted_exceptions)} more exceptions require drill-down.
        </Callout>
      )}

      {(contract.isPending || evidence.isPending) && <p className="text-body text-fey-graphite">Loading detail…</p>}
      {(contract.isError || evidence.isError) && <Callout tone="alert">{errorText(contract.error ?? evidence.error)}</Callout>}
      {contract.data !== undefined && contract.data.criteria.length > 0 && (
        <ul className="flex flex-col gap-8" aria-label="Acceptance criteria">
          {contract.data.criteria.map((criterion) => (
            <li key={criterion.id} className="rounded-small border border-fey-smoke bg-fey-ink p-14">
              <p className="text-body text-fey-white">{criterion.key}</p>
              <p className="text-caption uppercase text-fey-graphite">{criterion.id} · {criterion.evidence_kind} evidence · review {criterion.independent_review}</p>
            </li>
          ))}
        </ul>
      )}
      {evidence.data !== undefined && (
        <div className="flex flex-col gap-8">
          <p className="text-caption uppercase text-fey-graphite">
            Evidence summary · {String(evidence.data.evidence.length)} shown of {String(evidence.data.evidence_total)}
            {evidence.data.evidence_omitted > 0 ? ` · ${String(evidence.data.evidence_omitted)} omitted` : ""}
          </p>
          <p className="text-caption uppercase text-fey-graphite">
            Warning violations · {String(openWarningViolations?.length ?? 0)} shown open · {String(evidence.data.violations_total)} total
            {evidence.data.violations_omitted > 0 ? ` · ${String(evidence.data.violations_omitted)} violations omitted` : ""}
          </p>
        </div>
      )}
      {openBlockingViolations !== undefined && openBlockingViolations.length > 0 && (
        <ul className="flex flex-col gap-8" aria-label="Open blocking violation details">
          {openBlockingViolations.map((violation) => (
            <li key={violation.id} className="text-body text-fey-ember">{violation.id} · {violation.invariant_id}</li>
          ))}
        </ul>
      )}
      {openWarningViolations !== undefined && openWarningViolations.length > 0 && (
        <ul className="flex flex-col gap-8" aria-label="Open warning violation details">
          {openWarningViolations.map((violation) => (
            <li key={violation.id} className="text-body text-fey-mist">Warning · {violation.id} · {violation.invariant_id}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** T13 — implementation lifecycle and verification are deliberately separate. */
export function RequirementComplianceRow({ project, requirement, row, statusControl }: {
  project: string;
  requirement: Requirement;
  row: ComplianceRow;
  statusControl: ReactNode;
}): ReactNode {
  const [expanded, setExpanded] = useState(false);
  const blocking = exceptionsOf(row, "blocking");
  const prominent = blocking.length > 0 || validationLabel(row) === "Stale";
  return (
    <li className={`flex flex-col gap-14 rounded-small border bg-fey-obsidian p-16 ${prominent ? "border-fey-ember" : "border-fey-smoke"}`}>
      <div className="flex flex-col gap-10">
        <div className="flex items-start justify-between gap-16">
          <p className="text-body font-medium text-fey-white"><span className="text-fey-graphite">{requirement.req_key}</span> {requirement.title}</p>
          <PillButton size="sm" aria-expanded={expanded} onClick={() => { setExpanded((value) => !value); }}>{expanded ? "Hide compliance" : "View compliance"}</PillButton>
        </div>
        <div className="flex flex-wrap items-center gap-8">
          <span className="text-caption uppercase text-fey-graphite">Implementation</span>
          <RequirementStatusBadge status={requirement.status} />
          <span className="text-caption uppercase text-fey-graphite">Verification</span>
          <StatusBadge tone={validationTone(row)}>{validationLabel(row)}</StatusBadge>
          {blocking.length > 0 && <StatusBadge tone="ember">{String(blocking.length)} blocking</StatusBadge>}
          {row.omitted_exceptions > 0 && <StatusBadge tone="ember">{String(row.omitted_exceptions)} omitted</StatusBadge>}
        </div>
        {requirement.linked_files.length > 0 && <p className="text-caption text-fey-graphite">{requirement.linked_files.join(" · ")}</p>}
        {statusControl}
      </div>
      {expanded && <Detail project={project} row={row} />}
    </li>
  );
}
