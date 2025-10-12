/**
 * Run and Mini-Browser controllers (curl-based)
 * Usage:
 *   import { setupRunButton } from "./runButton.js";
 *   import { loadRunConfig } from "./runConfig.js";
 *
 *   const runCtrl = setupRunButton({
 *     runButtonEl: document.getElementById("run-code"),     // Run button (stays visible)
 *     browserButtonEl: document.getElementById("open-browser"), // Browser button (hidden if no port)
 *     loadRunConfig: () => loadRunConfig(apiReadFileWrapper),
 *     saveCurrentFile: saveCurrentFile,                     // async () => void
 *     wsSend: (payload) => ws.send(payload),                // optional: send run command to backend
 *     containerId: 5,                                       // default 5
 *     defaultPath: "index.html",                            // default page to probe when #preview-url is empty
 *   });
 *
 *   // When needed (e.g., after saving /app/config.json):
 *   await runCtrl.hydrate(); // refreshes command/port and buttons state
 */

import { notifyAlert } from "../core/alerts.js";
import { $ } from "../core/dom.js";
import { ideStore } from "../core/store.js";

/**
 * Normalize result of loadRunConfig to { run, port }
 * Supports both string (legacy) and object shapes.
 * @param {any} cfg
 * @returns {{ run: string|null, port: number|null }}
 */
function normalizeRunConfig(cfg) {
	if (!cfg) return { run: null, port: null };
	if (typeof cfg === "string") {
		const trimmed = cfg.trim();
		return { run: trimmed || null, port: null };
	}
	if (typeof cfg === "object") {
		const run =
			typeof cfg.run === "string" && cfg.run.trim() ? cfg.run.trim() : null;
		let port = null;
		if (cfg.port != null) {
			const p = parseInt(String(cfg.port), 10);
			if (!Number.isNaN(p) && p > 0 && p < 65536) port = p;
		}
		return { run, port };
	}
	return { run: null, port: null };
}

/**
 * @typedef {Object} SetupRunButtonOptions
 * @property {HTMLElement|null} [runButtonEl] - Button to trigger the run command (visible regardless of port).
 * @property {HTMLElement|null} [browserButtonEl] - Button to open the mini-browser (hidden when no valid port).
 * @property {() => Promise<any>} loadRunConfig - Loads config from /app/config.json (string 'run' or { run, port }).
 * @property {() => Promise<void>} [saveCurrentFile] - Async function to save the current file.
 * @property {(payload: any) => void} [wsSend] - Optional function to send payloads (e.g., WS) to run commands.
 * @property {number} [containerId=5] - Container id for the curl endpoint.
 * @property {string} [defaultPath="index.html"] - Default path to probe when #preview-url is empty.
 */

/**
 * Setup decoupled Run and Browser buttons with curl-based mini-browser probing.
 * @param {SetupRunButtonOptions} opts
 * @returns {{ hydrate: () => Promise<void>, setSender: (fn: (payload:any) => void) => void, getRun: () => string|null, getPort: () => number|null, dispose: () => void }}
 */
export function setupRunButton({
	runButtonEl,
	browserButtonEl,
	loadRunConfig,
	saveCurrentFile,
	wsSend,
	containerId,
	defaultPath = "",
}) {
	/** @type {string|null} */
	let runCommand = null;
	/** @type {number|null} */
	let runPort = null;
	/** @type {(payload:any)=>void} */
	let sender = typeof wsSend === "function" ? wsSend : () => {};

	function setRunDisabled(disabled) {
		try {
			if (runButtonEl) runButtonEl.disabled = !!disabled;
		} catch {
			// ignore
		}
	}

	function setBrowserVisible(visible) {
		try {
			if (!browserButtonEl) return;
			browserButtonEl.style.display = visible ? "" : "none";
		} catch {
			// ignore
		}
	}

	/**
	 * Refresh run config from /app/config.json and update UI state:
	 * - Disable RUN button if no run command
	 * - Show BROWSER button only if a valid port exists
	 */
	async function hydrate() {
		try {
			const raw = await loadRunConfig();
			const { run, port } = normalizeRunConfig(raw);
			runCommand = run;
			runPort = typeof port === "number" ? port : null;
			setRunDisabled(!runCommand);
			setBrowserVisible(!!runPort);
			// Sync with store for other consumers
			try {
				ideStore.actions.setRunCommand(runCommand);
			} catch {
				// ignore store errors
			}
		} catch {
			runCommand = null;
			runPort = null;
			setRunDisabled(true);
			setBrowserVisible(false);
		}
	}

	/**
	 * Builds the curl endpoint URL for a given port and path.
	 * The path is URL-encoded as one segment so "hola/mundo" -> "hola%2Fmundo".
	 * Always ensures a trailing slash at the end as per the examples.
	 * Adds a cache-busting query param.
	 */
	function buildCurlUrl(port, rawPath) {
		const sanitized = (rawPath || "").replace(/^\//, ""); // drop leading slash if present
		const encoded = sanitized ? encodeURIComponent(sanitized) : "";
		const base = `/api/containers/${containerId}/curl/${port}`;
		const pathPart = encoded ? `/${encoded}/` : `/`;
		const url = `${base}${pathPart}`;
		const u = new URL(url, window.location.href);
		u.searchParams.set("_cb", String(Date.now()));
		return u.toString();
	}

	/**
	 * Polls the curl endpoint until it returns 200, then returns { url, html }.
	 * Otherwise returns null after timeout.
	 * @param {number} port
	 * @param {string} rawPath
	 * @param {number} attempts
	 * @param {number} delayMs
	 * @returns {Promise<{url: string, html: string} | null>}
	 */
	async function pollUntil200(port, rawPath, attempts = 10, delayMs = 5000) {
		await new Promise((r) => setTimeout(r, delayMs));
		for (let i = 0; i < attempts; i++) {
			const url = buildCurlUrl(port, rawPath);
			try {
				const res = await fetch(url, { method: "GET", noLoader: true });
				if (res.status !== 200) {
					continue;
				}

				const html = await res.text();

				if (html.length < 10) {
					continue;
				}

				return { url, html };
			} catch {}
			await new Promise((r) => setTimeout(r, delayMs));
		}
		return null;
	}

	async function onRunClick() {
		// Save current file (best effort)
		try {
			if (typeof saveCurrentFile === "function") {
				await saveCurrentFile();
			}
		} catch {
			// saving error is already notified upstream; continue
		}

		// Send run command if available
		if (runCommand) {
			try {
				sender({ data: `${runCommand}\n` });
			} catch (e) {
				notifyAlert(
					(e && typeof e === "object" && "message" in e && e.message) ||
						"Failed to send run command",
					"error",
				);
			}
		} else {
			notifyAlert("There is no 'run' command in config.json.", "warning");
		}

		await onBrowserClick();
	}

	async function onBrowserClick() {
		if (!runPort) {
			notifyAlert(
				"There is no 'port' configured in config.json. The browser button is only shown when a port exists.",
				"warning",
			);
			return;
		}

		// Path to request: from #preview-url or fallback to defaultPath
		const urlInput = $("#preview-url");
		let rawPath = "";
		try {
			rawPath = (urlInput?.value || "").trim();
		} catch {
			rawPath = "";
		}
		if (!rawPath) rawPath = defaultPath || "";

		// Fetch HTML until the endpoint responds 200
		const result = await pollUntil200(runPort, rawPath);
		if (!result) {
			notifyAlert(
				`Mini-browser could not be opened: the endpoint did not return 200 for port ${runPort} and path "${rawPath}".`,
				"warning",
			);
			return;
		}
		const previewUrl = result.url;

		// Open mini-browser
		try {
			const iframe = $("#preview-iframe");
			const box = $("#preview-box");
			const urlInput = $("#preview-url");
			if (box?.classList.contains("hidden")) box.classList.remove("hidden");
			if (urlInput) urlInput.value = rawPath; // keep the raw path, not the encoded segment
			iframe.src = previewUrl;
			urlInput.value = previewUrl;
		} catch {}
	}

	// Wire clicks
	if (runButtonEl) {
		runButtonEl.addEventListener("click", onRunClick);
	}
	if (browserButtonEl) {
		browserButtonEl.addEventListener("click", onBrowserClick);
	}

	// Initial state:
	// - Run button: disabled until hydration determines there's a run command
	// - Browser button: hidden until hydration determines there's a valid port
	setRunDisabled(true);
	setBrowserVisible(false);

	// Public API
	return {
		hydrate,
		setSender(fn) {
			if (typeof fn === "function") sender = fn;
		},
		getRun() {
			return runCommand;
		},
		getPort() {
			return runPort;
		},
		dispose() {
			try {
				if (runButtonEl) runButtonEl.removeEventListener("click", onRunClick);
			} catch {}
			try {
				if (browserButtonEl)
					browserButtonEl.removeEventListener("click", onBrowserClick);
			} catch {
				// ignore
			}
		},
	};
}
