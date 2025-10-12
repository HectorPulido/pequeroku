/**
 * Dirty paths tracker for the IDE editor.
 *
 * Extracted from main.js to keep concerns isolated.
 *
 * Responsibilities:
 * - Track "dirty" (unsaved) file paths
 * - Normalize various path formats to canonical "/app/..." paths
 * - React to "editor-dirty-changed" CustomEvents and update the set
 * - Provide a small subscription API for UI updates (e.g., re-render tabs)
 *
 * Usage:
 *
 *   import { createDirtyTracker } from "./dirtyTracker.js";
 *
 *   const dirty = createDirtyTracker({
 *     eventName: "editor-dirty-changed",
 *     onChange: () => renderFileTabs(el, (p) => dirty.isDirty(p)),
 *   });
 *
 *   dirty.attach();
 *   // ...
 *   dirty.detach();
 *
 * Event payload shape (CustomEvent.detail):
 *   { path: string, dirty: boolean }
 */

/**
 * Normalize a path to the canonical "/app/..." format if possible.
 * Returns null if the input cannot be normalized to an /app path.
 *
 * Logic:
 * - If "file://", parse and take the URL pathname
 * - If contains "/app/" but doesn't start with it, slice from "/app/"
 * - If starts with "app/", prefix a leading slash
 *
 * @param {string} input
 * @returns {string|null}
 */
export function normalizeDirtyPath(input) {
	try {
		let p = String(input || "");
		if (!p) return null;

		// If it's a file URL, convert to path
		if (p.startsWith("file://")) {
			try {
				p = new URL(p).pathname;
			} catch {
				// ignore invalid URL, keep original
			}
		}

		// If it contains "/app/" but doesn't start with it, slice
		if (!p.startsWith("/app/") && p.includes("/app/")) {
			p = p.slice(p.indexOf("/app/"));
		} else if (!p.startsWith("/app/") && p.startsWith("app/")) {
			// If starts with "app/", prefix leading slash
			p = `/${p}`;
		}

		// Only accept canonical "/app/" paths
		if (p.startsWith("/app/")) return p;
		return null;
	} catch {
		return null;
	}
}

/**
 * @typedef {Object} DirtyTrackerOptions
 * @property {string} [eventName="editor-dirty-changed"] - Event to listen to.
 * @property {() => void} [onChange] - Optional callback when the dirty set changes.
 */

/**
 * Create a dirty paths tracker instance.
 *
 * @param {DirtyTrackerOptions} [options]
 * @returns {{
 *   isDirty: (path: string) => boolean,
 *   mark: (path: string, dirty: boolean) => boolean,
 *   clear: (path?: string) => void,
 *   getAll: () => string[],
 *   attach: () => void,
 *   detach: () => void,
 *   subscribe: (fn: () => void) => () => void
 * }}
 */
export function createDirtyTracker(options = {}) {
	const eventName = options.eventName || "editor-dirty-changed";
	/** @type {Set<string>} */
	const set = new Set();
	/** @type {Set<() => void>} */
	const listeners = new Set();
	let attached = false;

	if (typeof options.onChange === "function") {
		listeners.add(options.onChange);
	}

	function notify() {
		// Copy to avoid mutation during iteration
		Array.from(listeners).forEach((fn) => {
			try {
				fn();
			} catch {
				// ignore listener errors
			}
		});
	}

	/**
	 * Check if a path is currently marked as dirty.
	 * @param {string} path
	 */
	function isDirty(path) {
		const p = normalizeDirtyPath(path);
		if (!p) return false;
		return set.has(p);
	}

	/**
	 * Mark or unmark a path as dirty.
	 * @param {string} path
	 * @param {boolean} dirty
	 * @returns {boolean} true if the set changed, false otherwise
	 */
	function mark(path, dirty) {
		const p = normalizeDirtyPath(path);
		if (!p) return false;

		if (dirty) {
			if (!set.has(p)) {
				set.add(p);
				notify();
				return true;
			}
			return false;
		}

		if (set.delete(p)) {
			notify();
			return true;
		}
		return false;
	}

	/**
	 * Clear dirty flags.
	 * - If path provided, clears only that path
	 * - If omitted, clears all
	 * @param {string} [path]
	 */
	function clear(path) {
		if (typeof path === "string") {
			const p = normalizeDirtyPath(path);
			if (p && set.delete(p)) notify();
			return;
		}
		if (set.size > 0) {
			set.clear();
			notify();
		}
	}

	/**
	 * Get all dirty paths (array copy).
	 */
	function getAll() {
		return Array.from(set);
	}

	/**
	 * Handle DOM CustomEvent for dirty changes.
	 * Expected event.detail: { path: string, dirty: boolean }
	 * @param {Event} ev
	 */
	function handleDirtyEvent(ev) {
		try {
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			const detail = /** @type {any} */ (ev)?.detail || {};
			const path = typeof detail.path === "string" ? detail.path : "";
			const dirty = !!detail.dirty;
			if (!path) return;
			mark(path, dirty);
		} catch {
			// ignore
		}
	}

	/**
	 * Start listening to "editor-dirty-changed" events on window.
	 */
	function attach() {
		if (attached) return;
		try {
			window.addEventListener(eventName, handleDirtyEvent);
			attached = true;
		} catch {
			// ignore
		}
	}

	/**
	 * Stop listening to events.
	 */
	function detach() {
		if (!attached) return;
		try {
			window.removeEventListener(eventName, handleDirtyEvent);
			attached = false;
		} catch {
			// ignore
		}
	}

	/**
	 * Subscribe to dirty set changes.
	 * Returns an unsubscribe function.
	 * @param {() => void} fn
	 */
	function subscribe(fn) {
		if (typeof fn !== "function") return () => {};
		listeners.add(fn);
		return () => {
			try {
				listeners.delete(fn);
			} catch {
				// ignore
			}
		};
	}

	return { isDirty, mark, clear, getAll, attach, detach, subscribe };
}
