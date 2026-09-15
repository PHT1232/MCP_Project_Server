import { useCallback, useMemo, useState, useEffect, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ErrorBoundary } from '@/components/error-boundary';
import { Toaster } from '@/components/ui/toaster';
import { TooltipProvider } from '@/components/ui/tooltip';
import { toast } from '@/hooks/use-toast';
import {
  Activity, AlertCircle, ArrowRight, Boxes, Check, CheckCircle2, ChevronDown, ChevronRight,
  Circle, CircleDot, Code2, Copy, Database, FileCode2, FileText, Folder, GitBranch,
  Layers3, LayoutDashboard, ListChecks, Loader2, Menu, Plus, RefreshCw, Search, Settings2,
  Sparkles, Terminal, Trash2, Workflow, X, Zap,
} from 'lucide-react';
import { Link, Route, Switch, useLocation, useParams, Router as WouterRouter } from 'wouter';

import {
  useListProjects, useRegisterProject,
  useGetBriefing, useGetSection, useSetFocus, useAddEntry, useResolveEntry,
  useListRequirements, useReviewRequirementCompliance, useSyncRequirements, useUpdateEntry,
  useGetIndexStatus, useReindex,
  useGetCodeMap, useGetSource, useSearchCode,
  useGetAiSettings, useUpdateAiSettings, getGetAiSettingsQueryKey,
  setAdminTokenGetter,
  type AiSettings, type EmbeddingSettings, type SummarySettings,
  type CodeMap as CodeMapResponse, type Entry, type SyncReport,
} from '@workspace/api-client-react';
import { emptyGraph, mergeCodeMap, overlayTone, locateHit, relatedEntries, type CodeGraph, type MergedNode } from './lib/codemap';
import Plans from './pages/Plans';

export const queryClient = new QueryClient();

// Single shared admin token, entered once on the AI Settings page and kept in
// this browser's localStorage. customFetch calls this getter on every
// request, so updating the field below takes effect immediately.
const ADMIN_TOKEN_STORAGE_KEY = 'pcs-admin-token';

function readAdminToken(): string | null {
  try {
    return localStorage.getItem(ADMIN_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

setAdminTokenGetter(readAdminToken);

// Every mutation in this app should route failures through here instead of
// failing silently — react-query's onError is easy to forget one at a time.
export function notifyError(action: string, err: unknown) {
  toast({
    variant: 'destructive',
    title: `${action} failed`,
    description: err instanceof Error ? err.message : 'Something went wrong. Please try again.',
  });
}

export function notify(title: string, description?: string) {
  toast({ title, description });
}

export type Tone = 'blue' | 'amber' | 'mint' | 'red' | 'ink';

export const toneStyles: Record<Tone, string> = {
  blue: 'bg-[#e5e9ff] text-[#3047a8] border-[#c8d0ff]',
  amber: 'bg-[#f8edcf] text-[#856115] border-[#e8d397]',
  mint: 'bg-[#dcefe7] text-[#246a5a] border-[#b9dfd1]',
  red: 'bg-[#f7e1dd] text-[#97433d] border-[#e9c1bc]',
  ink: 'bg-[#e3e7e8] text-[#33454b] border-[#cbd4d5]',
};

export function cx(...values: Array<string | false | null | undefined>) { return values.filter(Boolean).join(' '); }

export function Button({ children, onClick, variant = 'primary', size = 'md', className, type = 'button', disabled = false, testId }: {
  children: ReactNode; onClick?: () => void; variant?: 'primary' | 'secondary' | 'quiet' | 'danger'; size?: 'sm' | 'md'; className?: string; type?: 'button' | 'submit'; disabled?: boolean; testId: string;
}) {
  const variants = {
    primary: 'bg-[#3155d8] text-[#f8f7f0] border-[#3155d8] hover:bg-[#2948be]',
    secondary: 'bg-[#f8f7f0] text-[#24343a] border-[#c9d0cf] hover:bg-[#edf0ea]',
    quiet: 'bg-transparent text-[#52636a] border-transparent hover:bg-[#e7ebe8]',
    danger: 'bg-[#f7e1dd] text-[#97433d] border-[#e9c1bc] hover:bg-[#f1d3ce]',
  };
  return <button data-testid={testId} type={type} onClick={onClick} disabled={disabled} className={cx('inline-flex items-center justify-center gap-2 rounded-md border font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50', variants[variant], size === 'sm' ? 'h-8 px-2.5 text-xs' : 'h-9 px-3.5 text-sm', className)}>{children}</button>;
}

export function Badge({ children, tone = 'ink', dot = false, testId }: { children: ReactNode; tone?: Tone; dot?: boolean; testId?: string }) {
  return <span data-testid={testId} className={cx('inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-semibold tracking-wide', toneStyles[tone])}>{dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}{children}</span>;
}

export function Stat({ label, value, sub, accent = 'blue', icon: Icon }: { label: string; value: string; sub?: string; accent?: Tone; icon?: typeof Activity }) {
  return <div data-testid={`stat-${label.toLowerCase().replace(/\s+/g, '-')}`} className="rounded-lg border border-[#d9dcd5] bg-[#faf9f4] p-4 shadow-[0_1px_0_rgba(31,43,45,.04)]">
    <div className="flex items-start justify-between"><p className="text-[11px] font-semibold uppercase tracking-[.12em] text-[#758188]">{label}</p>{Icon && <span className={cx('rounded p-1.5', toneStyles[accent])}><Icon size={14} /></span>}</div>
    <div className="mt-2 flex items-baseline gap-2"><strong className="font-mono text-2xl font-medium tracking-tight text-[#1e3036]">{value}</strong>{sub && <span className="text-xs text-[#78868b]">{sub}</span>}</div>
  </div>;
}

// A failed read query otherwise just renders as an empty/loading panel forever
// — this makes "it's broken" visibly different from "it's loading" or "it's empty".
type QueryLike = { isError: boolean; error: unknown; refetch: () => void };

export function combineQueryErrors(...queries: QueryLike[]): { isError: boolean; message: string; retry: () => void } {
  const failed = queries.filter((q) => q.isError);
  const messages = [...new Set(failed.map((q) => (q.error instanceof Error ? q.error.message : 'Request failed.')))];
  return {
    isError: failed.length > 0,
    message: messages.join(' '),
    retry: () => failed.forEach((q) => q.refetch()),
  };
}

export function ErrorBanner({ message, onRetry, testId = 'banner-load-error' }: { message: string; onRetry: () => void; testId?: string }) {
  return <div data-testid={testId} className="mb-5 flex items-center gap-3 rounded-md border border-[#e9c1bc] bg-[#f7e1dd] px-4 py-3 text-sm text-[#97433d]">
    <AlertCircle size={17} className="shrink-0" />
    <span className="flex-1">{message}</span>
    <Button testId={`${testId}-retry`} size="sm" variant="secondary" onClick={onRetry}><RefreshCw size={14} />Retry</Button>
  </div>;
}

function AppShell({ children }: { children: ReactNode }) {
  const [location, setLocation] = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const { data: projects, isLoading, isError, error, refetch } = useListProjects();

  const currentProjectName = decodeURIComponent(location.split('/projects/')[1]?.split('/')[0] ?? '');
  const currentProject = projects?.find((project) => project.name === currentProjectName) ?? projects?.[0];

  if (isLoading) {
    return <div className="p-8 text-center"><Loader2 className="animate-spin mx-auto text-[#3155d8]" /></div>;
  }
  if (isError) {
    return <div className="flex min-h-[100dvh] items-center justify-center bg-[#f1efe8] p-6"><div className="max-w-sm text-center">
      <AlertCircle className="mx-auto text-[#97433d]" size={28} />
      <p className="mt-3 font-semibold">Couldn't load projects</p>
      <p className="mt-1 text-sm text-[#7b888c]">{error instanceof Error ? error.message : 'Request failed.'}</p>
      <Button testId="button-retry-projects" className="mt-4" onClick={() => refetch()}><RefreshCw size={14} />Retry</Button>
    </div></div>;
  }
  if (!projects || projects.length === 0) {
    return <div className="flex min-h-[100dvh] items-center justify-center bg-[#f1efe8] p-6"><div className="max-w-sm text-center">
      <Folder className="mx-auto text-[#9eaaa5]" size={28} />
      <p className="mt-3 font-semibold">No projects registered</p>
      <Link href="/" data-testid="link-appshell-back-home" className="mt-4 inline-flex text-sm font-semibold text-[#3155d8]">Back to project list</Link>
    </div></div>;
  }
  if (!currentProject) {
    return <div className="flex min-h-[100dvh] items-center justify-center bg-[#f1efe8] p-6"><div className="max-w-sm text-center">
      <AlertCircle className="mx-auto text-[#9eaaa5]" size={28} />
      <p className="mt-3 font-semibold">Project "{currentProjectName}" not found</p>
      <Link href="/" data-testid="link-appshell-back-home" className="mt-4 inline-flex text-sm font-semibold text-[#3155d8]">Back to project list</Link>
    </div></div>;
  }

  const projectRoot = `/projects/${encodeURIComponent(currentProject.name)}`;
  const nav = [
    { href: `${projectRoot}/dashboard`, label: 'Dashboard', icon: LayoutDashboard },
    { href: `${projectRoot}/requirements`, label: 'Requirements', icon: ListChecks },
    { href: `${projectRoot}/plans`, label: 'Plans', icon: Workflow },
    { href: `${projectRoot}/index`, label: 'Code index', icon: Database },
    { href: `${projectRoot}/code-map`, label: 'Code map', icon: Folder },
  ];
  return <div className="noise min-h-[100dvh] overflow-x-hidden bg-[#f1efe8] text-[#203238]">
    <aside className={cx('fixed inset-y-0 left-0 z-40 flex w-[248px] flex-col border-r border-[#26393f] bg-[#17292f] text-[#e9ede6] transition-transform md:translate-x-0', mobileOpen ? 'translate-x-0' : '-translate-x-full')}>
      <div className="flex h-[72px] items-center justify-between border-b border-[#34474d] px-5">
        <Link href="/" data-testid="link-pcs-home" className="flex items-center gap-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-[#d9ae45] text-[#17292f]"><Boxes size={18} strokeWidth={2.5} /></span>
          <span><span className="block text-[17px] font-bold tracking-[-.03em]">PCS</span><span className="block font-mono text-[9px] uppercase tracking-[.17em] text-[#aebdb7]">project memory</span></span>
        </Link>
        <button data-testid="button-close-mobile-nav" className="rounded p-1 text-[#b8c4be] md:hidden" onClick={() => setMobileOpen(false)}><X size={18} /></button>
      </div>
      <div className="border-b border-[#34474d] p-4">
        <label className="mb-2 block text-[10px] font-semibold uppercase tracking-[.16em] text-[#8ea19b]">Active project</label>
        <div className="relative">
          <select data-testid="select-project-switcher" value={currentProject.name} onChange={(event) => setLocation(`/projects/${encodeURIComponent(event.target.value)}/dashboard`)} className="w-full appearance-none rounded-md border border-[#435960] bg-[#22373d] px-3 py-2.5 pr-8 text-sm font-medium text-[#edf1e9] outline-none focus:border-[#d9ae45]">
            {projects.map((project) => <option key={project.name} value={project.name}>{project.name}</option>)}
          </select><ChevronDown className="pointer-events-none absolute right-2.5 top-3 text-[#9aaba6]" size={15} />
        </div>
        <div className="mt-2 flex items-center gap-2 px-1 text-[11px] text-[#99aaa5]"><span className="h-1.5 w-1.5 rounded-full bg-[#77c6a5]" />{currentProject.name}</div>
      </div>
      <nav className="flex-1 space-y-1 p-3">
        <p className="px-3 pb-2 pt-2 text-[10px] font-semibold uppercase tracking-[.16em] text-[#71847e]">Workspace</p>
        {nav.map(({ href, label, icon: Icon }) => <Link key={href} href={href} onClick={() => setMobileOpen(false)} data-testid={`link-nav-${label.toLowerCase().replace(' ', '-')}`} className={cx('group flex items-center gap-3 rounded-md border px-3 py-2.5 text-sm transition-colors', location === href ? 'border-[#415962] bg-[#284047] font-semibold text-[#f1f2e9]' : 'border-transparent text-[#afbeb8] hover:bg-[#20383e] hover:text-[#eef2eb]')}><Icon size={16} className={location === href ? 'text-[#d9ae45]' : 'text-[#80938d]'} /><span>{label}</span></Link>)}
        <p className="px-3 pb-2 pt-7 text-[10px] font-semibold uppercase tracking-[.16em] text-[#71847e]">System</p>
        <Link href="/settings/ai" onClick={() => setMobileOpen(false)} data-testid="link-ai-settings" className={cx('flex items-center gap-3 rounded-md border px-3 py-2.5 text-sm transition-colors', location === '/settings/ai' ? 'border-[#415962] bg-[#284047] font-semibold text-[#f1f2e9]' : 'border-transparent text-[#afbeb8] hover:bg-[#20383e] hover:text-[#eef2eb]')}><Sparkles size={16} className="text-[#d9ae45]" />AI providers</Link>
      </nav>
      <div className="border-t border-[#34474d] p-4">
        <div className="flex items-center gap-2 text-[11px] text-[#9bada6]"><span className="h-2 w-2 rounded-full bg-[#77c6a5]" />Local workspace online</div>
        <div className="mt-2 font-mono text-[10px] text-[#687d77]">PCS v0.8.4 · MCP ready</div>
      </div>
    </aside>
    <div className="md:pl-[248px]">
      <header className="sticky top-0 z-30 flex h-[72px] items-center justify-between border-b border-[#d9dcd5] bg-[#f1efe8]/95 px-4 backdrop-blur md:px-8">
        <div className="flex items-center gap-3"><button data-testid="button-open-mobile-nav" className="rounded-md border border-[#d0d5d0] bg-[#faf9f4] p-2 md:hidden" onClick={() => setMobileOpen(true)}><Menu size={18} /></button><div className="hidden md:block"><p className="text-[10px] font-semibold uppercase tracking-[.16em] text-[#87938e]">Operator console</p><p className="font-mono text-xs text-[#53646a]">{currentProject.root_path}</p></div><div className="md:hidden"><p className="font-bold tracking-tight">PCS <span className="font-normal text-[#748087]">/ {currentProject.name}</span></p></div></div>
        <div className="flex items-center gap-2.5"><Button testId="button-refresh-workspace" variant="secondary" size="sm" onClick={() => queryClient.invalidateQueries()}><RefreshCw size={14} />Refresh</Button><Link href="/settings/ai" data-testid="link-header-settings" className="rounded-md border border-[#d0d5d0] bg-[#faf9f4] p-2 text-[#54646a] hover:text-[#3155d8]"><Settings2 size={16} /></Link></div>
      </header>
      <main className="mx-auto max-w-[1440px] px-4 py-6 md:px-8 md:py-8">{children}</main>
    </div>
  </div>;
}

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description?: string; actions?: ReactNode }) {
  return <div className="mb-6 flex flex-col justify-between gap-4 border-b border-[#d9dcd5] pb-6 lg:flex-row lg:items-end"><div><div className="mb-2 flex items-center gap-2 font-mono text-[10px] font-medium uppercase tracking-[.17em] text-[#3155d8]"><span className="h-1.5 w-1.5 rounded-full bg-[#3155d8]" />{eyebrow}</div><h1 className="text-3xl font-bold tracking-[-.045em] text-[#1d3036] md:text-[38px]">{title}</h1>{description && <p className="mt-2 max-w-2xl text-sm leading-6 text-[#69777c]">{description}</p>}</div>{actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}</div>;
}

export function ProjectTabs({ active }: { active: string }) {
  const project = decodeURIComponent(useParams<{ project: string }>().project ?? '');
  const tabs = [['dashboard', 'Overview'], ['requirements', 'Requirements'], ['plans', 'Plans'], ['index', 'Code index'], ['code-map', 'Code map']];
  return <div className="mb-6 flex gap-1 overflow-x-auto rounded-lg border border-[#d7dbd4] bg-[#e7e9e2] p-1">{tabs.map(([id, label]) => <Link key={id} href={`/projects/${encodeURIComponent(project)}/${id}`} data-testid={`tab-project-${id}`} className={cx('whitespace-nowrap rounded-md px-3 py-2 text-xs font-semibold transition-colors md:px-4', active === id ? 'bg-[#faf9f4] text-[#1e3036] shadow-[0_1px_2px_rgba(31,43,45,.08)]' : 'text-[#758187] hover:text-[#34464c]')}>{label}</Link>)}</div>;
}

function HomePicker() {
  const [showForm, setShowForm] = useState(false);
  const { data: projectsState = [], isLoading: projectsLoading, isError: projectsErrored, error: projectsError, refetch: refetchProjects } = useListProjects();
  const registerMutation = useRegisterProject();
  const [name, setName] = useState('');
  const [path, setPath] = useState('');
  
  const loading = registerMutation.isPending;
  const register = () => {
    const trimmedName = name.trim();
    const trimmedPath = path.trim();
    if (!trimmedName || !trimmedPath) {
      notifyError('Register project', new Error('Name and local path are both required.'));
      return;
    }
    registerMutation.mutate(
      { data: { name: trimmedName, root_path: trimmedPath, overview: '' } },
      {
        onSuccess: () => {
          queryClient.invalidateQueries({ queryKey: ['/api/projects'] });
          notify('Project registered', `${trimmedName} is ready to use.`);
          setName('');
          setPath('');
          setShowForm(false);
        },
        onError: (err) => notifyError('Register project', err),
      }
    );
  };
  
  return <div className="min-h-[100dvh] overflow-x-hidden bg-[#f1efe8] text-[#203238] paper-grid"><div className="mx-auto max-w-[1240px] px-5 py-8 md:px-10 md:py-12">
    <header className="flex items-center justify-between"><Link href="/" data-testid="link-home-wordmark" className="flex items-center gap-3"><span className="flex h-9 w-9 items-center justify-center rounded-md bg-[#17292f] text-[#d9ae45]"><Boxes size={19} /></span><span><strong className="block text-[18px] tracking-[-.04em]">PCS</strong><span className="font-mono text-[9px] uppercase tracking-[.18em] text-[#748188]">project context server</span></span></Link><Link href="/settings/ai" data-testid="link-home-ai-settings" className="flex items-center gap-2 text-sm font-medium text-[#53646a] hover:text-[#3155d8]"><Sparkles size={16} />AI settings</Link></header>
    <section className="mt-20 max-w-3xl md:mt-28"><p className="font-mono text-[11px] uppercase tracking-[.18em] text-[#3155d8]">Your project memory, assembled</p><h1 className="mt-4 text-5xl font-bold leading-[.98] tracking-[-.06em] text-[#1d3036] md:text-7xl">Pick up where<br /><span className="text-[#3155d8]">the repo left off.</span></h1><p className="mt-6 max-w-xl text-base leading-7 text-[#66757b]">PCS keeps the state of your codebase legible between sessions — briefings, decisions, requirements, and the files that matter now.</p></section>
    <section className="mt-16 md:mt-20"><div className="mb-4 flex items-center justify-between"><div><h2 className="text-lg font-bold tracking-tight">Registered projects</h2><p className="mt-1 text-xs text-[#7b888c]">{projectsState.length} workspaces connected to this PCS instance</p></div><Button testId="button-toggle-register-project" variant="primary" onClick={() => setShowForm((value) => !value)}><Plus size={15} />Register project</Button></div>
      {projectsErrored && <ErrorBanner testId="banner-projects-error" message={projectsError instanceof Error ? projectsError.message : 'Failed to load registered projects.'} onRetry={() => refetchProjects()} />}
      {showForm && <div className="mb-5 grid gap-3 rounded-lg border border-[#cfd7d2] bg-[#faf9f4] p-4 shadow-sm md:grid-cols-[1fr_1.4fr_auto] md:items-end"><label className="text-xs font-semibold text-[#52636a]">Project name<input data-testid="input-register-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Northstar API" className="mt-1.5 h-10 w-full rounded-md border border-[#ccd4d1] bg-[#f1efe8] px-3 text-sm outline-none focus:border-[#3155d8]" /></label><label className="text-xs font-semibold text-[#52636a]">Local path<input data-testid="input-register-path" value={path} onChange={(event) => setPath(event.target.value)} placeholder="~/work/northstar-api" className="mt-1.5 h-10 w-full rounded-md border border-[#ccd4d1] bg-[#f1efe8] px-3 font-mono text-xs outline-none focus:border-[#3155d8]" /></label><Button testId="button-submit-register" onClick={register} disabled={loading}>{loading ? <Loader2 className="animate-spin" size={15} /> : <Check size={15} />} {loading ? 'Connecting…' : 'Connect'}</Button></div>}
      {projectsLoading ? <div className="py-16 text-center"><Loader2 className="animate-spin mx-auto text-[#3155d8]" /></div> : <div className="grid gap-4 lg:grid-cols-3">{projectsState.map((project, index) => <Link href={`/projects/${encodeURIComponent(project.name)}/dashboard`} key={project.name} data-testid={`card-project-${project.name}`} className="group relative overflow-hidden rounded-lg border border-[#d2d8d2] bg-[#faf9f4] p-5 shadow-[0_2px_0_rgba(31,43,45,.04)] transition-all hover:-translate-y-0.5 hover:border-[#9daeb3] hover:shadow-[0_8px_20px_rgba(31,43,45,.07)] animate-enter" style={{ animationDelay: `${index * 60}ms` }}><div className={cx('absolute right-0 top-0 h-20 w-20 translate-x-5 -translate-y-5 rounded-full opacity-50 bg-[#ccd5ff]')} /><div className="relative"><div className="flex items-start justify-between"><span className="flex h-9 w-9 items-center justify-center rounded-md bg-[#e7e9e2] text-[#3155d8]"><Folder size={18} /></span><Badge tone="mint" dot>Synced</Badge></div><h3 className="mt-7 text-xl font-bold tracking-[-.035em]">{project.name}</h3><p className="mt-1 truncate font-mono text-[11px] text-[#77858a]">{project.root_path}</p><div className="mt-7 flex items-center justify-between border-t border-[#e1e4dc] pt-3 text-xs text-[#78858a]"><span className="flex items-center gap-1.5"></span><span className="font-mono"></span></div><ArrowRight className="absolute bottom-0 right-0 text-[#adb8b5] transition-transform group-hover:translate-x-1 group-hover:text-[#3155d8]" size={18} /></div></Link>)}</div>}
      {!projectsLoading && !projectsErrored && projectsState.length === 0 && <div className="rounded-lg border border-dashed border-[#c7d0cb] bg-[#faf9f4] py-16 text-center"><Folder className="mx-auto text-[#9eaaa5]" size={28} /><p className="mt-3 font-semibold">No projects registered</p><p className="mt-1 text-sm text-[#7b888c]">Connect a local repository to start building context.</p></div>}
    </section>
    <footer className="mt-20 flex items-center gap-2 font-mono text-[10px] uppercase tracking-[.15em] text-[#96a19d]"><span className="h-1.5 w-1.5 rounded-full bg-[#77c6a5]" />local-first · private by default</footer>
  </div></div>;
}

type EntryType = 'Blocker' | 'Bug' | 'Convention' | 'Decision';
function EntrySection({ type, items, onAdd, onResolve }: { type: EntryType; items: Array<{ id: string; text: string; meta: string; resolved?: boolean }>; onAdd: (type: EntryType) => void; onResolve: (id: string) => void }) {
  const tone = type === 'Blocker' ? 'red' : type === 'Bug' ? 'amber' : type === 'Convention' ? 'mint' : 'blue';
  const Icon = type === 'Blocker' ? AlertCircle : type === 'Bug' ? Zap : type === 'Convention' ? CircleDot : GitBranch;
  return <section className="rounded-lg border border-[#d8dcd5] bg-[#faf9f4]"><div className="flex items-center justify-between border-b border-[#e4e6df] px-4 py-3"><div className="flex items-center gap-2.5"><span className={cx('rounded p-1.5', toneStyles[tone])}><Icon size={14} /></span><h3 className="text-sm font-bold">{type}s</h3><span className="font-mono text-[10px] text-[#889398]">{items.filter((item) => !item.resolved).length.toString().padStart(2, '0')}</span></div><Button testId={`button-add-${type.toLowerCase()}`} variant="quiet" size="sm" onClick={() => onAdd(type)}><Plus size={14} />Add</Button></div><div className="divide-y divide-[#e5e7e0]">{items.map((item) => <div key={item.id} className={cx('flex gap-3 px-4 py-3', item.resolved && 'opacity-50')}><span className={cx('mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full', item.resolved ? 'bg-[#77a68e]' : type === 'Blocker' ? 'bg-[#c65b51]' : 'bg-[#d9ae45')} /><div className="min-w-0 flex-1"><p className={cx('text-sm leading-5', item.resolved && 'line-through')}>{item.text}</p><p className="mt-1 font-mono text-[10px] text-[#89959a]">{item.meta}</p></div>{!item.resolved && <button data-testid={`button-resolve-${item.id}`} onClick={() => onResolve(item.id)} className="self-start rounded p-1 text-[#9aa6a6] hover:bg-[#dcefe7] hover:text-[#246a5a]" title="Resolve"><Check size={15} /></button>}</div>)}</div></section>;
}

function Dashboard() {
  const project = decodeURIComponent(useParams<{ project: string }>().project ?? '');

  const briefingQuery = useGetBriefing(project);
  const briefingData = briefingQuery.data;
  // 'focus' holds at most one open entry (server resolves the prior one on every
  // set_current_focus) — this is the real focus text, not briefingData.briefing,
  // which is the whole assembled multi-section document (FR5/FR6).
  const focusQuery = useGetSection(project, 'focus');
  const focusData = focusQuery.data;
  const blockersQuery = useGetSection(project, 'blockers', { include_resolved: true });
  const blockersData = blockersQuery.data ?? { entries: [] };
  const bugsQuery = useGetSection(project, 'bugs', { include_resolved: true });
  const bugsData = bugsQuery.data ?? { entries: [] };
  const conventionsQuery = useGetSection(project, 'conventions', { include_resolved: true });
  const conventionsData = conventionsQuery.data ?? { entries: [] };
  const decisionsQuery = useGetSection(project, 'decisions', { include_resolved: true });
  const decisionsData = decisionsQuery.data ?? { entries: [] };
  const loadError = combineQueryErrors(briefingQuery, focusQuery, blockersQuery, bugsQuery, conventionsQuery, decisionsQuery);

  const addEntryMutation = useAddEntry();
  const resolveEntryMutation = useResolveEntry();
  const setFocusMutation = useSetFocus();

  const entries = useMemo(() => {
    const mapEntry = (e: any) => ({
      id: e.id,
      text: e.headline,
      meta: e.status === 'resolved' ? `resolved · ${e.author}` : `opened ${new Date(e.created_at).toLocaleDateString()} · ${e.author}`,
      resolved: e.status === 'resolved'
    });
    return {
      Blocker: blockersData.entries.map(mapEntry),
      Bug: bugsData.entries.map(mapEntry),
      Convention: conventionsData.entries.map(mapEntry),
      Decision: decisionsData.entries.map(mapEntry),
    };
  }, [blockersData, bugsData, conventionsData, decisionsData]);

  const [editing, setEditing] = useState(false);
  const [draftFocus, setDraftFocus] = useState('');
  const focusEntry = focusData?.entries[0];
  const focus = focusEntry?.detail || focusEntry?.headline || '';

  const add = (type: EntryType) => {
    const section = type.toLowerCase() + 's';
    addEntryMutation.mutate({ project, data: { section, headline: `New ${type.toLowerCase()} — add context here`, detail: '' } }, {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: [`/api/projects/${project}/sections/${section}`] }),
      onError: (err) => notifyError(`Add ${type.toLowerCase()}`, err),
    });
  };

  const resolve = (id: string) => {
    resolveEntryMutation.mutate({ project, entryId: id }, {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: [`/api/projects/${project}/sections`] }),
      onError: (err) => notifyError('Resolve entry', err),
    });
  };

  const saveFocus = () => {
    setFocusMutation.mutate({ project, data: { text: draftFocus } }, {
      onSuccess: () => {
        setEditing(false);
        queryClient.invalidateQueries({ queryKey: [`/api/projects/${project}/sections/focus`] });
        queryClient.invalidateQueries({ queryKey: [`/api/projects/${project}/briefing`] });
      },
      onError: (err) => notifyError('Save focus', err),
    });
  };

  const startEditing = () => {
    setDraftFocus(focus);
    setEditing(true);
  };

  const copyBriefing = async () => {
    const text = briefingData?.briefing ?? '';
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      notify('Copied', 'Briefing copied to clipboard.');
    } catch (err) {
      notifyError('Copy briefing', err);
    }
  };

  return <><PageHeader eyebrow="atlas-console / overview" title="Project briefing" description="The short version of what an engineer or coding agent needs before touching this repository." actions={<><Badge tone="mint" dot testId="status-project-sync">Context synced</Badge><Button testId="button-copy-briefing" variant="secondary" size="sm" onClick={copyBriefing} disabled={!briefingData?.briefing}><Copy size={14} />Copy briefing</Button></>} /><ProjectTabs active="dashboard" />
    {loadError.isError && <ErrorBanner testId="banner-dashboard-error" message={loadError.message} onRetry={loadError.retry} />}
    <div className="grid min-w-0 gap-5 xl:grid-cols-[1.25fr_.75fr]"><div className="min-w-0 space-y-5">
      <section className="w-full min-w-0 overflow-hidden rounded-lg border border-[#d1d7d2] bg-[#17292f] p-5 text-[#eff1e9] shadow-[0_4px_0_rgba(23,41,47,.08)]"><div className="flex items-start justify-between gap-5"><div className="min-w-0 flex-1"><p className="font-mono text-[10px] uppercase tracking-[.16em] text-[#d9ae45]">Current focus</p>{editing ? <textarea data-testid="textarea-focus" autoFocus value={draftFocus} onChange={(event) => setDraftFocus(event.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && e.metaKey) saveFocus(); }} className="mt-3 min-h-[84px] w-full resize-y rounded-md border border-[#52666b] bg-[#223a40] p-3 text-lg leading-7 text-[#f0f2e9] outline-none focus:border-[#d9ae45]" /> : <p data-testid="text-current-focus" className="mt-3 max-w-2xl break-words text-lg font-medium leading-8 tracking-[-.02em] md:text-xl">{focus || 'No focus set yet.'}</p>}</div><button data-testid="button-edit-focus" onClick={editing ? saveFocus : startEditing} className="shrink-0 rounded-md border border-[#52666b] px-2.5 py-1.5 text-xs text-[#b9c7c0] hover:border-[#d9ae45] hover:text-[#f1d27f]">{editing ? (setFocusMutation.isPending ? 'Saving...' : 'Save') : 'Edit'}</button></div><div className="mt-7 flex items-center gap-3 border-t border-[#31484e] pt-3 font-mono text-[10px] text-[#9aaca6]"><Activity size={13} className="text-[#77c6a5]" />{focusEntry ? `Focus set ${new Date(focusEntry.updated_at).toLocaleString()}` : 'No focus recorded yet'} <span className="text-[#556d71]">•</span> {blockersData.entries.length + bugsData.entries.length} active threads</div></section>
      <div className="grid gap-4 md:grid-cols-2">{(Object.keys(entries) as EntryType[]).map((type) => <EntrySection key={type} type={type} items={entries[type]} onAdd={add} onResolve={resolve} />)}</div>
    </div><aside className="space-y-5"><section className="rounded-lg border border-[#d8dcd5] bg-[#faf9f4] p-5"><div className="flex items-center justify-between"><div><p className="font-mono text-[10px] uppercase tracking-[.16em] text-[#7d898d]">Assembled briefing</p><h2 className="mt-1 text-base font-bold">What the agent sees</h2></div><Badge tone="blue">brief.md</Badge></div><pre data-testid="text-briefing-preview" className="mt-4 overflow-auto rounded-md border border-[#e0e2da] bg-[#eef0ea] p-4 font-mono text-[11px] leading-6 text-[#52636a] whitespace-pre-wrap">{briefingData?.briefing || 'Briefing not generated yet.'}</pre><div className="mt-3 flex items-center gap-2 text-[11px] text-[#7e8b8f]"><CheckCircle2 size={14} className="text-[#438b70]" />Verbatim from get_project_briefing</div></section><section className="rounded-lg border border-[#d8dcd5] bg-[#e5e9ff] p-5"><div className="flex items-center gap-2 text-[#3047a8]"><Sparkles size={16} /><h2 className="text-sm font-bold">Open threads</h2></div><p className="mt-2 text-sm leading-6 text-[#4b5b96]">{blockersData.entries.filter((e) => e.status !== 'resolved').length} open blocker(s), {bugsData.entries.filter((e) => e.status !== 'resolved').length} open bug(s).</p></section></aside></div>
  </>;
}

import { useGetRequirementContract, type RequirementComplianceRow } from '@workspace/api-client-react';

const COMPLIANCE_TONE: Record<string, Tone> = { verified: 'mint', failed: 'red', 'not-configured': 'ink' };

function RequirementRow({ req, project, expanded, onToggle, updateStatus, compliance }: { req: any; project: string; expanded: boolean; onToggle: () => void; updateStatus: (id: string, status: any) => void; compliance?: RequirementComplianceRow; }) {
  const { data: contract } = useGetRequirementContract(project, req.entry_id, { query: { enabled: expanded } as any });
  const statusTone = (status: string): Tone => status === 'done' ? 'mint' : status === 'in-progress' ? 'amber' : 'ink';

  return <div data-testid={`row-requirement-${req.entry_id}`} className="p-5"><div className="flex gap-3"><button data-testid={`button-expand-requirement-${req.entry_id}`} onClick={onToggle} className="mt-1 text-[#89959a]">{expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}</button><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-bold">{req.title}</h3><Badge tone={statusTone(req.status)}>{req.status}</Badge>{compliance && <Badge testId={`badge-compliance-${req.entry_id}`} tone={COMPLIANCE_TONE[compliance.verdict]} dot>{compliance.verdict === 'not-configured' ? 'No evidence configured' : `${compliance.ac_verified}/${compliance.ac_total} verified`}</Badge>}</div><p className="mt-1.5 text-sm leading-5 text-[#738087]">{req.req_key ?? 'No key'}</p><div className="mt-3"><select data-testid={`select-requirement-status-${req.entry_id}`} value={req.status} onChange={(event) => updateStatus(req.entry_id, event.target.value)} className="rounded border border-[#d1d8d4] bg-[#f1efe8] px-2 py-1 text-[11px] font-semibold text-[#58686c] outline-none"><option value="not-started">Planned</option><option value="in-progress">In progress</option><option value="done">Complete</option></select></div>
    {expanded && contract && <div className="mt-4 space-y-2 rounded-md bg-[#eef0ea] p-3"><p className="font-mono text-[10px] uppercase tracking-[.13em] text-[#7b898d]">Acceptance criteria</p>{contract.criteria.map((criterion: any) => <div key={criterion.id} className="flex items-center gap-2 text-xs text-[#53646a]"><span className={cx('flex h-4 w-4 items-center justify-center rounded-full', criterion.status === 'verified' ? 'bg-[#b9dfd1] text-[#246a5a]' : 'border border-[#c7ceca] text-[#98a3a1]')}>{criterion.status === 'verified' ? <Check size={11} /> : <Circle size={9} />}</span>{criterion.statement}<span className="ml-auto font-mono text-[10px] uppercase text-[#8a969a]">{criterion.status}</span></div>)}</div>}
    {expanded && !contract && <div className="mt-4 p-3 text-xs text-gray-500">Loading contract...</div>}
    {expanded && compliance && compliance.exceptions.length > 0 && <div className="mt-3 space-y-1.5 rounded-md border border-[#e9c1bc] bg-[#f7e1dd] p-3"><p className="font-mono text-[10px] uppercase tracking-[.13em] text-[#97433d]">Compliance exceptions</p>{compliance.exceptions.map((exception: any, index: number) => <p key={index} className="text-xs leading-5 text-[#7a3630]">{exception.summary ?? JSON.stringify(exception)}</p>)}</div>}
  </div></div></div>;
}

type RequirementStatusFilter = 'all' | 'not-started' | 'in-progress' | 'done';
const STATUS_FILTERS: Array<{ id: RequirementStatusFilter; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'not-started', label: 'Planned' },
  { id: 'in-progress', label: 'In progress' },
  { id: 'done', label: 'Complete' },
];

function Requirements() {
  const project = decodeURIComponent(useParams<{ project: string }>().project ?? '');
  const requirementsQuery = useListRequirements(project);
  const { data } = requirementsQuery;
  const reqs = data?.requirements ?? [];
  const doneCount = data?.done_count ?? 0;
  const totalCount = data?.total_count ?? 0;
  const percentage = totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0;

  const [statusFilter, setStatusFilter] = useState<RequirementStatusFilter>('all');
  const statusCounts = useMemo(() => ({
    all: reqs.length,
    'not-started': reqs.filter((r) => r.status === 'not-started').length,
    'in-progress': reqs.filter((r) => r.status === 'in-progress').length,
    done: reqs.filter((r) => r.status === 'done').length,
  }), [reqs]);
  const filteredReqs = useMemo(
    () => (statusFilter === 'all' ? reqs : reqs.filter((r) => r.status === statusFilter)),
    [reqs, statusFilter],
  );

  const [expanded, setExpanded] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [lastSync, setLastSync] = useState<SyncReport | null>(null);
  const [syncLogOpen, setSyncLogOpen] = useState(false);

  const addEntryMutation = useAddEntry();
  const syncMutation = useSyncRequirements();
  const updateEntryMutation = useUpdateEntry();

  const reqIds = useMemo(() => reqs.map((req) => req.entry_id), [reqs]);
  const { data: complianceData } = useReviewRequirementCompliance(project, { requirement_id: reqIds }, { query: { enabled: reqIds.length > 0 } as any });
  const complianceById = useMemo(() => {
    const map = new Map<string, RequirementComplianceRow>();
    complianceData?.requirements.forEach((row) => map.set(row.requirement_id, row));
    return map;
  }, [complianceData]);

  const add = () => {
    if (!newTitle.trim()) return;
    addEntryMutation.mutate({ project, data: { section: 'requirements', headline: newTitle.trim(), detail: 'New requirement captured from the project workspace.', status: 'not-started' } }, {
      onSuccess: () => {
        setNewTitle(''); setFormOpen(false);
        queryClient.invalidateQueries({ queryKey: [`/api/projects/${project}/requirements`] });
      },
      onError: (err) => notifyError('Add requirement', err),
    });
  };

  const updateStatus = (id: string, status: any) => {
    updateEntryMutation.mutate({ project, entryId: id, data: { status } }, {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: [`/api/projects/${project}/requirements`] }),
      onError: (err) => notifyError('Update requirement status', err),
    });
  };

  const runSync = () => {
    syncMutation.mutate({ project }, {
      onSuccess: (report) => {
        setLastSync(report);
        queryClient.invalidateQueries({ queryKey: [`/api/projects/${project}/requirements`] });
        if (report.ok && report.errors.length === 0) {
          notify('requirements.md synced', `${report.created.length} created · ${report.updated.length} updated · ${report.archived.length} archived`);
        } else {
          notifyError('Sync requirements', new Error(report.errors[0] ?? 'requirements.md sync completed with errors.'));
        }
      },
      onError: (err) => notifyError('Sync requirements', err),
    });
  };

  const syncOk = lastSync ? lastSync.ok && lastSync.errors.length === 0 : null;
  const syncLogEntries = lastSync
    ? [
        ...lastSync.errors.map((message) => ({ kind: 'error' as const, message })),
        ...lastSync.reconciliations.map((r) => ({ kind: 'note' as const, message: `${r.req_key}: ${r.message}` })),
      ]
    : [];

  return <>
    <PageHeader eyebrow="atlas-console / requirements" title="Requirements" description="Keep the intended behavior close to the code. Status changes are local until your next sync." actions={<><Button testId="button-sync-requirements" onClick={runSync} disabled={syncMutation.isPending} variant="secondary" size="sm">{syncMutation.isPending ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}Sync file</Button><Button testId="button-add-requirement" size="sm" onClick={() => setFormOpen((value) => !value)}><Plus size={14} />Add requirement</Button></>} />
    <ProjectTabs active="requirements" />
    {requirementsQuery.isError && <ErrorBanner testId="banner-requirements-error" message={requirementsQuery.error instanceof Error ? requirementsQuery.error.message : 'Failed to load requirements.'} onRetry={() => requirementsQuery.refetch()} />}
    <div className="grid gap-5 xl:grid-cols-[.8fr_1.2fr]">
      <div className="space-y-5">
        <section className="rounded-lg border border-[#d8dcd5] bg-[#faf9f4] p-5"><div className="flex items-end justify-between"><div><p className="font-mono text-[10px] uppercase tracking-[.16em] text-[#7d898d]">Delivery pulse</p><h2 className="mt-1 text-2xl font-bold tracking-tight">{doneCount} <span className="text-base font-normal text-[#7e8b8f]">of {totalCount} complete</span></h2></div><span className="font-mono text-2xl text-[#3155d8]">{percentage}%</span></div><div className="mt-5 h-2 overflow-hidden rounded-full bg-[#e3e6df]"><div className="h-full rounded-full bg-[#3155d8]" style={{ width: `${percentage}%` }} /></div><div className="mt-4 grid grid-cols-3 gap-2 text-center"><div><p className="font-mono text-lg">{doneCount.toString().padStart(2, '0')}</p><p className="text-[10px] uppercase tracking-wide text-[#849095]">complete</p></div><div><p className="font-mono text-lg text-[#9b701c]">{reqs.filter((r) => r.status === 'in-progress').length.toString().padStart(2, '0')}</p><p className="text-[10px] uppercase tracking-wide text-[#849095]">in progress</p></div><div><p className="font-mono text-lg text-[#849095]">{reqs.filter((r) => r.status === 'not-started').length.toString().padStart(2, '0')}</p><p className="text-[10px] uppercase tracking-wide text-[#849095]">planned</p></div></div></section>
        <div className={cx('rounded-lg border p-4', syncOk === null ? 'border-[#d7dbd4] bg-[#eef0ea]' : syncOk ? 'border-[#cbd7f4] bg-[#e8edff]' : 'border-[#e9c1bc] bg-[#f7e1dd]')}><div className="flex gap-3">{syncOk === false ? <AlertCircle className="mt-0.5 shrink-0 text-[#97433d]" size={17} /> : <CheckCircle2 className="mt-0.5 shrink-0 text-[#3155d8]" size={17} />}<div><p className={cx('text-sm font-bold', syncOk === false ? 'text-[#97433d]' : 'text-[#3047a8]')}>{lastSync === null ? 'requirements.md not synced this session' : syncOk ? 'requirements.md is in sync' : 'Sync completed with errors'}</p><p className="mt-1 text-xs leading-5 text-[#5969a1]">{lastSync === null ? 'Click "Sync file" to write the current status out to requirements.md.' : `${lastSync.created.length} created · ${lastSync.updated.length} updated · ${lastSync.archived.length} archived${lastSync.file_written ? '' : ' · file not written'}`}</p>{syncLogEntries.length > 0 && <button data-testid="button-view-sync-log" onClick={() => setSyncLogOpen((v) => !v)} className="mt-3 font-mono text-[10px] uppercase tracking-wide text-[#3155d8] underline underline-offset-2">{syncLogOpen ? 'Hide sync log' : 'View sync log'}</button>}{syncLogOpen && <div className="mt-2 space-y-1 rounded-md border border-[#d7dbd4] bg-[#faf9f4] p-2">{syncLogEntries.map((item, index) => <p key={index} className={cx('text-xs', item.kind === 'error' ? 'text-[#97433d]' : 'text-[#5969a1]')}>{item.message}</p>)}</div>}</div></div></div>
        {formOpen && <div className="rounded-lg border border-[#cbd7f4] bg-[#faf9f4] p-4"><label className="text-xs font-semibold">Requirement title<input data-testid="input-new-requirement" value={newTitle} onChange={(event) => setNewTitle(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && add()} placeholder="What should be true?" className="mt-2 h-10 w-full rounded-md border border-[#ccd4d1] bg-[#f1efe8] px-3 text-sm outline-none focus:border-[#3155d8]" /></label><div className="mt-3 flex justify-end gap-2"><Button testId="button-cancel-requirement" variant="quiet" size="sm" onClick={() => setFormOpen(false)}>Cancel</Button><Button testId="button-save-requirement" size="sm" onClick={add}>Save requirement</Button></div></div>}
      </div>
      <section className="rounded-lg border border-[#d8dcd5] bg-[#faf9f4]"><div className="flex items-center justify-between border-b border-[#e4e6df] px-5 py-4"><div><p className="font-mono text-[10px] uppercase tracking-[.16em] text-[#7d898d]">Acceptance ledger</p><h2 className="mt-1 text-base font-bold">All requirements</h2></div><span className="font-mono text-xs text-[#849095]">{filteredReqs.length.toString().padStart(2, '0')} of {reqs.length.toString().padStart(2, '0')} records</span></div>
        <div className="flex items-center gap-1 overflow-x-auto border-b border-[#e4e6df] px-3 py-2">{STATUS_FILTERS.map(({ id, label }) => <button key={id} data-testid={`filter-requirement-status-${id}`} onClick={() => setStatusFilter(id)} className={cx('flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 py-1.5 text-xs font-semibold transition-colors', statusFilter === id ? 'bg-[#e5e9ff] text-[#3047a8]' : 'text-[#758187] hover:bg-[#eef0ea] hover:text-[#34464c]')}>{label}<span className="font-mono text-[10px] text-[#98a3a1]">{statusCounts[id]}</span></button>)}</div>
        <div className="divide-y divide-[#e4e6df]">
        {filteredReqs.length === 0 && <p className="p-5 text-sm text-[#7d898d]">{reqs.length === 0 ? 'No requirements yet.' : 'No requirements match this filter.'}</p>}
        {filteredReqs.map((req) => <RequirementRow key={req.entry_id} req={req} project={project} expanded={expanded === req.entry_id} onToggle={() => setExpanded(expanded === req.entry_id ? null : req.entry_id)} updateStatus={updateStatus} compliance={complianceById.get(req.entry_id)} />)}
      </div></section>
    </div>
  </>;
}

function CodeIndex() {
  const project = decodeURIComponent(useParams<{ project: string }>().project ?? '');
  const indexStatusQuery = useGetIndexStatus(project);
  const { data: indexStatus } = indexStatusQuery;
  const reindexMutation = useReindex();
  const [done, setDone] = useState(false);
  
  const runIndex = (incremental: boolean) => {
    setDone(false);
    reindexMutation.mutate({ project, data: { incremental } }, {
      onSuccess: () => {
        setDone(true);
        queryClient.invalidateQueries({ queryKey: [`/api/projects/${project}/index-status`] });
      },
      onError: (err) => notifyError(incremental ? 'Re-index' : 'Full rebuild', err),
    });
  };
  const indexing = reindexMutation.isPending;
  
  const formatTime = (iso?: string | null) => iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Never';
  const formatDate = (iso?: string | null) => iso ? new Date(iso).toLocaleDateString() : '';

  return <><PageHeader eyebrow="atlas-console / code index" title="Code index" description="The retrieval layer beneath the briefing. Keep it current when the shape of the repo changes." actions={<><Button testId="button-reindex" variant="secondary" size="sm" onClick={() => runIndex(true)} disabled={indexing}>{indexing ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}Re-index changes</Button><Button testId="button-full-rebuild" size="sm" onClick={() => runIndex(false)} disabled={indexing}><Zap size={14} />Full rebuild</Button></>} /><ProjectTabs active="index" />
    {indexStatusQuery.isError && <ErrorBanner testId="banner-index-status-error" message={indexStatusQuery.error instanceof Error ? indexStatusQuery.error.message : 'Failed to load index status.'} onRetry={() => indexStatusQuery.refetch()} />}
    {done && <div className="mb-5 flex items-center gap-3 rounded-md border border-[#b9dfd1] bg-[#dcefe7] px-4 py-3 text-sm text-[#246a5a] animate-enter"><CheckCircle2 size={17} /><span><strong>Index refresh initiated.</strong> Check status shortly.</span><button data-testid="button-dismiss-index-notice" onClick={() => setDone(false)} className="ml-auto"><X size={16} /></button></div>}
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4"><Stat label="Indexed files" value={(indexStatus?.file_count ?? 0).toString()} sub="in index" icon={FileCode2} /><Stat label="Search chunks" value={(indexStatus?.chunk_count ?? 0).toString()} sub="indexed" accent="mint" icon={Layers3} /><Stat label="Last run" value={formatTime(indexStatus?.last_incremental_at || indexStatus?.last_full_at)} sub={formatDate(indexStatus?.last_incremental_at || indexStatus?.last_full_at)} accent="amber" icon={Activity} /><Stat label="Skipped" value={(indexStatus?.skipped_count ?? 0).toString().padStart(2, '0')} sub="see below" accent="red" icon={AlertCircle} /></div>
    <div className="mt-5 grid gap-5 xl:grid-cols-[1.2fr_.8fr]"><section className="rounded-lg border border-[#d8dcd5] bg-[#faf9f4]"><div className="border-b border-[#e4e6df] px-5 py-4"><p className="font-mono text-[10px] uppercase tracking-[.16em] text-[#7d898d]">Index configuration</p><h2 className="mt-1 text-base font-bold">What PCS can retrieve</h2></div><div className="grid gap-3 p-5 sm:grid-cols-2"><div className="rounded-md border border-[#dfe3dc] bg-[#eef0ea] p-4"><div className="flex items-center gap-2"><Search size={15} className="text-[#3155d8]" /><span className="text-sm font-bold">Semantic search</span><Badge tone={indexStatus?.semantic_available ? 'mint' : 'amber'} dot>{indexStatus?.semantic_available ? 'Available' : 'Pending'}</Badge></div><p className="mt-2 text-xs leading-5 text-[#758287]">{indexStatus?.semantic_note ?? 'Embeddings configured via AI settings.'}</p></div><div className="rounded-md border border-[#dfe3dc] bg-[#eef0ea] p-4"><div className="flex items-center gap-2"><Code2 size={15} className="text-[#3155d8]" /><span className="text-sm font-bold">Symbol index</span><Badge tone="mint" dot>Ready</Badge></div><p className="mt-2 text-xs leading-5 text-[#758287]">TypeScript, TSX, JSON, and Markdown parsers enabled.</p></div></div><div className="mx-5 mb-5 flex items-center justify-between border-t border-[#e1e4dc] pt-4 text-xs text-[#7b898d]"><span>Auto-index on file change</span><button data-testid="button-toggle-auto-index" disabled title="Controlled by PCS_INDEX_WATCH on the server — not configurable from this UI" className="flex h-5 w-9 cursor-not-allowed items-center rounded-full bg-[#3155d8] p-0.5 opacity-50"><span className="ml-auto h-4 w-4 rounded-full bg-[#faf9f4]" /></button></div></section><section className="rounded-lg border border-[#d8dcd5] bg-[#faf9f4]"><div className="border-b border-[#e4e6df] px-5 py-4"><p className="font-mono text-[10px] uppercase tracking-[.16em] text-[#7d898d]">Ignored by policy</p><h2 className="mt-1 text-base font-bold">Skipped files</h2></div><div className="divide-y divide-[#e5e7e0]">{indexStatus?.skipped?.map((file) => <div key={file.path} className="flex items-center gap-3 px-5 py-3 text-xs"><FileText size={14} className="text-[#9aa5a5]" /><span className="font-mono text-[#53646a]">{file.path}</span><span className="ml-auto text-[10px] text-[#9aa5a5]">{file.reason}</span></div>)}</div><button data-testid="button-edit-ignore-rules" disabled title="Ignore rules are fixed server-side policy — not editable from this UI yet" className="m-4 cursor-not-allowed font-mono text-[10px] uppercase tracking-wide text-[#a3aeb0]">Ignore rules are server policy</button></section></div>
  </>;
}

// Ember = a blocker/bug hot spot, growth = the current focus, mist = a
// requirement-linked file (FR33/AC12 — never the Signal blue used for status).
const OVERLAY_DOT_CLASS: Record<string, string> = {
  ember: 'bg-[#c65b51]',
  growth: 'bg-[#3155d8]',
  mist: 'bg-[#8ea6c9]',
};

function TreeNode({ project, node, depth = 0, graph, onMerge, onSelect, selectedPath }: {
  project: string; node: MergedNode; depth?: number; graph: CodeGraph;
  onMerge: (map: CodeMapResponse) => void; onSelect: (path: string) => void; selectedPath: string | null;
}) {
  const [open, setOpen] = useState(false);
  const isDir = node.kind === 'directory';
  const needsFetch = isDir && node.has_children && !node.expanded;
  const { data: map, isFetching } = useGetCodeMap(project, { scope: node.path }, { query: { enabled: open && needsFetch } as any });

  useEffect(() => {
    if (map) onMerge(map);
  }, [map, onMerge]);

  const toggle = () => {
    if (isDir) setOpen((value) => !value);
    else onSelect(node.path);
  };

  const dotClass = OVERLAY_DOT_CLASS[overlayTone(node.overlay) ?? ''];

  const children = open
    ? [...graph.nodes.values()]
        .filter((n) => n.id !== node.id && !n.outside_scope && n.path.startsWith(node.path + '/') && n.path.slice(node.path.length + 1).indexOf('/') === -1)
        .sort((a, b) => (a.kind === b.kind ? a.label.localeCompare(b.label) : a.kind === 'directory' ? -1 : 1))
    : [];

  return <div><button data-testid={`button-tree-${node.id}`} onClick={toggle} className={cx('flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-[#e8edff]', !isDir && 'font-mono text-[#53646a]', selectedPath === node.path && 'bg-[#e8edff]')} style={{ paddingLeft: `${10 + depth * 16}px` }}>{isDir ? (open ? <ChevronDown size={13} /> : <ChevronRight size={13} />) : <FileCode2 size={13} className="text-[#718287]" />}<span className="truncate">{node.label}</span>{dotClass && <span className={cx('ml-auto h-1.5 w-1.5 shrink-0 rounded-full', dotClass)} />}</button>
    {open && needsFetch && isFetching && <div style={{ paddingLeft: `${26 + depth * 16}px` }} className="py-1 text-xs text-gray-400">Loading...</div>}
    {open && children.map((child) => <TreeNode key={child.id} project={project} node={child} depth={depth + 1} graph={graph} onMerge={onMerge} onSelect={onSelect} selectedPath={selectedPath} />)}
  </div>;
}

function CodeMap() {
  const project = decodeURIComponent(useParams<{ project: string }>().project ?? '');
  const [query, setQuery] = useState('');
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [graph, setGraph] = useState<CodeGraph>(() => emptyGraph());

  const mergeTier = useCallback((map: CodeMapResponse) => setGraph((current) => mergeCodeMap(current, map)), []);

  const rootMapQuery = useGetCodeMap(project);
  const { data: rootMap } = rootMapQuery;
  useEffect(() => {
    if (rootMap) mergeTier(rootMap);
  }, [rootMap, mergeTier]);

  const rootNodes = [...graph.nodes.values()]
    .filter((n) => !n.outside_scope && n.path.indexOf('/') === -1)
    .sort((a, b) => (a.kind === b.kind ? a.label.localeCompare(b.label) : a.kind === 'directory' ? -1 : 1));

  const { data: searchResults } = useSearchCode(project, { q: query }, { query: { enabled: query.length > 2 } as any });
  const { data: sourceData } = useGetSource(project, { path: selectedPath ?? '' }, { query: { enabled: !!selectedPath } as any });

  const selectHit = (path: string) => {
    // Reveal the tree ancestor so the selection is visible if the user
    // switches back from search results to the browse view (FR35).
    const located = locateHit(graph, path);
    if (located.kind === 'node') {
      const hitNode = graph.nodes.get(located.nodeId);
      if (hitNode) {
        setSelectedPath(hitNode.path);
        return;
      }
    }
    setSelectedPath(path);
  };

  const selectedNode = selectedPath ? graph.nodes.get(`file:${selectedPath}`) ?? null : null;

  // Context entries whose linked_files touch the selected path (FR34).
  const { data: blockersData } = useGetSection(project, 'blockers', undefined, { query: { enabled: !!selectedPath } as any });
  const { data: bugsData } = useGetSection(project, 'bugs', undefined, { query: { enabled: !!selectedPath } as any });
  const { data: conventionsData } = useGetSection(project, 'conventions', undefined, { query: { enabled: !!selectedPath } as any });
  const { data: decisionsData } = useGetSection(project, 'decisions', undefined, { query: { enabled: !!selectedPath } as any });
  const { data: requirementsData } = useGetSection(project, 'requirements', undefined, { query: { enabled: !!selectedPath } as any });

  const relatedSections = useMemo<Record<string, readonly Entry[]>>(() => ({
    blockers: blockersData?.entries ?? [],
    bugs: bugsData?.entries ?? [],
    conventions: conventionsData?.entries ?? [],
    decisions: decisionsData?.entries ?? [],
    requirements: requirementsData?.entries ?? [],
  }), [blockersData, bugsData, conventionsData, decisionsData, requirementsData]);

  const related = selectedPath ? relatedEntries(relatedSections, selectedPath) : [];

  const copySource = async () => {
    const text = sourceData?.content ?? '';
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      notify('Copied', `${selectedPath} copied to clipboard.`);
    } catch (err) {
      notifyError('Copy source', err);
    }
  };

  return <><PageHeader eyebrow="atlas-console / code map" title="Code map" description="A readable surface over the repository index. Follow the hot spots, then inspect the context around a file." actions={rootMap ? <Badge tone="mint" dot testId="status-code-map">{rootMap.stats.node_count} nodes · {rootMap.stats.edge_count} edges</Badge> : rootMapQuery.isError ? <Badge tone="red" dot testId="status-code-map">Failed to load</Badge> : <Badge tone="amber" dot testId="status-code-map">Loading index…</Badge>} /><ProjectTabs active="code-map" />
    {rootMapQuery.isError && <ErrorBanner testId="banner-codemap-error" message={rootMapQuery.error instanceof Error ? rootMapQuery.error.message : 'Failed to load the code map.'} onRetry={() => rootMapQuery.refetch()} />}
    <div className="grid min-h-[570px] gap-4 xl:grid-cols-[280px_1fr_320px]"><section className="rounded-lg border border-[#d8dcd5] bg-[#faf9f4]"><div className="border-b border-[#e4e6df] p-3"><div className="relative"><Search className="absolute left-2.5 top-2.5 text-[#8d999d]" size={14} /><input data-testid="input-code-map-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter files…" className="h-9 w-full rounded-md border border-[#d1d8d4] bg-[#eef0ea] pl-8 pr-3 text-xs outline-none focus:border-[#3155d8]" /></div><div className="mt-3 flex items-center justify-between"><span className="font-mono text-[10px] uppercase tracking-[.12em] text-[#7e8c90]">Repository</span></div></div><div className="p-2 overflow-y-auto max-h-[500px]">
      {query.length > 2 ?
        searchResults?.hits?.map((hit) => <div key={hit.path} data-testid={`hit-code-map-${hit.path}`} className={cx('px-2 py-1.5 text-xs font-mono hover:bg-[#e8edff] text-[#53646a] cursor-pointer rounded', selectedPath === hit.path && 'bg-[#e8edff]')} onClick={() => selectHit(hit.path)}>{hit.path}</div>)
      : rootNodes.map((node) => <TreeNode key={node.id} project={project} node={node} graph={graph} onMerge={mergeTier} onSelect={setSelectedPath} selectedPath={selectedPath} />)}
    </div></section><section className="overflow-hidden rounded-lg border border-[#d8dcd5] bg-[#faf9f4] flex flex-col"><div className="flex items-center justify-between border-b border-[#e4e6df] px-5 py-4 shrink-0"><div><p className="font-mono text-[10px] uppercase tracking-[.12em] text-[#7d898d]">File preview</p><h2 className="mt-1 text-sm font-bold">{selectedPath ?? 'No file selected'}</h2></div><div className="flex items-center gap-2"><button data-testid="button-copy-source" onClick={copySource} disabled={!sourceData?.content} className="rounded p-1.5 text-[#879397] hover:bg-[#e8edff] hover:text-[#3155d8] disabled:cursor-not-allowed disabled:opacity-40"><Copy size={14} /></button></div></div><div className="overflow-auto bg-[#202f35] p-5 text-[#d6ded6] grow flex flex-col">
      {sourceData ? <pre data-testid="text-source-preview" className="font-mono text-xs leading-7">{(sourceData.content || '').split('\n').map((line: string, index: number) => <div key={index} className="flex"><span className="mr-5 inline-block w-5 shrink-0 select-none text-right text-[#64777b]">{String(index + 1).padStart(2, '0')}</span><code>{line || ' '}</code></div>)}</pre> : <div className="text-sm text-[#64777b] m-auto">Select a file to preview</div>}
    </div></section><aside className="space-y-4"><section className="rounded-lg border border-[#d8dcd5] bg-[#faf9f4]"><div className="border-b border-[#e4e6df] px-4 py-4"><p className="font-mono text-[10px] uppercase tracking-[.12em] text-[#7d898d]">Related context</p><h2 className="mt-1 text-sm font-bold">What connects here</h2></div><div className="space-y-2 p-3">
      {!selectedPath && <p className="text-xs text-[#7d898d] italic">Select a file to see linked context.</p>}
      {selectedPath && related.length === 0 && <p className="text-xs text-[#7d898d] italic">Nothing links to this file yet.</p>}
      {related.map(({ section, entry }) => <div key={entry.id} data-testid={`related-entry-${entry.id}`} className="rounded-md border border-[#e4e6df] bg-[#eef0ea] p-2.5"><div className="flex items-center gap-2"><Badge tone="blue">{section}</Badge>{entry.status === 'resolved' && <span className="text-[10px] text-[#78868b]">resolved</span>}</div><p className={cx('mt-1.5 text-xs leading-5 text-[#4a5a60]', entry.status === 'resolved' && 'line-through opacity-70')}>{entry.headline}</p></div>)}
    </div></section><section className="rounded-lg border border-[#d8dcd5] bg-[#faf9f4] p-4"><div className="flex items-center gap-2"><Activity size={15} className="text-[#d09c2b]" /><h2 className="text-sm font-bold">File activity</h2></div>
      {!selectedNode && <p className="mt-3 text-xs text-[#7d898d]">{selectedPath ? 'Not present in the loaded map tiers yet.' : 'No file selected.'}</p>}
      {selectedNode && <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-[#53646a]"><span>Blockers</span><span className="text-right font-mono">{selectedNode.overlay.blockers}</span><span>Bugs</span><span className="text-right font-mono">{selectedNode.overlay.bugs}</span><span>Requirements</span><span className="text-right font-mono">{selectedNode.overlay.requirements}</span><span>Fan in / out</span><span className="text-right font-mono">{selectedNode.fan_in} / {selectedNode.fan_out}</span></div>}
    </section></aside></div>
  </>;
}

export function Field({ label, value, onChange, placeholder, type = 'text', hint, testId }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; type?: string; hint?: string; testId?: string }) {
  return <label className="block text-xs font-semibold text-[#53646a]">{label}<input data-testid={testId ?? `input-${label.toLowerCase().replace(/\s+/g, '-')}`} type={type} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="mt-2 h-10 w-full rounded-md border border-[#ccd4d1] bg-[#f1efe8] px-3 text-sm font-normal text-[#203238] outline-none placeholder:text-[#a0aaa8] focus:border-[#3155d8] focus:ring-2 focus:ring-[#3155d8]/10" />{hint && <span className="mt-1.5 block text-[10px] font-normal text-[#889498]">{hint}</span>}</label>;
}

// Backends the server actually accepts (pcs/ai_settings.py::_provider) — "hashing"
// is a local no-network fallback and only valid for embeddings.
const EMBEDDING_BACKENDS = ['openai', 'openai-compatible', 'hashing'] as const;
const SUMMARY_BACKENDS = ['openai', 'openai-compatible'] as const;

type EmbeddingForm = { backend: string; base_url: string; model: string; dimensions: string; batch_size: string; timeout_seconds: string; api_key: string };
type SummaryForm = { backend: string; base_url: string; model: string; timeout_seconds: string; api_key: string };

function providerSaveStatus(pending: boolean, success: boolean, error: string | null) {
  return <span className={cx('text-xs', error ? 'text-[#97433d]' : success ? 'text-[#246a5a]' : 'text-[#7e8b8f]')}>{pending ? 'Saving provider…' : error ?? (success ? 'Saved just now' : 'Changes apply to the next index run.')}</span>;
}

function EmbeddingCard({ settings, onSaved }: { settings: EmbeddingSettings; onSaved: (data: AiSettings) => void }) {
  const [form, setForm] = useState<EmbeddingForm>(() => ({ backend: settings.backend, base_url: settings.base_url, model: settings.model, dimensions: String(settings.dimensions), batch_size: String(settings.batch_size), timeout_seconds: String(settings.timeout_seconds), api_key: '' }));
  const [error, setError] = useState<string | null>(null);
  const mutation = useUpdateAiSettings();
  const set = (key: keyof EmbeddingForm) => (value: string) => setForm((prev) => ({ ...prev, [key]: value }));

  const save = () => {
    const dimensions = Number(form.dimensions);
    const batch_size = Number(form.batch_size);
    const timeout_seconds = Number(form.timeout_seconds);
    if (!form.base_url || !form.model || !Number.isFinite(dimensions) || dimensions <= 0 || !Number.isFinite(batch_size) || batch_size <= 0 || !Number.isFinite(timeout_seconds) || timeout_seconds <= 0) {
      setError('All fields are required and numeric fields must be positive.');
      return;
    }
    setError(null);
    mutation.mutate({ data: { embedding: { backend: form.backend, base_url: form.base_url, model: form.model, dimensions, batch_size, timeout_seconds, ...(form.api_key ? { api_key: form.api_key } : {}) } } }, {
      onSuccess: (data) => { setForm((prev) => ({ ...prev, api_key: '' })); onSaved(data); },
      onError: (err: unknown) => setError(err instanceof Error ? err.message : 'Failed to save embedding settings.'),
    });
  };

  return <section className="rounded-lg border border-[#d8dcd5] bg-[#faf9f4]"><div className="flex items-start justify-between border-b border-[#e4e6df] p-5"><div><div className="flex items-center gap-2"><span className="flex h-8 w-8 items-center justify-center rounded-md bg-[#e5e9ff] text-[#3155d8]"><Layers3 size={16} /></span><h2 className="text-lg font-bold">Embeddings</h2></div><p className="mt-2 max-w-md text-xs leading-5 text-[#7a878b]">Turn repository chunks into searchable vectors.</p></div><Badge tone={settings.api_key_configured ? 'mint' : 'amber'} dot>{settings.api_key_configured ? 'Key configured' : `Source: ${settings.source}`}</Badge></div><div className="grid gap-4 p-5 md:grid-cols-2"><label className="block text-xs font-semibold text-[#53646a]">Backend<select data-testid="select-embeddings-backend" value={form.backend} onChange={(event) => set('backend')(event.target.value)} className="mt-2 h-10 w-full rounded-md border border-[#ccd4d1] bg-[#f1efe8] px-3 text-sm font-normal outline-none focus:border-[#3155d8]">{EMBEDDING_BACKENDS.map((backend) => <option key={backend} value={backend}>{backend}</option>)}</select></label><Field testId="input-embeddings-base-url" label="Base URL" value={form.base_url} onChange={set('base_url')} placeholder="https://api.openai.com/v1" /><Field testId="input-embeddings-model" label="Model" value={form.model} onChange={set('model')} placeholder="text-embedding-3-small" /><Field testId="input-embeddings-api-key" label="API key" value={form.api_key} onChange={set('api_key')} placeholder="Leave blank to keep current key" type="password" hint="Write-only. PCS never reads the stored key back." /><Field testId="input-embeddings-dimensions" label="Dimensions" value={form.dimensions} onChange={set('dimensions')} type="number" hint="Vector dimensions returned by the model." /><Field testId="input-embeddings-batch-size" label="Batch size" value={form.batch_size} onChange={set('batch_size')} type="number" /><Field testId="input-embeddings-timeout" label="Timeout (seconds)" value={form.timeout_seconds} onChange={set('timeout_seconds')} type="number" /></div><div className="flex items-center justify-between border-t border-[#e4e6df] bg-[#f5f4ee] px-5 py-3">{providerSaveStatus(mutation.isPending, mutation.isSuccess, error)}<Button testId="button-save-embeddings" size="sm" onClick={save} disabled={mutation.isPending}>{mutation.isPending ? <Loader2 className="animate-spin" size={13} /> : mutation.isSuccess ? <Check size={13} /> : 'Save changes'}</Button></div></section>;
}

function SummaryCard({ settings, onSaved }: { settings: SummarySettings; onSaved: (data: AiSettings) => void }) {
  const [form, setForm] = useState<SummaryForm>(() => ({ backend: settings.backend, base_url: settings.base_url, model: settings.model, timeout_seconds: String(settings.timeout_seconds), api_key: '' }));
  const [error, setError] = useState<string | null>(null);
  const mutation = useUpdateAiSettings();
  const set = (key: keyof SummaryForm) => (value: string) => setForm((prev) => ({ ...prev, [key]: value }));

  const save = () => {
    const timeout_seconds = Number(form.timeout_seconds);
    if (!form.base_url || !form.model || !Number.isFinite(timeout_seconds) || timeout_seconds <= 0) {
      setError('All fields are required and the timeout must be positive.');
      return;
    }
    setError(null);
    mutation.mutate({ data: { summary: { backend: form.backend, base_url: form.base_url, model: form.model, timeout_seconds, ...(form.api_key ? { api_key: form.api_key } : {}) } } }, {
      onSuccess: (data) => { setForm((prev) => ({ ...prev, api_key: '' })); onSaved(data); },
      onError: (err: unknown) => setError(err instanceof Error ? err.message : 'Failed to save summarization settings.'),
    });
  };

  return <section className="rounded-lg border border-[#d8dcd5] bg-[#faf9f4]"><div className="flex items-start justify-between border-b border-[#e4e6df] p-5"><div><div className="flex items-center gap-2"><span className="flex h-8 w-8 items-center justify-center rounded-md bg-[#e5e9ff] text-[#3155d8]"><Sparkles size={16} /></span><h2 className="text-lg font-bold">Summarization</h2></div><p className="mt-2 max-w-md text-xs leading-5 text-[#7a878b]">Create the concise briefing that agents read first.</p></div><Badge tone={settings.api_key_configured ? 'mint' : 'amber'} dot>{settings.api_key_configured ? 'Key configured' : `Source: ${settings.source}`}</Badge></div><div className="grid gap-4 p-5 md:grid-cols-2"><label className="block text-xs font-semibold text-[#53646a]">Backend<select data-testid="select-summarization-backend" value={form.backend} onChange={(event) => set('backend')(event.target.value)} className="mt-2 h-10 w-full rounded-md border border-[#ccd4d1] bg-[#f1efe8] px-3 text-sm font-normal outline-none focus:border-[#3155d8]">{SUMMARY_BACKENDS.map((backend) => <option key={backend} value={backend}>{backend}</option>)}</select></label><Field testId="input-summarization-base-url" label="Base URL" value={form.base_url} onChange={set('base_url')} placeholder="https://api.openai.com/v1" /><Field testId="input-summarization-model" label="Model" value={form.model} onChange={set('model')} placeholder="gpt-4o-mini" /><Field testId="input-summarization-api-key" label="API key" value={form.api_key} onChange={set('api_key')} placeholder="Leave blank to keep current key" type="password" hint="Write-only. PCS never reads the stored key back." /><Field testId="input-summarization-timeout" label="Timeout (seconds)" value={form.timeout_seconds} onChange={set('timeout_seconds')} type="number" /></div><div className="flex items-center justify-between border-t border-[#e4e6df] bg-[#f5f4ee] px-5 py-3">{providerSaveStatus(mutation.isPending, mutation.isSuccess, error)}<Button testId="button-save-summarization" size="sm" onClick={save} disabled={mutation.isPending}>{mutation.isPending ? <Loader2 className="animate-spin" size={13} /> : mutation.isSuccess ? <Check size={13} /> : 'Save changes'}</Button></div></section>;
}

function AdminTokenCard() {
  const [token, setToken] = useState(() => readAdminToken() ?? '');
  const [saved, setSaved] = useState(false);

  const save = () => {
    try {
      if (token) localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, token);
      else localStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY);
    } catch {
      // localStorage unavailable (private mode, etc.) — token just won't persist across reloads.
    }
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  return <section className="rounded-lg border border-[#d8dcd5] bg-[#faf9f4] p-5"><div className="flex items-center gap-2"><span className="flex h-8 w-8 items-center justify-center rounded-md bg-[#e5e9ff] text-[#3155d8]"><Settings2 size={16} /></span><h2 className="text-lg font-bold">Admin access</h2></div><p className="mt-2 max-w-lg text-xs leading-5 text-[#7a878b]">Saving provider changes below requires the PCS server's admin token. It's kept only in this browser's local storage and sent as the <code>x-pcs-admin-token</code> header on PCS requests.</p><div className="mt-4 flex flex-wrap items-end gap-3"><div className="min-w-[260px] flex-1"><Field testId="input-admin-token" label="Admin token" value={token} onChange={setToken} placeholder="Paste the server's admin token" type="password" /></div><Button testId="button-save-admin-token" size="sm" variant="secondary" onClick={save}>{saved ? <Check size={13} /> : 'Save token'}</Button></div></section>;
}

function AISettings() {
  const settingsQuery = useGetAiSettings();
  const { data: settings, isLoading, isError, error, refetch } = settingsQuery;
  const onSaved = (data: AiSettings) => queryClient.setQueryData(getGetAiSettingsQueryKey(), data);

  return <><PageHeader eyebrow="system / ai providers" title="AI providers" description="Independent provider settings for retrieval and summarization. Keys are write-only and stay in your local configuration." actions={settings ? <Badge tone={settings.reindex_required ? 'amber' : 'mint'} dot testId="status-ai-connection">{settings.reindex_required ? 'Reindex required' : 'Providers in sync'}</Badge> : undefined} /><div className="mb-6 rounded-lg border border-[#d5c98c] bg-[#f8edcf] p-4"><div className="flex gap-3"><Settings2 className="mt-0.5 shrink-0 text-[#856115]" size={17} /><div><p className="text-sm font-bold text-[#725617]">Configuration is scoped to this workspace</p><p className="mt-1 text-xs leading-5 text-[#856115]">PCS never displays stored secrets. Blank API key fields mean the current key will be preserved when you save.</p></div></div></div>
    {isError && <ErrorBanner testId="banner-ai-settings-error" message={error instanceof Error ? error.message : 'Failed to load AI provider settings.'} onRetry={() => refetch()} />}
    <div className="space-y-5">
      <AdminTokenCard />
      {isLoading && <div className="py-10 text-center"><Loader2 className="animate-spin mx-auto text-[#3155d8]" /></div>}
      {settings && <><EmbeddingCard settings={settings.embedding} onSaved={onSaved} /><SummaryCard settings={settings.summary} onSaved={onSaved} /></>}
    </div></>;
}

function NotFound() { return <div className="flex min-h-[100dvh] items-center justify-center bg-[#f1efe8] p-6"><div className="text-center"><p className="font-mono text-xs text-[#3155d8]">404 / not in the map</p><h1 className="mt-3 text-4xl font-bold">This context does not exist.</h1><Link href="/" data-testid="link-back-home" className="mt-5 inline-flex text-sm font-semibold text-[#3155d8]">Return to projects <ArrowRight size={15} className="ml-2" /></Link></div></div>; }

function RoutedErrorBoundary({ children }: { children: ReactNode }) { const [location] = useLocation(); return <ErrorBoundary resetKey={location}>{children}</ErrorBoundary>; }
function Router() {
  return <RoutedErrorBoundary><Switch><Route path="/" component={HomePicker} /><Route path="/settings/ai"><AppShell><AISettings /></AppShell></Route><Route path="/projects/:project/dashboard"><AppShell><Dashboard /></AppShell></Route><Route path="/projects/:project/requirements"><AppShell><Requirements /></AppShell></Route><Route path="/projects/:project/plans"><AppShell><Plans /></AppShell></Route><Route path="/projects/:project/index"><AppShell><CodeIndex /></AppShell></Route><Route path="/projects/:project/code-map"><AppShell><CodeMap /></AppShell></Route><Route component={NotFound} /></Switch></RoutedErrorBoundary>;
}
function App() { return <QueryClientProvider client={queryClient}><TooltipProvider><WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, '')}><Router /></WouterRouter><Toaster /></TooltipProvider></QueryClientProvider>; }
export default App;