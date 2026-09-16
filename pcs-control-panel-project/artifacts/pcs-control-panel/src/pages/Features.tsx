import { Link, useParams } from 'wouter';
import { useGetSection, useListRequirements } from '@workspace/api-client-react';
import { FileCode2, Loader2 } from 'lucide-react';
import { Badge, combineQueryErrors, ErrorBanner, PageHeader, ProjectTabs, type Tone } from '../App';
import { resolveFeatureRequirements } from '../lib/features';

const STATUS_TONE: Record<string, Tone> = {
  done: 'mint',
  'in-progress': 'amber',
  blocked: 'red',
  'not-started': 'ink',
};

export default function Features() {
  const project = decodeURIComponent(useParams<{ project: string }>().project ?? '');

  const featuresQuery = useGetSection(project, 'features');
  const requirementsQuery = useListRequirements(project);

  const features = featuresQuery.data?.entries ?? [];
  const resolved = resolveFeatureRequirements(features, requirementsQuery.data?.requirements ?? []);

  const loadError = combineQueryErrors(featuresQuery, requirementsQuery);
  const loading = featuresQuery.isLoading || requirementsQuery.isLoading;

  return (
    <>
      <PageHeader
        eyebrow="atlas-console / features"
        title="Features"
        description="What each feature does, the files that implement it, and the requirement it satisfies — for humans browsing the codebase, not the agent briefing."
        actions={
          <Badge tone="blue" dot testId="status-features-count">
            {features.length} documented
          </Badge>
        }
      />
      <ProjectTabs active="features" />
      {loadError.isError && (
        <ErrorBanner testId="banner-features-error" message={loadError.message} onRetry={loadError.retry} />
      )}

      {loading && (
        <div className="py-10 text-center">
          <Loader2 className="animate-spin mx-auto text-[#3155d8]" />
        </div>
      )}

      {!loading && features.length === 0 && (
        <div
          data-testid="empty-features"
          className="rounded-lg border border-dashed border-[#c7d0cb] bg-[#faf9f4] py-16 text-center"
        >
          <FileCode2 className="mx-auto text-[#9eaaa5]" size={28} />
          <p className="mt-3 font-semibold">No features documented yet</p>
          <p className="mt-1 text-sm text-[#7b888c]">
            Ask an agent to explain this codebase's features, files, and I/O — it should write the
            result here via add_feature/update_feature instead of a standalone .md file.
          </p>
        </div>
      )}

      {features.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2">
          {resolved.map(({ feature, requirement }) => {
            return (
              <Link
                key={feature.id}
                href={`/projects/${encodeURIComponent(project)}/features/${feature.id}`}
                data-testid={`card-feature-${feature.id}`}
                className="block rounded-lg border border-[#d8dcd5] bg-[#faf9f4] p-4 shadow-[0_1px_0_rgba(31,43,45,.04)] transition-colors hover:border-[#9daeb3]"
              >
                <h3 className="text-sm font-bold">{feature.headline}</h3>
                {requirement && (
                  <div className="mt-1.5 max-w-full" title={requirement.title}>
                    <Badge
                      tone={STATUS_TONE[requirement.status] ?? 'ink'}
                      dot
                      testId={`badge-feature-requirement-${feature.id}`}
                    >
                      <span className="block max-w-[320px] truncate">{requirement.title}</span>
                    </Badge>
                  </div>
                )}
                <p className="mt-2 whitespace-pre-wrap text-sm leading-5 text-[#4a5a5f]">
                  {feature.detail}
                </p>
              </Link>
            );
          })}
        </div>
      )}
    </>
  );
}
