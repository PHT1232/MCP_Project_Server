import { useEffect, useState, type ReactNode, type SyntheticEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { updateAiSettings } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type {
  AiSettingSource,
  EmbeddingSettings,
  EmbeddingSettingsInput,
  SummarySettings,
  SummarySettingsInput,
} from "../api/types";
import { Callout } from "../components/Callout";
import { Card } from "../components/Card";
import { Field, Select, TextInput } from "../components/fields";
import { PillButton } from "../components/PillButton";
import { StatusBadge } from "../components/StatusBadge";
import { SectionTitle } from "../components/Typography";
import { useAiSettings } from "../hooks/useAiSettings";
import { useReindex } from "../hooks/useIndexStatus";
import { useProjects } from "../hooks/useProjects";

interface SaveState {
  error: string | null;
  saved: boolean;
}

const EMPTY_SAVE_STATE: SaveState = { error: null, saved: false };

function embeddingInput(settings: EmbeddingSettings): EmbeddingSettingsInput {
  return {
    backend: settings.backend,
    base_url: settings.base_url,
    model: settings.model,
    dimensions: settings.dimensions,
    batch_size: settings.batch_size,
    timeout_seconds: settings.timeout_seconds,
  };
}

function summaryInput(settings: SummarySettings): SummarySettingsInput {
  return {
    backend: settings.backend,
    base_url: settings.base_url,
    model: settings.model,
    timeout_seconds: settings.timeout_seconds,
  };
}

function sourceLabel(source: AiSettingSource): string {
  switch (source) {
    case "persisted":
      return "Saved override";
    case "environment":
      return "Environment";
    case "default":
      return "Default";
  }
}

function safeError(error: unknown, secrets: readonly string[]): string {
  const fallback = "Settings could not be saved. Check the values and try again.";
  if (!(error instanceof Error) || error.message === "") {
    return fallback;
  }
  if (secrets.some((secret) => secret !== "" && error.message.includes(secret))) {
    return fallback;
  }
  return error.message;
}

function ProviderStatus({
  configured,
  source,
}: {
  configured: boolean;
  source: AiSettingSource;
}): ReactNode {
  return (
    <div className="flex flex-wrap items-center gap-10">
      <StatusBadge tone={configured ? "growth" : "graphite"}>
        {configured ? "API key configured" : "No API key"}
      </StatusBadge>
      <span className="text-caption uppercase text-fey-graphite">
        Source: {sourceLabel(source)}
      </span>
    </div>
  );
}

function SecretFields({
  configured,
  apiKey,
  adminToken,
  clear,
  onApiKey,
  onAdminToken,
  onClear,
}: {
  configured: boolean;
  apiKey: string;
  adminToken: string;
  clear: boolean;
  onApiKey: (value: string) => void;
  onAdminToken: (value: string) => void;
  onClear: () => void;
}): ReactNode {
  return (
    <div className="grid gap-14 md:grid-cols-2">
      <div className="flex flex-col gap-8">
        <Field
          label="API key"
          hint={configured ? "Blank keeps the configured key." : "Blank leaves the key unset."}
        >
          <TextInput
            type="password"
            autoComplete="new-password"
            value={apiKey}
            placeholder={configured ? "Configured" : "Not configured"}
            onChange={(event) => { onApiKey(event.currentTarget.value); }}
          />
        </Field>
        <div className="flex flex-wrap items-center gap-10">
          <PillButton size="sm" onClick={onClear} disabled={!configured && !clear}>
            Clear saved key
          </PillButton>
          {clear && (
            <span className="text-caption uppercase text-fey-ember">
              Key will be cleared on save
            </span>
          )}
        </div>
      </div>
      <Field label="Admin token" hint="Held in this form only and cleared on submit.">
        <TextInput
          type="password"
          autoComplete="off"
          value={adminToken}
          onChange={(event) => { onAdminToken(event.currentTarget.value); }}
        />
      </Field>
    </div>
  );
}

function SaveFeedback({ state }: { state: SaveState }): ReactNode {
  if (state.error !== null) {
    return <Callout tone="alert">{state.error}</Callout>;
  }
  if (state.saved) {
    return <Callout>Settings saved.</Callout>;
  }
  return null;
}

function EmbeddingForm({ settings }: { settings: EmbeddingSettings }): ReactNode {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const [form, setForm] = useState<EmbeddingSettingsInput>(() => embeddingInput(settings));
  const [apiKey, setApiKey] = useState("");
  const [adminToken, setAdminToken] = useState("");
  const [clearSecret, setClearSecret] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>(EMPTY_SAVE_STATE);

  useEffect(() => { setForm(embeddingInput(settings)); }, [settings]);

  async function submit(event: SyntheticEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const submittedApiKey = apiKey;
    const submittedAdminToken = adminToken;
    const payload: EmbeddingSettingsInput = {
      ...form,
      ...(clearSecret
        ? { api_key: null }
        : submittedApiKey !== ""
          ? { api_key: submittedApiKey }
          : {}),
    };
    setApiKey("");
    setAdminToken("");
    setSaveState(EMPTY_SAVE_STATE);
    setPending(true);
    try {
      const updated = await updateAiSettings({ embedding: payload }, submittedAdminToken);
      queryClient.setQueryData(queryKeys.aiSettings, updated);
      setClearSecret(false);
      setSaveState({ error: null, saved: true });
    } catch (error: unknown) {
      setSaveState({
        error: safeError(error, [submittedApiKey, submittedAdminToken]),
        saved: false,
      });
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <form className="flex flex-col gap-16" onSubmit={(event) => void submit(event)}>
        <div className="flex flex-col gap-8">
          <SectionTitle>Embedding provider</SectionTitle>
          <ProviderStatus configured={settings.api_key_configured} source={settings.source} />
        </div>
        <div className="grid gap-14 md:grid-cols-2">
          <Field label="Backend"><TextInput required value={form.backend} onChange={(event) => { setForm({ ...form, backend: event.currentTarget.value }); }} /></Field>
          <Field label="Base URL"><TextInput required type="url" value={form.base_url} onChange={(event) => { setForm({ ...form, base_url: event.currentTarget.value }); }} /></Field>
          <Field label="Model"><TextInput required value={form.model} onChange={(event) => { setForm({ ...form, model: event.currentTarget.value }); }} /></Field>
          <Field label="Dimensions"><TextInput required type="number" min="1" value={form.dimensions} onChange={(event) => { setForm({ ...form, dimensions: event.currentTarget.valueAsNumber }); }} /></Field>
          <Field label="Batch size"><TextInput required type="number" min="1" value={form.batch_size} onChange={(event) => { setForm({ ...form, batch_size: event.currentTarget.valueAsNumber }); }} /></Field>
          <Field label="Timeout seconds"><TextInput required type="number" min="1" value={form.timeout_seconds} onChange={(event) => { setForm({ ...form, timeout_seconds: event.currentTarget.valueAsNumber }); }} /></Field>
        </div>
        <SecretFields configured={settings.api_key_configured} apiKey={apiKey} adminToken={adminToken} clear={clearSecret} onApiKey={(value) => { setApiKey(value); setClearSecret(false); }} onAdminToken={setAdminToken} onClear={() => { setApiKey(""); setClearSecret(true); }} />
        <SaveFeedback state={saveState} />
        <div><PillButton type="submit" disabled={pending}>{pending ? "Saving…" : "Save embedding settings"}</PillButton></div>
      </form>
    </Card>
  );
}

function SummaryForm({ settings }: { settings: SummarySettings }): ReactNode {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const [form, setForm] = useState<SummarySettingsInput>(() => summaryInput(settings));
  const [apiKey, setApiKey] = useState("");
  const [adminToken, setAdminToken] = useState("");
  const [clearSecret, setClearSecret] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>(EMPTY_SAVE_STATE);

  useEffect(() => { setForm(summaryInput(settings)); }, [settings]);

  async function submit(event: SyntheticEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const submittedApiKey = apiKey;
    const submittedAdminToken = adminToken;
    const payload: SummarySettingsInput = {
      ...form,
      ...(clearSecret
        ? { api_key: null }
        : submittedApiKey !== ""
          ? { api_key: submittedApiKey }
          : {}),
    };
    setApiKey("");
    setAdminToken("");
    setSaveState(EMPTY_SAVE_STATE);
    setPending(true);
    try {
      const updated = await updateAiSettings({ summary: payload }, submittedAdminToken);
      queryClient.setQueryData(queryKeys.aiSettings, updated);
      setClearSecret(false);
      setSaveState({ error: null, saved: true });
    } catch (error: unknown) {
      setSaveState({
        error: safeError(error, [submittedApiKey, submittedAdminToken]),
        saved: false,
      });
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <form className="flex flex-col gap-16" onSubmit={(event) => void submit(event)}>
        <div className="flex flex-col gap-8">
          <SectionTitle>Summary provider</SectionTitle>
          <ProviderStatus configured={settings.api_key_configured} source={settings.source} />
        </div>
        <div className="grid gap-14 md:grid-cols-2">
          <Field label="Backend"><TextInput required value={form.backend} onChange={(event) => { setForm({ ...form, backend: event.currentTarget.value }); }} /></Field>
          <Field label="Base URL"><TextInput required type="url" value={form.base_url} onChange={(event) => { setForm({ ...form, base_url: event.currentTarget.value }); }} /></Field>
          <Field label="Model"><TextInput required value={form.model} onChange={(event) => { setForm({ ...form, model: event.currentTarget.value }); }} /></Field>
          <Field label="Timeout seconds"><TextInput required type="number" min="1" value={form.timeout_seconds} onChange={(event) => { setForm({ ...form, timeout_seconds: event.currentTarget.valueAsNumber }); }} /></Field>
        </div>
        <SecretFields configured={settings.api_key_configured} apiKey={apiKey} adminToken={adminToken} clear={clearSecret} onApiKey={(value) => { setApiKey(value); setClearSecret(false); }} onAdminToken={setAdminToken} onClear={() => { setApiKey(""); setClearSecret(true); }} />
        <SaveFeedback state={saveState} />
        <div><PillButton type="submit" disabled={pending}>{pending ? "Saving…" : "Save summary settings"}</PillButton></div>
      </form>
    </Card>
  );
}

function ReindexControl(): ReactNode {
  const projects = useProjects();
  const [project, setProject] = useState("");
  const reindex = useReindex(project);

  return (
    <Callout tone="alert" title="Reindex required">
      <div className="flex flex-wrap items-end justify-between gap-14">
        <Field label="Project" hint="Run a full reindex for each affected project.">
          <Select value={project} onChange={(event) => { setProject(event.currentTarget.value); }}>
            <option value="">Select a project…</option>
            {(projects.data ?? []).map((item) => <option key={item.id} value={item.name}>{item.name}</option>)}
          </Select>
        </Field>
        <PillButton size="sm" disabled={project === "" || reindex.isPending} onClick={() => { reindex.mutate({ incremental: false }); }}>
          {reindex.isPending ? "Reindexing…" : "Run full reindex"}
        </PillButton>
      </div>
      {reindex.isError && <p>Reindex failed. Open the selected project's Index view for details or retry.</p>}
    </Callout>
  );
}

/** T20 / AC-AISET-8..10 — global provider settings independent of project selection. */
export function AiSettingsView(): ReactNode {
  const query = useAiSettings();

  if (query.isPending) {
    return <Card><p className="text-body text-fey-graphite">Loading AI settings…</p></Card>;
  }
  if (query.isError) {
    return <Callout tone="alert">AI settings could not be loaded.</Callout>;
  }

  return (
    <div className="flex flex-col gap-24">
      <div className="flex flex-col gap-8">
        <SectionTitle>Global AI settings</SectionTitle>
        <p className="text-body text-fey-graphite">These providers apply to every project.</p>
      </div>
      {query.data.reindex_required && <ReindexControl />}
      <EmbeddingForm settings={query.data.embedding} />
      <SummaryForm settings={query.data.summary} />
    </div>
  );
}
