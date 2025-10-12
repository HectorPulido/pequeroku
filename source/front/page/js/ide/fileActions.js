/**
 * File actions module
 *
 * Centralizes file save logic used by the IDE:
 * - Resolves active file path
 * - Writes through fsws with revision tracking and conflict handling
 * - Dispatches "editor-dirty-changed" to normalize dirty state
 * - Triggers run hydration when saving /app/config.json
 *
 * Usage:
 *   import { setupFileActions } from "./fileActions.js";
 *
 *   const fileActions = setupFileActions({
 *     fsws, // { call: async (method,payload) => any, revs: Map<string, number> }
 *     getActivePath: () => ideStore.get().files?.active || null,
 *     getEditor,      // () => monaco.editor.IStandaloneCodeEditor | null
 *     getEditorValue, // () => string
 *     openEditorPath: (path) => openFileIntoEditor(apiReadFileWrapper, path, setPath),
 *     runHydrate: () => runCtrl.hydrate(),
 *     onAfterSave: () => fileTabs.update?.(), // optional
 *   });
 *
 *   await fileActions.saveCurrentFile();
 */

import { notifyAlert } from "../core/alerts.js";

/**
 * @typedef {Object} SetupFileActionsOptions
 * @property {{ call: (method: string, payload: any) => Promise<any>, revs?: Map<string, number> }} fsws
 * @property {() => string|null} getActivePath
 * @property {() => any} getEditor
 * @property {() => string} getEditorValue
 * @property {(path: string) => Promise<void>} openEditorPath
 * @property {() => Promise<void>} [runHydrate]
 * @property {() => void} [onAfterSave]
 */

/**
 * Create a file actions controller.
 * @param {SetupFileActionsOptions} opts
 * @returns {{ saveCurrentFile: () => Promise<void>, savePath: (path: string, content?: string) => Promise<void> }}
 */
export function setupFileActions({
	fsws,
	getActivePath,
	getEditor,
	getEditorValue,
	openEditorPath,
	runHydrate,
	onAfterSave,
}) {
	if (!fsws || typeof fsws.call !== "function") {
		throw new Error("Invalid fsws passed to setupFileActions");
	}
	if (typeof getActivePath !== "function") {
		throw new Error("getActivePath must be a function");
	}
	if (typeof getEditor !== "function" || typeof getEditorValue !== "function") {
		throw new Error("getEditor and getEditorValue must be functions");
	}
	if (typeof openEditorPath !== "function") {
		throw new Error("openEditorPath must be a function");
	}

	/**
	 * Save the currently active file in the editor.
	 */
	async function saveCurrentFile() {
		const activePath = getActivePath();
		if (!activePath) {
			notifyAlert("Open a file first", "error");
			return;
		}
		await savePath(activePath);
	}

	/**
	 * Save a given path.
	 * If content is not provided and the path is the active one, reads it from the editor.
	 * @param {string} path
	 * @param {string} [content]
	 */
	async function savePath(path, content) {
		const p = String(path || "");
		if (!p) return;

		const activePath = getActivePath();
		const editor = getEditor?.();
		const isActiveDoc = !!activePath && activePath === p;

		const toWrite =
			typeof content === "string"
				? content
				: isActiveDoc
					? (editor?.getModel?.()?.getValue?.() ?? getEditorValue())
					: null;

		if (toWrite == null) {
			notifyAlert(
				"Cannot infer content to save. Provide content or make the file active.",
				"warning",
			);
			return;
		}

		const prevRev =
			(fsws.revs && typeof fsws.revs.get === "function" && fsws.revs.get(p)) ||
			0;

		try {
			const res = await fsws.call("write_file", {
				path: p,
				prev_rev: prevRev,
				content: toWrite,
			});

			const nextRev =
				res && typeof res.rev === "number" ? res.rev : prevRev + 1;
			try {
				if (fsws.revs && typeof fsws.revs.set === "function") {
					fsws.revs.set(p, nextRev);
				}
			} catch {
				// ignore rev cache failures
			}

			notifyAlert(`File ${p} saved`, "success");

			// If saving config.json, refresh run config
			if (p === "/app/config.json") {
				try {
					await runHydrate?.();
				} catch {
					// ignore hydration errors
				}
			}

			// Mark current model as clean if it's the active doc
			try {
				if (isActiveDoc && editor) {
					const model = editor.getModel?.();
					if (model) {
						model._prk_lastSaved = model.getValue?.() ?? "";
					}
				}
			} catch {
				// ignore model metadata errors
			}

			// Emit normalized dirty event (mark as clean)
			try {
				window.dispatchEvent(
					new CustomEvent("editor-dirty-changed", {
						detail: { path: p, dirty: false },
					}),
				);
			} catch {
				// ignore event dispatch errors
			}

			// Allow caller to refresh tabs/tree/etc
			try {
				onAfterSave?.();
			} catch {
				// ignore post-save hooks errors
			}
		} catch (e) {
			const msg = e?.message ? String(e.message) : String(e);
			if (msg.includes("conflict")) {
				const cur =
					(fsws.revs &&
						typeof fsws.revs.get === "function" &&
						fsws.revs.get(p)) ||
					0;
				notifyAlert(
					`Conflict saving saving current Rev ${cur}. Reload...`,
					"error",
				);
				try {
					await openEditorPath(p);
				} catch {
					// ignore reopen errors
				}
			} else {
				notifyAlert(msg, "error");
			}
		}
	}

	return { saveCurrentFile, savePath };
}
