/**
 * Tabs UI handlers for the IDE (console tabs and file tabs).
 *
 * This module extracts the tabs rendering and event wiring from main.js,
 * keeping responsibilities focused and making the code easier to maintain.
 *
 * Usage example:
 *
 * import { setupConsoleTabs, setupFileTabs } from "./tabs.js";
 *
 * const consoleTabs = setupConsoleTabs({
 *   el: document.getElementById("console-tabs"),
 *   onFocus: (sid) => ws?.send({ control: "focus", sid }),
 *   onClose: (sid) => ws?.send({ control: "close", sid }),
 * });
 *
 * const fileTabs = setupFileTabs({
 *   el: document.getElementById("file-tabs"),
 *   isDirty: (p) => dirtyPaths.has(p),
 *   discardIfDirty: async (p) => {
 *     const mod = await import("./editor.js");
 *     mod.discardPathModel?.(p);
 *   },
 *   openFile: (p) => openFileIntoEditor(apiReadFileWrapper, p, setPath),
 *   clearEditor: () => clearEditor(),
 * });
 */

import { $ } from "../core/dom.js";
import { ideStore } from "../core/store.js";

/**
 * Render console tabs.
 * @param {HTMLElement|null} el
 */
export function renderConsoleTabs(el) {
	if (!el) return;
	const { sessions: list, active } = ideStore.get().console || {
		sessions: [],
		active: null,
	};
	if (!Array.isArray(list) || list.length === 0) {
		el.innerHTML = "";
		return;
	}
	el.innerHTML = list
		.map((sid) => {
			const final_sid =
				sid.length > 25 ? `...${sid.slice(sid.length - 25)}` : sid;
			const selected = sid === active;
			return `<button class="console-tab" role="tab" aria-selected="${selected}" data-sid="${sid}" title="${sid}">${final_sid}<span class="icon" data-close="${sid}">×</span></button>`;
		})
		.join("");
}

/**
 * Setup console tabs UI.
 * - Renders tabs when console state changes
 * - Handles focus and close actions via callbacks
 *
 * @param {Object} opts
 * @param {HTMLElement|null} opts.el - Container element for console tabs
 * @param {(sid: string) => void} [opts.onFocus] - Called when a tab is focused
 * @param {(sid: string) => void} [opts.onClose] - Called when a tab close icon is clicked
 *
 * @returns {{ update: () => void, destroy: () => void }}
 */
export function setupConsoleTabs({ onFocus, onClose }) {
	const el = $("#console-tabs");
	if (!el) {
		return { update: () => {}, destroy: () => {} };
	}

	const handleClick = (e) => {
		const target = /** @type {HTMLElement} */ (e.target);
		if (!target) return;

		// Close action
		const closeEl = target.closest("[data-close]");
		if (closeEl) {
			const sid = closeEl.getAttribute("data-close");
			if (sid) {
				try {
					onClose?.(sid);
				} catch {}
			}
			e.stopPropagation();
			return;
		}

		// Focus action
		const tab = target.closest("[data-sid]");
		if (tab) {
			const sid = tab.getAttribute("data-sid");
			if (sid && sid !== (ideStore.get().console.active || null)) {
				try {
					onFocus?.(sid);
				} catch {}
			}
		}
	};

	el.addEventListener("click", handleClick);

	// Subscribe to console state changes and re-render
	const off = ideStore.select(
		(s) => s.console,
		() => renderConsoleTabs(el),
	);

	// Initial render
	renderConsoleTabs(el);

	return {
		update: () => renderConsoleTabs(el),
		destroy: () => {
			try {
				el.removeEventListener("click", handleClick);
			} catch {}
			try {
				off?.();
			} catch {}
		},
	};
}

/**
 * Render file tabs.
 * @param {HTMLElement|null} el
 * @param {(path: string) => boolean} [isDirty] - Optional dirty checker for asterisk marker
 */
export function renderFileTabs(el, isDirty = () => false) {
	if (!el) return;
	const files = ideStore.get().files?.open || [];
	const active = ideStore.get().files?.active || null;
	if (!Array.isArray(files) || files.length === 0) {
		el.innerHTML = "";
		return;
	}
	el.innerHTML = files
		.map((fp) => {
			const name = fp.replace("/app/", "");
			const final_name =
				name.length > 25 ? `...${name.slice(name.length - 25)}` : name;
			const selected = fp === active;
			const dirty = isDirty(fp);
			return `<button class="file-tab" role="tab" aria-selected="${selected}" data-path="${fp}" title="${fp}">${final_name}${dirty ? "*" : ""}<span class="icon" data-close-file="${fp}">×</span></button>`;
		})
		.join("");
}

/**
 * Setup file tabs UI.
 * - Renders tabs when files state changes
 * - Handles open and close file actions
 *
 * @param {Object} opts
 * @param {HTMLElement|null} opts.el - Container element for file tabs
 * @param {(path: string) => boolean} [opts.isDirty] - Optional dirty checker for asterisk marker
 * @param {(path: string) => Promise<void>|void} opts.openFile - Open file callback
 * @param {() => Promise<void>|void} opts.clearEditor - Clear editor callback
 * @param {(path: string) => Promise<void>|void} [opts.discardIfDirty] - Optional hook to discard model if dirty before closing
 *
 * @returns {{ update: () => void, destroy: () => void }}
 */
export function setupFileTabs({
	isDirty = () => false,
	openFile,
	clearEditor,
	discardIfDirty,
}) {
	const el = $("#file-tabs");
	if (!el) {
		return { update: () => {}, destroy: () => {} };
	}

	const handleClick = async (e) => {
		const target = /** @type {HTMLElement} */ (e.target);
		if (!target) return;

		// Close a tab
		const closeEl = target.closest("[data-close-file]");
		if (closeEl) {
			const path = closeEl.getAttribute("data-close-file");
			if (!path) return;

			const prevActive = ideStore.get().files?.active || null;
			const files = ideStore.get().files?.open || [];
			const idx = Math.max(0, files.indexOf(path));

			try {
				if (isDirty(path)) {
					await discardIfDirty?.(path);
				}
			} catch {
				// ignore discard errors
			}

			// Update store first
			ideStore.actions.files.close(path);

			// If the closed tab was active, decide next action
			if (prevActive === path) {
				const remaining = ideStore.get().files?.open || [];
				const nextIdx = idx < remaining.length ? idx : idx - 1;
				const next = nextIdx >= 0 ? remaining[nextIdx] : null;
				if (next) {
					try {
						await openFile(next);
					} catch {
						// ignore open errors
					}
				} else {
					try {
						await clearEditor();
					} catch {
						// ignore clear errors
					}
				}
			}

			// Stop propagation so outer handlers don't trigger
			e.stopPropagation();
			return;
		}

		// Focus (open) a tab
		const tab = target.closest("[data-path]");
		if (tab) {
			const path = tab.getAttribute("data-path");
			if (path) {
				try {
					await openFile(path);
				} catch {
					// ignore open errors
				}
			}
		}
	};

	el.addEventListener("click", handleClick);

	// Subscribe to files state changes and re-render
	const off = ideStore.select(
		(s) => s.files,
		() => renderFileTabs(el, isDirty),
	);

	// Initial render
	renderFileTabs(el, isDirty);

	return {
		update: () => renderFileTabs(el, isDirty),
		destroy: () => {
			try {
				el.removeEventListener("click", handleClick);
			} catch {}
			try {
				off?.();
			} catch {}
		},
	};
}
