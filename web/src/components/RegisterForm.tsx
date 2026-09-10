import { useState, type ReactNode } from "react";

import type { RegisterProjectInput } from "../api/types";
import { PillButton } from "./PillButton";

interface RegisterFormProps {
  onSubmit: (input: RegisterProjectInput) => void;
  pending: boolean;
  error: string | null;
}

const FIELD_CLASS =
  "rounded-small border border-fey-smoke bg-fey-obsidian px-14 py-10 text-body text-fey-white outline-none focus:border-fey-mist";

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
      <label className="flex flex-col gap-6 text-caption uppercase text-fey-graphite">
        Name
        <input
          className={FIELD_CLASS}
          value={name}
          onChange={(event) => {
            setName(event.target.value);
          }}
          required
        />
      </label>
      <label className="flex flex-col gap-6 text-caption uppercase text-fey-graphite">
        Root path
        <input
          className={FIELD_CLASS}
          value={rootPath}
          onChange={(event) => {
            setRootPath(event.target.value);
          }}
          placeholder="/repos/my-project"
          required
        />
      </label>
      <label className="flex flex-col gap-6 text-caption uppercase text-fey-graphite">
        Overview
        <textarea
          className={FIELD_CLASS}
          value={overview}
          rows={3}
          onChange={(event) => {
            setOverview(event.target.value);
          }}
          required
        />
      </label>
      {error !== null && (
        <p className="text-body text-fey-ember">{error}</p>
      )}
      <div>
        <PillButton type="submit" disabled={pending}>
          {pending ? "Registering…" : "Register project"}
        </PillButton>
      </div>
    </form>
  );
}
