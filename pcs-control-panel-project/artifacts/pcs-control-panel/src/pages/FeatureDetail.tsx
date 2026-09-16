import { Link, useParams } from 'wouter';
import { useGetSection, useListRequirements } from '@workspace/api-client-react';
import { ArrowLeft, FileCode2, Loader2 } from 'lucide-react';
import { Badge, combineQueryErrors, ErrorBanner, PageHeader, ProjectTabs, type Tone } from '../App';
import { MermaidDiagram } from '../components/MermaidDiagram';
import { resolveFeatureRequirements } from '../lib/features';

const STATUS_TONE: Record<string, Tone> = {
  done: 'mint',
  'in-progress': 'amber',
  blocked: 'red',
  'not-started': 'ink',
};

export default function FeatureDetail() {
  const params = useParams<{ project: string; id: string }>();
  const project = decodeURIComponent(params.project ?? '');
  const featureId = params.id ?? '';

  const featuresQuery = useGetSection(project, 'features');
  const requirementsQuery = useListRequirements(project);

  const features = featuresQuery.data?.entries ?? [];
  const feature = features.find((f) => f.id === featureId);
  const [resolved] = feature
    ? resolveFeatureRequirements([feature], requirementsQuery.data?.requirements ?? [])
    : [undefined];

  const loadError = combineQueryErrors(featuresQuery, requirementsQuery);
  const loading = featuresQuery.isLoading || requirementsQuery.isLoading;

  return (
    <>
      <PageHeader
        eyebrow="atlas-console / features"
        title={feature ? feature.headline : 'Feature'}
        description="Sequence diagram and the files that implement this feature."
        actions={
          <Link
            href={`/projects/${encodeURIComponent(project)}/features`}
            data-testid="link-back-to-features"
            className="inline-flex items-center gap-1.5 text-sm font-semibold text-[#3155d8]"
          >
            <ArrowLeft size={14} />
            Back to Features
          </Link>
        }
      />
      <ProjectTabs active="features" />
      {loadError.isError && (
        <ErrorBanner testId="banner-feature-detail-error" message={loadError.message} onRetry={loadError.retry} />
      )}

      {loading && (
        <div className="py-10 text-center">
          <Loader2 className="animate-spin mx-auto text-[#3155d8]" />
        </div>
      )}

      {!loading && !loadError.isError && !feature && (
        <div className="rounded-lg border border-dashed border-[#c7d0cb] bg-[#faf9f4] py-16 text-center">
          <p className="font-semibold">Feature not found</p>
          <p className="mt-1 text-sm text-[#7b888c]">It may have been resolved or removed.</p>
        </div>
      )}

      {feature && (
        <div className="space-y-4">
          {resolved?.requirement && (
            <div title={resolved.requirement.title}>
              <Badge tone={STATUS_TONE[resolved.requirement.status] ?? 'ink'} dot testId="badge-feature-detail-requirement">
                {resolved.requirement.title}
              </Badge>
            </div>
          )}

          <section className="rounded-lg border border-[#d8dcd5] bg-[#faf9f4] p-5">
            <p className="font-mono text-[10px] uppercase tracking-[.13em] text-[#7d898d]">Overview</p>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-[#3a4a4f]">{feature.detail}</p>
          </section>

          <section className="rounded-lg border border-[#d8dcd5] bg-[#faf9f4] p-5">
            <p className="font-mono text-[10px] uppercase tracking-[.13em] text-[#7d898d]">Sequence diagram</p>
            {feature.diagram ? (
              <div className="mt-3">
                <MermaidDiagram code={feature.diagram} />
              </div>
            ) : (
              <p className="mt-2 text-sm text-[#7b888c]">
                No diagram documented yet. Ask an agent to add one via update_feature.
              </p>
            )}
          </section>

          <section className="rounded-lg border border-[#d8dcd5] bg-[#faf9f4] p-5">
            <p className="font-mono text-[10px] uppercase tracking-[.13em] text-[#7d898d]">Related files</p>
            {feature.linked_files.length === 0 ? (
              <p className="mt-2 text-sm text-[#7b888c]">No files linked to this feature yet.</p>
            ) : (
              <div className="mt-3 flex flex-wrap gap-2">
                {feature.linked_files.map((path) => (
                  <Link
                    key={path}
                    href={`/projects/${encodeURIComponent(project)}/code-map?file=${encodeURIComponent(path)}`}
                    data-testid={`link-feature-file-${path}`}
                    className="inline-flex items-center gap-1.5 rounded bg-[#eef0ea] px-2.5 py-1.5 font-mono text-[11px] text-[#3f4f53] hover:bg-[#e5e9ff] hover:text-[#3047a8]"
                  >
                    <FileCode2 size={12} />
                    {path}
                  </Link>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </>
  );
}
