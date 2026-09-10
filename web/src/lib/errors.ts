import { ApiError } from "../api/client";

/** Human-readable text for anything thrown by the query/mutation layer. */
export function errorText(error: unknown): string | null {
  if (error === null || error === undefined) {
    return null;
  }
  if (error instanceof ApiError) {
    if (error.available !== undefined) {
      return `${error.message} (known projects: ${error.available.join(", ") || "none"})`;
    }
    return error.message;
  }
  return error instanceof Error ? error.message : "Request failed";
}
