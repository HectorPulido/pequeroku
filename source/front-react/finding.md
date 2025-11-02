# Code Review Findings – `front-react`

- **1. Medium · `src/components/ide/TerminalPanel.tsx:467-490`** ✅ SOLVED
  The tab header renders a `<button>` that wraps two nested `<button>` elements (label + close icon). Nested interactive controls are invalid HTML; in Chromium you end up triggering the parent `onClick` (tab activation) even when you try to press the close button, while Safari simply ignores the inner buttons. The result is that closing a tab either fails or switches focus to it before the close handler runs. Replace the outer wrapper with a neutral element (`div`, `span`) or move the close button outside so each control is its own button.

- **2. Medium · `src/services/ide/TerminalWebService.ts:4-58`** ✅ SOLVED
  The terminal WebSocket wrapper never retries or recreates the connection after `onclose`. Network hiccups or container restarts leave the tab permanently disconnected and `useTerminals` has no way to recover besides forcing the user to open a brand-new terminal. Mirror the filesystem service by scheduling reconnect attempts (or surfacing a failure so the UI can respawn the session).

- **3. Low · `package.json:7-18`** ✅ SOLVED
  The `npm run test` script only recompiles the TypeScript test sources (`tsc -p tsconfig.tests.json`) but never executes them, so CI and local runs can report success with zero coverage. Consider wiring this script to `node --test build-tests/**/*.js` (or vitest/jest) so the suite actually runs.

- **4. High** ·
  El sistema es de todo menos responsive, no puedo creer que la version en @front/app sea tan jodidamente superior todavia MIERDA

- **5. High** · ✅ SOLVED
  El light theme esta simplemente roto, algunos botones no cambian de color, hay texto blanco sobre fondo blanco, en el ide ni monaco ni xterm cambian de color, etc.

- **6. High** ·
  El navegador deberia estar en un panel a la derecha, como la IA, pero solo debe haber uno de los dos a la vez, y tambien debe ser resizable
