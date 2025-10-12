/**
 * GitHub Clone Modal Controller
 *
 * Encapsulates the "Clone from GitHub" modal behavior:
 * - Owns all DOM querying for the modal and related controls
 * - Wires open/close via bindModal
 * - On submit: composes and sends the clone command using the provided WS controller
 * - Waits a configurable time and triggers a refresh callback
 *
 * Usage:
 *   import { setupGithubModal } from "./githubModal.js";
 *
 *   const github = setupGithubModal({
 *     wsCtrl, // { hasConnection(): boolean, send(payload: any): void }
 *     refreshIDE: async () => { await ft.refresh(); await runCtrl.hydrate(); },
 *   });
 *
 *   // Optional:
 *   // github.open();
 *   // github.close();
 *   // github.dispose();
 */

import { notifyAlert } from "../core/alerts.js";
import { ACTION_DELAYS } from "../core/constants.js";
import { $ } from "../core/dom.js";
import { bindModal } from "../core/modals.js";
import { sleep } from "../core/utils.js";

/**
 * @typedef {Object} GithubModalOptions
 * @property {{ hasConnection?: () => boolean, send?: (payload: any) => void } | null} wsCtrl
 * @property {() => Promise<void>} refreshIDE - Called after a successful clone to refresh UI/state (e.g., refresh file tree and hydrate run config)
 */

/**
 * Setup the GitHub modal wiring.
 * @param {GithubModalOptions} opts
 * @returns {{ open: () => void, close: () => void, dispose: () => void }}
 */
export function setupGithubModal({ wsCtrl, refreshIDE }) {
	const modalEl = $("#github-modal");
	const openBtn = $("#btn-clone-repo");
	const closeBtn = $("#btn-github-close");
	const submitBtn = $("#btn-github");
	const urlInput = $("#url_git");
	const basePathInput = $("#base_path");

	if (
		!modalEl ||
		!openBtn ||
		!closeBtn ||
		!submitBtn ||
		!urlInput ||
		!basePathInput
	) {
		// Missing DOM elements; return safe no-op controller
		return {
			open: () => {},
			close: () => {},
			dispose: () => {},
		};
	}

	const titleEl = modalEl?.querySelector?.(".upload-header > span") || null;
	const modalCtrl = bindModal(modalEl, openBtn, closeBtn, {
		titleEl,
		defaultTitle: titleEl?.textContent || "Clone from Github",
		initialFocus: () => urlInput,
		onOpen: () => {
			try {
				submitBtn.disabled = false;
			} catch {}
		},
	});

	let running = false;

	async function onSubmit() {
		if (running) return;

		const repo = String(urlInput.value || "").trim();
		const base_path = String(basePathInput.value || "").trim() || "/";

		if (!repo) {
			notifyAlert("Please provide a Git repository URL", "warning");
			return;
		}
		if (!wsCtrl?.hasConnection?.()) {
			notifyAlert(
				"Console is not connected. Please reconnect and try again.",
				"error",
			);
			return;
		}

		running = true;
		submitBtn.disabled = true;

		// Note: Keep the command consistent with previous behavior
		const cmd = `bash -lc 'set -euo pipefail; REPO="${repo}"; X="${base_path}"; TMP="$(mktemp -d)"; git clone "$REPO" "$TMP/repo"; sudo mkdir -p /app; find /app -mindepth 1 -not -name "readme.txt" -not -name "config.json" -exec rm -rf {} +; SRC="$TMP/repo"; [ "\${X:-/}" != "/" ] && SRC="$TMP/repo/\${X#/}"; shopt -s dotglob nullglob; mv "$SRC"/* /app/; rm -rf "$TMP"'`;

		try {
			wsCtrl?.send?.({ data: cmd });
			await sleep(ACTION_DELAYS.cloneRepoWaitMs);
			await refreshIDE?.();
			modalCtrl.close();
		} catch (e) {
			notifyAlert(e?.message || String(e), "error");
		} finally {
			running = false;
			submitBtn.disabled = false;
		}
	}

	submitBtn.addEventListener("click", onSubmit);

	function dispose() {
		try {
			submitBtn.removeEventListener("click", onSubmit);
		} catch {}
	}

	return {
		open: () => {
			try {
				openBtn.click();
			} catch {
				// fallback
				try {
					modalCtrl?.open?.();
				} catch {}
			}
		},
		close: () => {
			try {
				modalCtrl?.close?.();
			} catch {}
		},
		dispose,
	};
}
