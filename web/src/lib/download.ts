/**
 * Trigger a browser file download from an in-memory string (T31).
 *
 * Builds a Blob, mounts a temporary `<a download>`, clicks it, then revokes
 * the object URL. Callers supply the server-provided filename and media type.
 */
export function downloadFile(
  filename: string,
  content: string,
  mediaType: string,
): void {
  const blob = new Blob([content], { type: mediaType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
