import { useState, type ReactNode } from "react";

import type { RegisterProjectInput } from "../api/types";
import { Callout } from "./Callout";
import { PillButton } from "./PillButton";
import { Field, TextArea, TextInput } from "./fields";

interface RegisterFormProps {
  onSubmit: (input: RegisterProjectInput) => void;
  pending: boolean;
  error: string | null;
}

export function RegisterForm({
  onSubmit,
  pending,
  error,
}: RegisterFormProps): ReactNode {
  const [name, setName] = useState("");
  const [rootPath, setRootPath] = useState("");
  const [overview, setOverview] = useState("");

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({ name, root_path: rootPath, overview });
      }}
      className="flex flex-col gap-16"
    >
      <Field label="Name">
        <TextInput
          value={name}
          onChange={(event) => {
            setName(event.target.value);
          }}
          required
        />
      </Field>
      <Field label="Root path">
        <TextInput
          value={rootPath}
          onChange={(event) => {
            setRootPath(event.target.value);
          }}
          placeholder="/repos/my-project"
          required
        />
      </Field>
      <Field label="Overview">
        <TextArea
          value={overview}
          rows={3}
          onChange={(event) => {
            setOverview(event.target.value);
          }}
          required
        />
      </Field>
      {error !== null && <Callout tone="alert">{error}</Callout>}
      <div>
        <PillButton type="submit" disabled={pending}>
          {pending ? "Registering…" : "Register project"}
        </PillButton>
      </div>
    </form>
  );
}
