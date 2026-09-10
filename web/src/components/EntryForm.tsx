import { useState, type ReactNode } from "react";

import type { EntryInput } from "../api/types";
import { PillButton } from "./PillButton";
import { Field, TextArea, TextInput } from "./fields";

interface EntryFormProps {
  initialHeadline?: string;
  initialDetail?: string;
  /** Show the headline input. Off for focus (detail-only). */
  withHeadline?: boolean;
  submitLabel: string;
  pending: boolean;
  onSubmit: (input: EntryInput) => void;
  onCancel?: () => void;
}

/** Shared create/edit form for a context entry (headline + detail). */
export function EntryForm({
  initialHeadline = "",
  initialDetail = "",
  withHeadline = true,
  submitLabel,
  pending,
  onSubmit,
  onCancel,
}: EntryFormProps): ReactNode {
  const [headline, setHeadline] = useState(initialHeadline);
  const [detail, setDetail] = useState(initialDetail);

  const canSubmit =
    (withHeadline ? headline.trim() !== "" : true) && detail.trim() !== "";

  return (
    <form
      className="flex flex-col gap-14"
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSubmit || pending) {
          return;
        }
        const input: EntryInput = { detail: detail.trim() };
        if (withHeadline) {
          input.headline = headline.trim();
        }
        onSubmit(input);
      }}
    >
      {withHeadline && (
        <Field label="Headline">
          <TextInput
            value={headline}
            maxLength={120}
            onChange={(event) => {
              setHeadline(event.target.value);
            }}
            required
          />
        </Field>
      )}
      <Field label="Detail">
        <TextArea
          value={detail}
          rows={3}
          onChange={(event) => {
            setDetail(event.target.value);
          }}
          required
        />
      </Field>
      <div className="flex gap-10">
        <PillButton type="submit" size="sm" disabled={pending || !canSubmit}>
          {pending ? "Saving…" : submitLabel}
        </PillButton>
        {onCancel !== undefined && (
          <PillButton type="button" size="sm" onClick={onCancel} disabled={pending}>
            Cancel
          </PillButton>
        )}
      </div>
    </form>
  );
}
