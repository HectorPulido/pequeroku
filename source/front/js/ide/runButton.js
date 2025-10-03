/**
 * Run button controller
 *
 * Extracts the "Run" button logic from main.js. It:
 * - Loads run configuration (run command and optional url) from /app/config.json
 * - Enables/disables the run button accordingly
 * - On click, saves the current file, executes the run command via provided sender, and optionally opens a URL in a new tab
 *
 * Usage:
 *   import { setupRunButton } from "./runButton.js";
 *   import { loadRunConfig } from "./runConfig.js";
 *
 *   const runCtrl = setupRunButton({
 *     buttonEl: document.getElementById("run-code"),
 *     loadRunConfig: () => loadRunConfig(apiReadFileWrapper), // must return { run, url } or string
 *     saveCurrentFile: saveCurrentFile, // async () => void
 *     wsSend: (payload) => ws.send(payload), // function that sends payload to backend
 *     autoOpenUrl: true, // optional
 *   });
 *
 *   // When needed (e.g., after saving /app/config.json):
 *   await runCtrl.hydrate(); // refreshes command and url and button state
 */

import { notifyAlert } from "../core/alerts.js";
import { ideStore } from "../core/store.js";

/**
 * Normalize result of loadRunConfig to { run, url }
 * Supports both string (legacy) and object shapes.
 * @param {any} cfg
 * @returns {{ run: string|null, url: string|null }}
 */
function normalizeRunConfig(cfg) {
	if (!cfg) return { run: null, url: null };
	if (typeof cfg === "string") {
		const trimmed = cfg.trim();
		return { run: trimmed || null, url: null };
	}
	if (typeof cfg === "object") {
		const run =
			typeof cfg.run === "string" && cfg.run.trim() ? cfg.run.trim() : null;
		const url =
			typeof cfg.url === "string" && cfg.url.trim() ? cfg.url.trim() : null;
		return { run, url };
	}
	return { run: null, url: null };
}

/**
 * @typedef {Object} SetupRunButtonOptions
 * @property {HTMLElement|null} buttonEl - The Run button element.
 * @property {() => Promise<any>} loadRunConfig - Async function that loads config from /app/config.json and returns either a string 'run' or an object with { run, url }.
 * @property {() => Promise<void>} saveCurrentFile - Async function to save the current file.
 * @property {(payload: any) => void} wsSend - Function to send payloads (e.g., to a WS).
 * @property {boolean} [autoOpenUrl=true] - If true, will open the configured URL after running the command.
 */

/**
 * Setup the Run button behavior.
 * @param {SetupRunButtonOptions} opts
 * @returns {{ hydrate: () => Promise<void>, setSender: (fn: (payload:any) => void) => void, getRun: () => string|null, getUrl: () => string|null, dispose: () => void }}
 */
export function setupRunButton({
	buttonEl,
	loadRunConfig,
	saveCurrentFile,
	wsSend,
	autoOpenUrl = true,
}) {
	/** @type {string|null} */
	let runCommand = null;
	/** @type {string|null} */
	let runUrl = null;
	/** @type {(payload:any)=>void} */
	let sender = typeof wsSend === "function" ? wsSend : () => {};

	function setDisabled(disabled) {
		try {
			if (buttonEl) buttonEl.disabled = !!disabled;
		} catch {
			// ignore
		}
	}

	/**
	 * Refresh run config from /app/config.json and update UI
	 */
	async function hydrate() {
		try {
			const raw = await loadRunConfig();
			const { run, url } = normalizeRunConfig(raw);
			runCommand = run;
			runUrl = url;
			setDisabled(!runCommand);
			// Sync with store for other consumers
			try {
				ideStore.actions.setRunCommand(runCommand);
			} catch {
				// ignore store errors
			}
		} catch {
			runCommand = null;
			runUrl = null;
			setDisabled(true);
		}
	}

	async function onClick() {
		try {
			await saveCurrentFile();
		} catch {
			// saving error is already notified upstream; proceed cautiously
		}

		if (runCommand) {
			try {
				sender({ data: runCommand });
			} catch (e) {
				notifyAlert(
					(e && typeof e === "object" && "message" in e && e.message) ||
						"Failed to send run command",
					"error",
				);
				return;
			}
			if (autoOpenUrl && runUrl) {
				try {
					// Open in a new tab without giving it access to window.opener
					window.open(runUrl, "_blank", "noopener,noreferrer");
				} catch {
					// ignore open failures (e.g., blocked by browser)
				}
			}
		} else {
			notifyAlert(
				"There is no 'run' command in config.json. The button is disabled.",
				"warning",
			);
		}
	}

	// Wire click
	if (buttonEl) {
		buttonEl.addEventListener("click", onClick);
	}

	// Initial state unknown => keep enabled state conservative
	setDisabled(true);

	// Public API
	return {
		hydrate,
		setSender(fn) {
			if (typeof fn === "function") sender = fn;
		},
		getRun() {
			return runCommand;
		},
		getUrl() {
			return runUrl;
		},
		dispose() {
			try {
				if (buttonEl) buttonEl.removeEventListener("click", onClick);
			} catch {
				// ignore
			}
		},
	};
}
