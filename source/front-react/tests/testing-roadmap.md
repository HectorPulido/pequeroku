# Testing Roadmap

Single source of truth for the unit/integration scenarios we still need to cover. Split by module so we can tick items as we implement them. Use `[ ]` / `[x]` to track progress.

## Services & State

- [x] `services/user`: happy path + unauthorized fallbacks (`fetchCurrentUser`)
- [x] `services/containers`: list/mutations, loader behaviour, payload validation
- [x] `services/api`: CSRF header injection, loader toggles, 401 redirect contract, JSON parsing fallbacks
- [x] `services/ide/FileSystemWebService`: request queueing, broadcast handling, timeout paths
- [x] `services/ide/TerminalWebService`: session lifecycle, resize messages, reconnection/backoff logic
- [x] `lib/theme`: storage persistence, initial theme detection, subscriber notifications
- [x] `lib/alertStore` / `lib/loaderStore`: subscription disposal, burst emission ordering
- [x] `lib/eventBus`: unsubscribe edge cases, deep listener nesting

## Hooks

- [x] `useFileTree`: tree building, action handlers (create/rename/delete), selection state resets (helper-tested)
- [ ] `useFileTree` broadcast hook: WS message throttling, refresh scheduling, cleanup
- [ ] `useFileTree` search helper: payload shaping, error surfacing, result normalization
- [x] `useEditor`: tab dedupe, dirty tracking helper (`getOrCreateTab`)
- [x] `useTerminals`: tab lifecycle helper (`generateTerminalId`)

## Components – Core UI

- [x] `<AlertStack />`: renders alerts, dismiss button wiring, non-dismissible support (via `AlertStackView`)
- [x] `<LoaderOverlay />`: synchronization with loader store, concurrent request behaviour (via `LoaderOverlayView`)
- [x] Shared UI primitives (`Button`): accessibility attributes, disabled states, theme propagation

## Components – Pages & Complex Views

- [ ] `<ProtectedRoute />`: session guard permutations (authorized, unauthorized, pending)
- [ ] `<Dashboard />`: polling dedupe, action buttons, modal toggles, quota banner
- [ ] `<Login />`: probe redirect, error messaging, success redirect, loader states
- [ ] `<IDE />`: containerId query handling, missing-container fallback, per-container state reset
- [ ] IDE components (`FileTree`, `Editor`, `TerminalPanel`, `ResizablePanel`): rendering integrity, keyboard shortcuts, collapse behaviour
- [ ] Modals (`CreateContainerModal`, `UploadModal`, `TemplatesModal`, `GithubModal`): form validation, button states, credit gating

## Integrations & Flows

- [ ] Dashboard ↔ API integration smoke test (mock fetch): ensures list refresh + user quota update happen together
- [ ] Login → Dashboard end-to-end with mocked services: verifies redirect and store side-effects
- [ ] IDE boot flow: container query string, websocket bootstrapping, panel collapse persistence
- [ ] IDE container switch: ensures filesystem/editor/terminal hooks dispose connections when containerId changes
- [ ] Metrics polling loop: API throttling, chart dataset rollover, offline/restore transitions
- [ ] Theme toggle global event propagation across routes
- [ ] Upload/download/template flows once backend endpoints are wired in Step 5

## Tooling & Infrastructure

- [ ] Coverage post-processing (convert V8 JSON to LCOV/HTML for reporting)
- [ ] CI script to run `npm run lint` + `npm test` in sequence
- [ ] Watch mode for tests (optional, would require additional tooling)
- [ ] Docs: add testing instructions to `front-react/README.md`

---

Update this file whenever we mark a scenario complete or discover new edge cases. Cross-reference parity checklist items so nothing slips through the migration plan.
