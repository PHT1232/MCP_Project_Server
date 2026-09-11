import { useState, type ReactNode } from "react";

import type { RequirementStatus, SyncReport } from "../api/types";
import { Card } from "../components/Card";
import { Callout } from "../components/Callout";
import { PillButton } from "../components/PillButton";
import { RequirementComplianceRow } from "../components/RequirementCompliance";
import { RequirementsFileNotice } from "../components/RequirementsFileNotice";
import { SectionTitle } from "../components/Typography";
import { Field, Select, TextInput } from "../components/fields";
import { useRequirementCompliance } from "../hooks/useRequirementCompliance";
import { useRequirementMutations, useRequirements } from "../hooks/useRequirements";
import { errorText } from "../lib/errors";
import {
  REQUIREMENT_STATUSES,
  doneFraction,
  doneSummary,
  requirementStatusLabel,
} from "../lib/requirements";

function StatusOptions(): ReactNode {
  return (
    <>
      {REQUIREMENT_STATUSES.map((status) => (
        <option key={status} value={status}>
          {requirementStatusLabel(status)}
        </option>
      ))}
    </>
  );
}

function SyncSummary({ report }: { report: SyncReport }): ReactNode {
  return (
    <Callout tone={report.errors.length > 0 ? "alert" : "muted"} title="Sync report">
      <div className="flex flex-col gap-4">
        <span>
          {report.file_written ? "File updated" : "File unchanged"} · {report.file_path}
        </span>
        <span>
          created {report.created.length} · updated {report.updated.length} ·
          archived {report.archived.length}
        </span>
        {!report.file_writable && (
          <span className="text-fey-mist">
            The requirements file location is read-only. Changes are saved in the
            store (it is authoritative) — mount the project tree read-write to
            keep the file in sync.
          </span>
        )}
        {report.errors.map((err) => (
          <span key={err} className="text-fey-ember">
            {err}
          </span>
        ))}
        {report.reconciliations.map((note) => (
          <span key={`${note.req_key}:${note.message}`}>
            {note.req_key} — {note.message}
          </span>
        ))}
      </div>
    </Callout>
  );
}

/** FR36a — the requirements view: list, N-of-M, add, status change, file sync. */
export function RequirementsView({ project }: { project: string }): ReactNode {
  const query = useRequirements(project);
  const { add, setStatus, sync } = useRequirementMutations(project);

  const [title, setTitle] = useState("");
  const [newStatus, setNewStatus] = useState<RequirementStatus>("not-started");

  const data = query.data;
  const requirementIds = data?.requirements.map((requirement) => requirement.entry_id) ?? [];
  const compliance = useRequirementCompliance(project, requirementIds);
  const verdictById = new Map(
    compliance.data?.requirements.map((verdict) => [verdict.requirement_id, verdict]),
  );
  const fraction = data ? doneFraction(data.done_count, data.total_count) : 0;
  const lastWrite = add.data?.requirements_file ?? setStatus.data?.requirements_file;

  return (
    <div className="flex flex-col gap-24">
      <Card>
        <div className="flex flex-col gap-16">
          <div className="flex items-start justify-between gap-16">
            <div className="flex flex-col gap-4">
              <SectionTitle>Requirements</SectionTitle>
              <p className="text-body text-fey-graphite">
                {data
                  ? doneSummary(data.done_count, data.total_count)
                  : "Loading…"}
              </p>
            </div>
            <PillButton
              size="sm"
              onClick={() => {
                sync.mutate();
              }}
              disabled={sync.isPending}
            >
              {sync.isPending ? "Syncing…" : "Sync file"}
            </PillButton>
          </div>

          <div
            className="h-4 overflow-hidden rounded-small bg-fey-obsidian"
            role="progressbar"
            aria-valuenow={Math.round(fraction * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className="h-4 bg-fey-growth"
              style={{ width: `${String(Math.round(fraction * 100))}%` }}
            />
          </div>

          {sync.isError && <Callout tone="alert">{errorText(sync.error)}</Callout>}
          {sync.data !== undefined && <SyncSummary report={sync.data} />}
          <RequirementsFileNotice sync={lastWrite} />
        </div>
      </Card>

      <Card surface="elevated">
        <form
          className="flex flex-col gap-14"
          onSubmit={(event) => {
            event.preventDefault();
            if (title.trim() === "" || add.isPending) {
              return;
            }
            add.mutate(
              { title: title.trim(), status: newStatus },
              {
                onSuccess: () => {
                  setTitle("");
                  setNewStatus("not-started");
                },
              },
            );
          }}
        >
          <SectionTitle>Add a requirement</SectionTitle>
          <Field label="Title">
            <TextInput
              value={title}
              maxLength={120}
              onChange={(event) => {
                setTitle(event.target.value);
              }}
              required
            />
          </Field>
          <Field label="Status">
            <Select
              value={newStatus}
              onChange={(event) => {
                setNewStatus(event.target.value as RequirementStatus);
              }}
            >
              <StatusOptions />
            </Select>
          </Field>
          <div>
            <PillButton type="submit" size="sm" disabled={add.isPending}>
              {add.isPending ? "Adding…" : "Add requirement"}
            </PillButton>
          </div>
          {add.isError && <Callout tone="alert">{errorText(add.error)}</Callout>}
        </form>
      </Card>

      <Card>
        <div className="flex flex-col gap-16">
          <SectionTitle>All requirements</SectionTitle>
          {(compliance.data?.errors.length ?? 0) > 0 && (
            <Callout tone="alert" title="Compliance unavailable">
              {compliance.data?.errors.join(" ")}
            </Callout>
          )}
          {(compliance.data?.omitted_requirements ?? 0) > 0 && (
            <Callout tone="alert" title="Compliance rows omitted">
              {String(compliance.data?.omitted_requirements)} requirements were omitted by the server.
            </Callout>
          )}
          {query.isPending ? (
            <p className="text-body text-fey-graphite">Loading…</p>
          ) : query.isError ? (
            <Callout tone="alert">{errorText(query.error)}</Callout>
          ) : (data?.requirements.length ?? 0) === 0 ? (
            <p className="text-body text-fey-graphite">
              No requirements yet — add one above or sync the file.
            </p>
          ) : (
            <ul className="flex flex-col gap-10">
              {data?.requirements.map((req) => {
                const verdict = verdictById.get(req.entry_id);
                if (verdict === undefined) {
                  return (
                    <li key={req.req_key} className="flex flex-col gap-10 rounded-small border border-fey-smoke bg-fey-obsidian p-16">
                      <p className="text-body text-fey-white">{req.req_key} · {req.title}</p>
                      <Callout tone={compliance.data?.errors.length ? "alert" : "muted"}>
                        {compliance.data?.errors.length ? "Compliance unavailable for this requirement." : "Loading compliance…"}
                      </Callout>
                      <label className="flex items-center gap-8 text-caption uppercase text-fey-graphite">
                        Set status
                        <Select value={req.status} disabled={setStatus.isPending} onChange={(event) => {
                          setStatus.mutate({ entryId: req.entry_id, status: event.target.value as RequirementStatus });
                        }}>
                          <StatusOptions />
                        </Select>
                      </label>
                    </li>
                  );
                }
                return (
                  <RequirementComplianceRow
                    key={req.req_key}
                    project={project}
                    requirement={req}
                    row={verdict}
                    statusControl={
                      <label className="flex items-center gap-8 text-caption uppercase text-fey-graphite">
                        Set status
                        <Select
                          value={req.status}
                          disabled={setStatus.isPending}
                          onChange={(event) => {
                            setStatus.mutate({
                              entryId: req.entry_id,
                              status: event.target.value as RequirementStatus,
                            });
                          }}
                        >
                          <StatusOptions />
                        </Select>
                      </label>
                    }
                  />
                );
              })}
            </ul>
          )}
          {setStatus.isError && (
            <Callout tone="alert">{errorText(setStatus.error)}</Callout>
          )}
        </div>
      </Card>
    </div>
  );
}
