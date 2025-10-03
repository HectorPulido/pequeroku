/**
 * Run button controller
 *
 * Extracts the "Run" button logic from main.js. It:
 * - Loads run configuration (run command and optional url and port) from /app/config.json
 * - Enables/disables the run button accordingly
 * - On click, saves the current file, executes the run command via provided sender, and optionally opens a URL in a new tab
 *
 * Usage:
 *   import { setupRunButton } from "./runButton.js";
 *   import { loadRunConfig } from "./runConfig.js";
 *
 *   const runCtrl = setupRunButton({
 *     buttonEl: document.getElementById("run-code"),
 *     loadRunConfig: () => loadRunConfig(apiReadFileWrapper), // must return { run, url, port } or string
 *     saveCurrentFile: saveCurrentFile, // async () => void
 *     wsSend: (payload) => ws.send(payload), // function that sends payload to backend
 *     autoOpenUrl: true, // optional
 *     readFileApi: apiReadFileWrapper, // optional: FS socket reader for polling
 *   });
 *
 *   // When needed (e.g., after saving /app/config.json):
 *   await runCtrl.hydrate(); // refreshes command and url and button state
 */

import { notifyAlert } from "../core/alerts.js";
import { $ } from "../core/dom.js";
import { ideStore } from "../core/store.js";

/**
 * Normalize result of loadRunConfig to { run, url, port }
 * Supports both string (legacy) and object shapes.
 * @param {any} cfg
 * @returns {{ run: string|null, url: string|null, port: number|null }}
 */
function normalizeRunConfig(cfg) {
	if (!cfg) return { run: null, url: null, port: null };
	if (typeof cfg === "string") {
		const trimmed = cfg.trim();
		return { run: trimmed || null, url: null, port: null };
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
 * @property {HTMLElement|null} buttonEl - The Run button element.
 * @property {() => Promise<any>} loadRunConfig - Async function that loads config from /app/config.json and returns either a string 'run' or an object with { run, url, port }.
 * @property {() => Promise<void>} saveCurrentFile - Async function to save the current file.
 * @property {(payload: any) => void} wsSend - Function to send payloads (e.g., to a WS).
 * @property {boolean} [autoOpenUrl=true] - If true, will open the configured URL after running the command.
 * @property {(url: string | URL) => Promise<{ content: string }>} [readFileApi] - Optional file reader via FS socket for polling tunnel URL.
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
	readFileApi,
}) {
	/** @type {string|null} */
	let runCommand = null;
	/** @type {number|null} */
	let runPort = null;
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
			const { run, port } = normalizeRunConfig(raw);
			runCommand = run;
			runPort = typeof port === "number" ? port : null;
			setDisabled(!runCommand);
			// Sync with store for other consumers
			try {
				ideStore.actions.setRunCommand(runCommand);
			} catch {
				// ignore store errors
			}
		} catch {
			runCommand = null;
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
			if (autoOpenUrl) {
				const tunnel_url = "/app/tunnel_url.txt";
				// Helper to build cloudflared command using configured port
				const buildCloudflaredCommand = (port) => {
					const url = `http://localhost:${port}`;
					return `URL=${url} URL_FILE=${tunnel_url} LOG_FILE=/tmp/cloudflared.log; pkill -f "cloudflared tunnel --url $URL" >/dev/null 2>&1 || true; : >"$LOG_FILE"; nohup cloudflared tunnel --url "$URL" >>"$LOG_FILE" 2>&1 & tail -f -n +1 "$LOG_FILE" | grep -m1 -oE 'https://[A-Za-z0-9.-]+\\.trycloudflare\\.com' | tee "$URL_FILE"`;
				};

				// Read via FS socket API if provided
				const readServerFile = async (path) => {
					try {
						if (typeof readFileApi !== "function") return null;
						const { content } = await readFileApi(
							`/read_file/?path=${encodeURIComponent(path)}`,
						);
						return typeof content === "string" ? content : null;
					} catch {
						return null;
					}
				};

				const pollTunnelUrl = async () => {
					await new Promise((r) => setTimeout(r, 5000));
					for (let i = 0; i < 100; i++) {
						await new Promise((r) => setTimeout(r, 1000));
						const content = await readServerFile(tunnel_url);
						const v = (content || "").trim();
						if (v) {
							await new Promise((r) => setTimeout(r, 1000));
							return v;
						}
					}
					return null;
				};

				if (runPort) {
					// Start cloudflared and poll for generated public URL
					try {
						const cmd = buildCloudflaredCommand(runPort);
						sender({ data: cmd });
					} catch {}
					const tunnelUrl = await pollTunnelUrl();
					console.log("Tunnel:", tunnelUrl);
					if (tunnelUrl) {
						try {
							const iframe = $("#preview-iframe");
							const box = $("#preview-box");
							const urlInput = $("#preview-url");
							// Build a cache-busting URL for the iframe to avoid stale content
							let bustedUrl = tunnelUrl;
							try {
								const u = new URL(tunnelUrl, window.location.href);
								u.searchParams.set("_cb", String(Date.now()));
								bustedUrl = u.toString();
							} catch {
								bustedUrl =
									tunnelUrl +
									(tunnelUrl.includes("?") ? "&" : "?") +
									"_cb=" +
									Date.now();
							}
							if (iframe) {
								if (box?.classList.contains("hidden"))
									box.classList.remove("hidden");
								if (urlInput) urlInput.value = tunnelUrl;
								iframe.src = bustedUrl;
							} else {
								window.open(bustedUrl, "_blank", "noopener,noreferrer");
							}
						} catch {}
					}
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
		getPort() {
			return runPort;
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
