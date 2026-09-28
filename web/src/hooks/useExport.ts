import {
  useMutation,
  type UseMutationResult,
} from "@tanstack/react-query";

import {
  exportProjectContext,
  type ExportFormat,
  type ProjectContextExport,
} from "../api/client";
import { downloadFile } from "../lib/download";

/**
 * Fetch a full project-context export and save it via {@link downloadFile}.
 *
 * Errors surface on the mutation result for the Callout on DashboardView.
 */
export function useExportProjectContext(
  project: string,
): UseMutationResult<ProjectContextExport, Error, ExportFormat> {
  return useMutation({
    mutationFn: async (format: ExportFormat) => {
      const envelope = await exportProjectContext(project, format);
      downloadFile(envelope.filename, envelope.content, envelope.media_type);
      return envelope;
    },
  });
}
