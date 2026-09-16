# T20-control-panel — API Wiring Handoff

## Acceptance checklist

- [x] Run `codegen` from `api-spec` to generate Orval React Query hooks.
- [x] Wire `Dashboard` component with `useGetBriefing`, `useGetSection`, `useSetFocus`, `useAddEntry`, `useUpdateEntry`.
- [x] Wire `Requirements` component with `useListRequirements`, `useGetRequirementContract`, `useSyncRequirements`.
- [x] Wire `CodeIndex` component with `useGetIndexStatus`, `useReindex`.
- [x] Wire `CodeMap` component with `useGetCodeMap`, `useSearchCode`, `useGetSource`.
- [x] Support `x-pcs-admin-token` headers via `custom-fetch.ts` injection.
- [x] Build frontend without TypeScript errors.
- [x] Start backend and verify healthy integration.

## Handoff

Completed the frontend to backend integration for `pcs-control-panel`. 

1. **API Client Codegen**: Generated Orval hooks via `@workspace/api-spec`. Adjusted TypeScript configurations (added `DOM.Iterable` to `tsconfig.json` and fixed namespace collisions in Zod exports) to allow successful compilation of the client libraries.
2. **API Injection**: Modified `custom-fetch.ts` in `api-client-react` to inject `x-pcs-admin-token` into fetch request headers.
3. **Component Wiring**:
   - `Dashboard`: Wired to fetch real briefing and sections, and implemented mutate callbacks (`useAddEntry`, `useUpdateEntry`, `useSetFocus`) with automatic query invalidation.
   - `Requirements`: Integrated `useListRequirements` for the overview and lazily fetched individual contract states via `useGetRequirementContract` in `RequirementRow`. Wired `useSyncRequirements` for the manual sync trigger.
   - `CodeIndex`: Connected to `useGetIndexStatus` for live index stats and `useReindex` for triggering full and incremental rebuilds.
   - `CodeMap`: Rewrote the `TreeNode` component to lazily expand the graph via `useGetCodeMap`. Integrated `useSearchCode` for searching files and `useGetSource` to display real source code snippets in the UI.
4. **Validation**: Built the `api-client-react` library successfully. Ran `pnpm -w run typecheck` across the frontend workspace, passing with zero errors. Started the local PostgreSQL and backend services via `docker compose` to verify network health and integration end-to-end.

The frontend is now fully decoupled from mock data and relies strictly on the PCS REST API.
