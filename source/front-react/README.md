# Front React

Front React is the single-page application that powers the Pequeroku control panel. It offers the user dashboard, container orchestration tools, the in-browser IDE (file tree, Monaco editor, multiplexed terminals) and live metrics visualisations. This document explains every moving part—after reading it you should be able to run, extend and debug the front end without inspecting the source.

---

## 1. Technology Stack

- **Runtime:** React 19 with the new JSX runtime, strict mode, and React Router v7 for navigation.
- **Language & Tooling:** TypeScript 5.9 in “bundler” mode with path aliases and incremental builds.
- **Bundler:** Vite 7 using `@vitejs/plugin-react` (Fast Refresh) and `@tailwindcss/vite`.
- **Styling:** Tailwind CSS (class-based dark mode), vanilla CSS overrides in `src/index.css` and `src/styles/`.
- **Visualization:** Chart.js 4 and `react-chartjs-2` for metrics.
- **Editor/Terminal:** Monaco editor (`@monaco-editor/react`) and `@xterm/xterm` with the fit addon.
- **Linting & Formatting:** Biome (primary) plus ESLint for React-specific rules.
- **Testing:** Type-checked build artifacts under `tests/` compiled via `tsconfig.tests.json`; integrates with external runners.

---

## 2. Quick Start

> **Prerequisite:** Use Node.js 20.19+ (or 22.12+) so the bundled tooling and test runner (`node --test`) are available. `package.json` enforces this through the `engines` field.

```bash
cd front-react
npm install           # install dependencies
npm run dev           # start Vite dev server (defaults to http://localhost:5173)
```

Optional environment variables:

```bash
export FRONT_REACT_BASE=/app/     # serve the SPA from a sub-path
export VITE_USE_MOCKS=true        # run against in-memory mocks instead of the real backend
```

---

## 3. Scripts

| Command | Purpose | Details |
| --- | --- | --- |
| `npm run dev` | Development server | Vite with Fast Refresh; honours `FRONT_REACT_BASE`. |
| `npm run build` | Production build | Runs `npm run build:ts` (type-check emit) followed by `npm run build:vite`. |
| `npm run build:ts` | TypeScript project refs | Invokes `tsc -b` using the project references defined in `tsconfig.json`. |
| `npm run build:vite` | Bundle-only build | Runs `vite build` without re-emitting TypeScript. |
| `npm run preview` | Static preview | Serves the compiled `dist/` bundle. |
| `npm run build:tests` | Compile tests | Emits JS into `build-tests/` from `tsconfig.tests.json`. |
| `npm run test` | Compile + run tests | Calls `build:tests` then executes `node scripts/run-tests.mjs`; automatically sets `VITE_USE_MOCKS=true`. |
| `npm run biome:check` | Biome lint/format (dry run) | Generates the same diagnostics as CI. |
| `npm run biome:lint` | Lint only | Biome lint rules without formatting changes. |
| `npm run biome:format` | Format in-place | Applies Biome formatting. |
| `npm run biome:fix` | Fix lint + format | Writes both lint and format fixes. |
| `npm run biome:ci` | CI helper | One command that fails on lint/format issues (used in pipelines). |

---

## 4. Environment & Configuration

- **`FRONT_REACT_BASE`** (default `/`): controls Vite’s `base` option so assets and router links resolve under reverse proxies (e.g. `/app/`). Normalisation happens in `vite.config.ts` and is consumed by `src/lib/appBase.ts`.
- **`VITE_USE_MOCKS`** (default `false`): when `"true"`, services route requests to the in-memory mocks under `src/mocks`. This enables offline development and deterministic tests. The test runner (`npm run test`) forces this flag to `"true"` so suites never hit real services.
- Any variable prefixed with `VITE_` is exposed via `import.meta.env`.
- `src/lib/appBase.ts` inspects `import.meta.env.BASE_URL` and the current `window.location` to select the router basename, with a fallback to `/app/` when served behind the Django app.

---

## 5. High-Level Architecture

```text
┌──────────────────┐    HTTP/Fetch    ┌──────────────────────┐
│ React Components │ ───────────────► │ Django/VM Backends   │
└───┬──────────────┘                  └──────────────────────┘
    │    ▲
    │    │   WebSocket
    ▼    └───────────────────────────────┐
┌─────────────┐                           │
│ Services    │  WebSocket + mocks        │
│ (HTTP / WS) │─────────────────────► Backend WS endpoints
└────┬────────┘                           │
     │   ▲                                │
     ▼   │                                │
┌─────────────┐                       ┌─────────────┐
│ Event Bus   │◄── Components ───────►│ UI Stores   │
└─────────────┘                       └─────────────┘
```

### Boot Sequence

1. `src/main.tsx` resolves the app base (`resolveAppBase`) and mounts `App` inside a `BrowserRouter`.
2. `App.tsx` registers routes, listens for `auth:unauthorized` window events and renders two global surfaces:
   - `LoaderOverlay` reacting to `loaderStore` events.
   - `AlertStack` reacting to `alertStore` events.
3. Routes map to pages in `src/pages`:
   - `/login` → `Login` page.
   - `/` → `Dashboard` (protected).
   - `/ide` → `IDE` workspace (protected); expects `containerId` query param.
   - `/metrics` → `Metrics` view (protected); expects `container` query param.

### Route Protection

`ProtectedRoute` (see `src/components/ProtectedRoute.tsx`) gatekeeps protected routes:
- On mount it checks `VITE_USE_MOCKS`. If mocks are enabled, it renders immediately.
- Otherwise it invokes `fetchCurrentUser()` (`services/user.ts`).
- Failure triggers a redirect to `/login` using `react-router-dom` navigation.
- Any component can broadcast session expiry by dispatching `window.dispatchEvent(new CustomEvent("auth:unauthorized"))`. `App.tsx` listens and redirects.

---

## 6. Global UI Systems

- **Loader Overlay (`src/components/LoaderOverlay.tsx`)**
  - Subscribes to `loaderStore` (in `src/lib/loaderStore.ts`).
  - Each API request increments/decrements a counter; overlay disappears when counter hits zero.
- **Alert Stack (`src/components/AlertStack.tsx`)**
  - Listens to `alertStore` events (`src/lib/alertStore.ts`).
  - Supports push/dismiss actions; alerts render in `AlertStackView`.
  - `makeApi` automatically pushes alerts on HTTP errors.
- **Theme Management (`src/lib/theme.ts` + `ThemeToggle`)**
  - Persists theme in `localStorage`, syncs via `window` events, toggles Tailwind’s `dark` class on `<html>`.
  - UI toggled through `ThemeToggle` button present on the dashboard header.

---

## 7. Data Layer & State Management

### Event Bus

`src/lib/eventBus.ts` exposes a minimal pub/sub system used for alert and loader stores. Subscriptions return cleanup functions to avoid leaks. No global state library (Redux, Zustand) is used; local component state + custom hooks handle the rest.

### Stores

- `alertStore`: pushes alerts with `crypto.randomUUID()` IDs and broadcasts dismiss events.
- `loaderStore`: increments/decrements an `activeRequests` counter and broadcasts the current count.
- `themeManager`: manages theme, notifies subscribers and updates DOM classes.

### Signatures & Polling

`Dashboard.tsx` uses `signatureFrom` to generate JSON signatures of container lists and avoid overwriting UI state when the payload hasn’t changed (useful during polling).

---

## 8. HTTP Client & Services

### `makeApi` (`src/services/api.ts`)

Centralised fetch wrapper that:

- Accepts typed options: `noLoader`, `noAuthRedirect`, `noAuthAlert`, `suppressAuthRedirect`.
- Automatically merges headers and sets `Content-Type` unless a `FormData` body is used.
- Injects `X-CSRFToken` using `getCsrfToken()` (reads from cookies).
- Starts/stops the global loader unless `noLoader` is set.
- On 401/403:
  - Optionally dispatches `auth:unauthorized`.
  - Optionally redirects to `/login` (via `buildAppUrl`).
  - Optionally suppresses alerts.
- Parses JSON responses or returns raw text.

Usage pattern:

```ts
const api = makeApi("/api");
const containers = await api<Container[]>("/containers/", { method: "GET", noLoader: true });
```

### Domain Services

- **`services/user.ts`**
  - `fetchCurrentUser()` validates type guards for `UserInfo`.
  - Falls back to `mockFetchCurrentUser()` when mocks are enabled.
- **`services/containers.ts`**
  - CRUD over containers, power control, statistics polling.
  - Uses `AbortController` for cancellation and supports `suppressLoader`.
  - `fetchContainerStatistics` normalises CPU %, memory MiB and thread counts, converting timestamps to ISO strings.
- **`services/ide/actions.ts`**
  - Uploads files, downloads archives, polls template previews (with exponential backoff), fetches run configurations via WebSocket (`FileSystemWebService`).
  - Caches per-container `makeApi` instances for repeated calls.
- **`services/ide/FileSystemWebService.ts`**
  - Manages a dedicated WebSocket to `/ws/fs/:containerPk/`.
  - Maintains `pending` map keyed by `req_id` to resolve call promises.
  - Tracks remote file revisions (`revs`) and injects `prev_rev` into write actions.
  - Broadcasts file system events (create, update, delete) to listeners so the file tree stays in sync.
  - Handles reconnection with exponential backoff and fails pending promises when the socket closes.
- **`services/ide/TerminalWebService.ts`**
  - Wraps a WebSocket to `/ws/containers/:id/`.
  - Configures binary mode for raw terminal IO.
  - Exposes `send`, `onMessage`, `close`, `isConnected`.
  - Swapped for `MockTerminalWebService` when mocks are active.

---

## 9. Page-Level Behaviour

### Dashboard (`src/pages/Dashboard.tsx`)

- Fetches user info and containers on mount; polls containers every 5 seconds.
- Stores ToS warning state in `sessionStorage` per non-superuser session.
- Exposes actions: create, delete, power on/off containers.
- Handles abortable fetches to avoid race conditions when navigating away.
- Renders metrics and console modals by controlling component state.
- Uses `CreateContainerModal`, `ThemeToggle`, `Modal`, and `Button` components for UI affordances.

### IDE (`src/pages/IDE.tsx`)

Core workspace combining multiple subsystems:

- **File Tree (`useFileTree`)**
  - Uses `FileSystemWebService` to read directories, expand folders lazily, rename/delete nodes and react to broadcast updates.
  - Remembers expanded state and last opened file per container (`localStorage` keys `ide:{id}:...`).
  - Provides search functionality (`FileSystemWebService.search`) with glob include/exclude support.
- **Editor (`useEditor`)**
  - Wraps Monaco editor through `Editor` component.
  - Tracks open tabs, debounce-saves with `saveActiveFile`, and handles external updates (e.g. git checkout) by updating tab content when revisions change.
  - Determines language via `detectLanguageFromPath`.
- **Terminals (`useTerminals`)**
  - Manages multiple Xterm instances backed by `TerminalWebService`. Supports session discovery and clearing.
- **Auxiliary Panels**
  - `UploadModal`: uses `uploadFile` (FormData) for dragging files.
  - `TemplatesModal`: loads remote templates, applies them through `applyTemplate`.
  - `GithubModal`: constructs shell commands (via `buildCloneCommand`) for repo cloning; postpones polling with `ACTION_DELAYS.cloneRepoWaitMs`.
  - `AiAssistantPanel`: reserved UI panel for AI assistance (integrates with mocks today).
- **Preview Polling**
  - `pollPreview` hits `/api/containers/:id/curl/:port/:path` repeatedly until a non-empty HTML payload is returned.
- **Responsive Behaviour**
  - `useIsMobile` toggles sidebars and console panels depending on screen width; state persisted across reloads.
- **Theme Integration**
  - Editor reacts to `themeManager` updates to switch Monaco theme between light/dark.

If the `containerId` query param is missing or invalid, `MissingContainer` renders guidance.

### Metrics (`src/pages/Metrics.tsx`)

- Expects `?container=<id>` query parameter.
- Polls `fetchContainerStatistics` at intervals defined in `constants.METRICS.pollMs` (defaults to 1000 ms) with cancellation on tab blur/visibility change.
- Maintains a sliding window capped at `METRICS.maxPoints`.
- Displays CPU %, memory usage (MiB) and threads using Chart.js line charts, custom tooltip formatting and responsive layout.
- Exposes `showHeader` query flag to embed the chart outside the full chrome (e.g. in iframes).

### Login (`src/pages/Login.tsx`)

- Minimal form; relies on backend redirection. When mocks are enabled, successful login is simulated.

---

## 10. Styling & Theming

- Tailwind is configured in `tailwind.config.js` with `darkMode: "class"` to allow manual theme selection.
- `src/index.css` defines global resets, font faces and base colours.
- `src/styles/theme-overrides.css` tweaks Monaco, terminals and layout specifics that Tailwind cannot express.
- Components use Tailwind utility classes; heavier layouts still rely on conventional CSS within the same files.

---

## 11. Directory Reference

```
front-react/
├─ public/                     # Static assets copied verbatim during build
├─ src/
│  ├─ components/              # Reusable UI widgets (modals, buttons, alerts)
│  ├─ components/ide/          # IDE-specific panels (editor shell, tabs, AI)
│  ├─ components/modals/       # Modal bodies rendered inside <Modal />
│  ├─ hooks/                   # Custom hooks powering file tree, terminals, editor
│  ├─ lib/                     # Infrastructure utilities (event bus, stores, theme)
│  ├─ mocks/                   # Mock data/services used when VITE_USE_MOCKS=true
│  ├─ pages/                   # Top-level route components
│  ├─ services/                # HTTP and WebSocket service layers
│  ├─ styles/                  # Additional global CSS overrides
│  ├─ types/                   # Shared TypeScript interfaces and type guards
│  ├─ App.tsx                  # Router setup, global listeners
│  ├─ main.tsx                 # Entrypoint rendering StrictMode + Router
│  ├─ config.ts                # Env flag helper for USE_MOCKS
│  └─ constants.ts             # Tunables for polling, delays, WS timeouts
├─ tests/                      # Test sources compiled with tsconfig.tests.json
├─ build-tests/                # Generated JS artifacts (ignored from VCS)
├─ dist/                       # Production build output (generated)
├─ vite.config.ts              # Build tooling configuration
├─ tailwind.config.js          # Tailwind setup
├─ biome.json                  # Biome configuration
└─ eslint.config.js            # ESLint configuration
```

Refer to `front-react/files.md` for an exhaustive file list.

---

## 12. TypeScript & Build Configuration

- `tsconfig.app.json` targets ES2022, uses the bundler module resolution, enables strict mode and path alias `@/*` → `src/*`.
- `tsconfig.tests.json` extends app config but enables emit (`noEmit: false`) and writes compiled tests to `build-tests/`.
- `tsconfig.json` (root) orchestrates project references for the build pipeline.
- `vite.config.ts`
  - Normalises `FRONT_REACT_BASE`.
  - Registers React & Tailwind plugins.
  - Defines alias `@` → `./src`.
  - Configures the project for SPA deployment under sub-paths.

---

## 13. Mocking & Offline Development

- `config.ts` exposes `USE_MOCKS`, enabling or bypassing mocks at runtime.
- `src/mocks/dashboard.ts`, `src/mocks/ide.ts`, `src/mocks/terminal.ts` implement deterministic responses mimicking backend contracts.
- Services check `USE_MOCKS` before invoking network calls, ensuring identical TypeScript signatures regardless of backend availability.
- Tests rely heavily on mocks to assert behaviour without spinning up real services.

---

## 14. Testing Strategy

- Tests live under `tests/` and cover:
  - Store behaviour (`alertStore`, `loaderStore`).
  - Service edge cases (API wrappers, filesystem/terminal mocks).
  - Hooks (`useEditor`, `useFileTree`, `useTerminals`).
  - Component rendering (buttons, alert stacks, loader overlay).
- `npm run build:tests` compiles TypeScript tests to JavaScript without running them (helpful when another runner needs the emitted files).
- `npm run test` runs the end-to-end pipeline: it compiles via `build:tests`, then invokes `scripts/run-tests.mjs`, which ensures `node:test` is available, forces `VITE_USE_MOCKS=true`, and executes the compiled suite with the built-in runner.
- If you integrate Vitest/Jest or another harness, reuse the artifacts in `build-tests/` or mirror the environment configuration (`VITE_USE_MOCKS=true`) to avoid hitting real services.

---

## 15. Development Workflow

1. Export necessary environment variables (`FRONT_REACT_BASE`, `VITE_USE_MOCKS`).
2. Run `npm run dev` and navigate to the reported URL. React Router automatically handles deep links based on `resolveAppBase`.
3. Make changes; Hot Module Reload updates the UI instantly.
4. Validate with `npm run lint` and `npm run build` before committing.
5. If integrating with backends, ensure the SPA runs on the same domain for CSRF cookies to apply.

---

## 16. Deployment Notes

- `npm run build` outputs the SPA into `dist/`; deploy the contents behind an HTTP server capable of fallback routing (i.e. serve `index.html` for unknown routes).
- When hosting under `/app/` alongside the Django backend:
  - Configure the reverse proxy to rewrite requests to serve the SPA at that path.
  - Keep `FRONT_REACT_BASE`, `DEFAULT_APP_BASE` (`src/lib/appBase.ts`) and proxy routes in sync.
  - Expose WebSocket endpoints (`/ws/fs/:id/`, `/ws/containers/:id/`) via the proxy with proper TLS termination.
- Ensure backend CSRF cookie domain matches the SPA origin to allow authenticated API calls.

---

## 17. Extensibility Guidelines

- **Adding a new page**
  1. Create a component in `src/pages/`.
  2. Add a `<Route>` in `App.tsx`.
  3. If the page requires auth, wrap it with `ProtectedRoute`.
  4. Use `buildAppUrl` to generate internal links that honour the base path.
- **Adding a service**
  - Place HTTP services in `src/services`.
  - Reuse `makeApi` to guarantee consistent auth/error handling.
  - If the service needs WebSockets, model it after `FileSystemWebService` with reconnection/backoff.
- **Shared state**
  - Prefer custom hooks with `useState`/`useReducer` for local needs.
  - Use `EventBus` for broadcast-style events affecting multiple distant components.
- **IDE enhancements**
  - Follow existing patterns in `useEditor` / `useFileTree` to keep optimistic updates and revision control intact.
  - Extend `langMap` when supporting new file extensions to ensure Monaco highlights correctly.

---

## 18. Troubleshooting

- **Blank screen after login**
  - Check the console for 401/403 errors.
  - Ensure the backend sets `csrftoken` cookie and that `VITE_USE_MOCKS` is disabled when hitting real APIs.
- **Stuck loader overlay**
  - Inspect network tab for hanging requests; `loaderStore.stop()` is only called when promises settle.
- **Static assets served from wrong path**
  - Verify `FRONT_REACT_BASE` matches the deployment path.
  - Re-run `npm run build` after changing the base.
- **WebSocket disconnects**
  - Confirm proxy forwards WS upgrades.
  - File system service will retry with exponential backoff up to 5 seconds; check browser logs (`FS WS connected/error`).
- **Metrics view shows “Unable to fetch metrics”**
  - Ensure `container` query param is numeric.
  - Confirm `/api/containers/:id/statistics/` is reachable and returns JSON with `cpu_percent`, `rss_*`, `num_threads`.
- **Theme toggling not working**
  - Confirm `<html>` element receives `.dark`/`.light` classes.
  - Clear `localStorage` key `pequeroku:theme` to reset.
