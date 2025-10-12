/**
 * Central IDE Store with PubSub
 *
 * Goals:
 * - Single source of truth for IDE state (files, console sessions, etc.)
 * - Simple Pub/Sub for state changes and arbitrary app events
 * - Helpers (actions) to perform common operations without duplicating logic
 *
 * This module is framework-agnostic and has no dependencies.
 *
 * Usage (examples):
 *   import { ideStore, bus } from "../core/store.js";
 *
 *   // Read state
 *   const state = ideStore.get();
 *
 *   // Subscribe to all changes
 *   const off = ideStore.subscribe((next, prev) => {
 *     // example removed
 *   });
 *
 *   // Subscribe to a slice
 *   const offActiveFile = ideStore.select(
 *     (s) => s.files.active,
 *     (active, prevActive) => {},
 *   );
 *
 *   // Update state (partial)
 *   ideStore.set({ runCommand: "bash -lc 'node index.js'" });
 *
 *   // Update state via function
 *   ideStore.update((s) => ({ ...s, theme: "dark" }));
 *
 *   // Use actions
 *   ideStore.actions.files.open("/app/main.js");
 *   ideStore.actions.console.open("s2", true);
 *   ideStore.actions.console.close("s1");
 *
 *   // Emit/listen custom events (not tied to store)
 *   const offPing = bus.on("ping", (p) => {});
 *   bus.emit("ping", { t: Date.now() });
 *   offPing();
 */

// ---------------------------
// Small event bus (Pub/Sub)
// ---------------------------
function createPubSub() {
	const listeners = new Map(); // event -> Set<fn>

	function on(event, handler) {
		if (!listeners.has(event)) listeners.set(event, new Set());
		const set = listeners.get(event);
		set.add(handler);
		return () => off(event, handler);
	}

	function off(event, handler) {
		const set = listeners.get(event);
		if (!set) return;
		set.delete(handler);
		if (set.size === 0) listeners.delete(event);
	}

	function emit(event, payload) {
		const set = listeners.get(event);
		if (!set || set.size === 0) return;
		// Copy to avoid mutation during emit
		Array.from(set).forEach((fn) => {
			try {
				fn(payload);
			} catch (e) {
				// eslint-disable-next-line no-console
				console.error(`[bus] error in listener for "${event}":`, e);
			}
		});
	}

	return { on, off, emit };
}

// A shared global bus for arbitrary events (not just state changes)
export const bus = createPubSub();

// ---------------------------
// Helpers
// ---------------------------
const is = Object.is;
function shallowEqual(a, b) {
	if (is(a, b)) return true;
	if (
		typeof a !== "object" ||
		a === null ||
		typeof b !== "object" ||
		b === null
	)
		return false;
	const ka = Object.keys(a);
	const kb = Object.keys(b);
	if (ka.length !== kb.length) return false;
	for (const k of ka) {
		if (!is(a[k], b[k])) return false;
	}
	return true;
}

// ---------------------------
// Store implementation
// ---------------------------

/**
 * @typedef {Object} IDEFilesState
 * @property {string[]} open - Ordered list of open file paths
 * @property {string|null} active - Active file path or null
 *
 * @typedef {Object} IDEConsoleState
 * @property {string[]} sessions - Ordered list of console session IDs
 * @property {string|null} active - Active session ID or null
 *
 * @typedef {Object} IDEState
 * @property {string|null} containerId
 * @property {ID EFilesState} files
 * @property {IDEConsoleState} console
 * @property {string|null} runCommand
 * @property {"light"|"dark"|null} theme
 */

const initialState = Object.freeze({
	containerId: null,
	files: { open: [], active: null },
	console: { sessions: [], active: null },
	runCommand: null,
	theme: null,
});

/**
 * Create a simple global store
 * @param {Partial<IDEState>} seed
 */
function createStore(seed = {}) {
	/** @type {IDEState} */
	let state = {
		...initialState,
		...seed,
		files: { ...initialState.files, ...(seed.files || {}) },
		console: { ...initialState.console, ...(seed.console || {}) },
	};

	const subscribers = new Set(); // (next, prev) => void

	function get() {
		return state;
	}

	function notify(prev) {
		// Emit store change event on the global bus, in case some code prefers centralized feed
		try {
			bus.emit("store:change", { next: state, prev });
		} catch {}
		// Call store subscribers
		subscribers.forEach((fn) => {
			try {
				fn(state, prev);
			} catch (e) {
				// eslint-disable-next-line no-console
				console.error("[store] subscriber error:", e);
			}
		});
	}

	/**
	 * Shallow merge top-level keys and notify if changed
	 * @param {Partial<IDEState>} patch
	 */
	function set(patch) {
		const prev = state;
		// Build next with shallow copy; ensure nested slices are copied when updated
		const next = {
			...prev,
			...patch,
			files: patch.files ? { ...prev.files, ...patch.files } : prev.files,
			console: patch.console
				? { ...prev.console, ...patch.console }
				: prev.console,
		};

		if (next === prev) return;
		if (shallowEqual(prev, next)) return;

		state = next;
		notify(prev);
	}

	/**
	 * Functional update style
	 * @param {(s: IDEState) => IDEState | Partial<IDEState>} updater
	 */
	function update(updater) {
		const res = updater(state);
		if (!res) return;
		if (typeof res === "object" && !Array.isArray(res)) {
			set(res);
		} else {
			// Ignore invalid updater results
		}
	}

	/**
	 * Subscribe to any state change
	 * @param {(next: IDEState, prev: IDEState) => void} fn
	 * @returns {() => void} unsubscribe
	 */
	function subscribe(fn) {
		subscribers.add(fn);
		return () => {
			subscribers.delete(fn);
		};
	}

	/**
	 * Subscribe to a derived slice
	 * @template T
	 * @param {(s: IDEState) => T} selector
	 * @param {(next: T, prev: T, rootNext: IDEState, rootPrev: IDEState) => void} cb
	 * @param {(a: T, b: T) => boolean} [equals] - Comparison function (default: Object.is)
	 * @returns {() => void} unsubscribe
	 */
	function select(selector, cb, equals = is) {
		let prevSel;
		let initial = true;

		function handler(next, prev) {
			const cur = selector(next);
			if (initial) {
				initial = false;
				prevSel = cur;
				cb(cur, undefined, next, prev);
				return;
			}
			if (!equals(cur, prevSel)) {
				const old = prevSel;
				prevSel = cur;
				cb(cur, old, next, prev);
			}
		}

		return subscribe(handler);
	}

	function reset() {
		const prev = state;
		state = {
			...initialState,
			// do not clear theme if present to avoid flicker; comment out if not desired
			theme: prev.theme ?? initialState.theme,
		};
		notify(prev);
	}

	// --------------- Actions (domain-specific helpers) ---------------

	const actions = {
		// General / metadata
		setContainer(id) {
			set({ containerId: id != null ? String(id) : null });
		},
		setRunCommand(cmd) {
			set({ runCommand: typeof cmd === "string" ? cmd : null });
		},
		setTheme(theme) {
			if (theme === "light" || theme === "dark" || theme === null) {
				set({ theme });
			}
		},

		// Files (tabs)
		files: {
			open(path) {
				const p = String(path || "");
				if (!p) return;
				const { files } = state;
				const exists = files.open.includes(p);
				const open = exists ? files.open.slice() : [...files.open, p];
				const active = p;
				set({ files: { open, active } });
			},
			close(path) {
				const p = String(path || "");
				if (!p) return;
				const { files } = state;
				const i = files.open.indexOf(p);
				if (i < 0) return;
				const open = files.open.filter((x) => x !== p);
				let active = files.active;
				if (files.active === p) {
					const nextIdx = i < open.length ? i : i - 1;
					active = nextIdx >= 0 ? open[nextIdx] : null;
				}
				set({ files: { open, active } });
			},
			focus(path) {
				const p = String(path || "");
				if (!p) return;
				if (!state.files.open.includes(p)) {
					// Open if not present, and focus it
					actions.files.open(p);
					return;
				}
				set({ files: { ...state.files, active: p } });
			},
			setOpen(list) {
				const arr = Array.isArray(list)
					? Array.from(new Set(list.map(String)))
					: [];
				// Preserve active if still present
				const active = arr.includes(state.files.active)
					? state.files.active
					: arr[0] || null;
				set({ files: { open: arr, active } });
			},
			clear() {
				set({ files: { open: [], active: null } });
			},
		},

		// Console sessions (multi-terminal)
		console: {
			open(sid, makeActive = true) {
				const id = String(sid || "");
				if (!id) return;
				const exists = state.console.sessions.includes(id);
				const sessions = exists
					? state.console.sessions.slice()
					: [...state.console.sessions, id];
				const active = makeActive ? id : (state.console.active ?? id);
				set({ console: { sessions, active } });
			},
			close(sid) {
				const id = String(sid || "");
				if (!id) return;
				const { sessions, active } = state.console;
				const i = sessions.indexOf(id);
				if (i < 0) return;
				const nextSessions = sessions.filter((x) => x !== id);
				let nextActive = active;
				if (active === id) {
					nextActive = nextSessions[0] || null;
				}
				set({ console: { sessions: nextSessions, active: nextActive } });
			},
			focus(sid) {
				const id = String(sid || "");
				if (!id) return;
				if (!state.console.sessions.includes(id)) {
					actions.console.open(id, true);
					return;
				}
				set({ console: { ...state.console, active: id } });
			},
			setAll(list, active) {
				const sessions = Array.isArray(list)
					? Array.from(new Set(list.map(String)))
					: [];
				const nextActive =
					active && sessions.includes(active) ? active : sessions[0] || null;
				set({ console: { sessions, active: nextActive } });
			},
			clear() {
				set({ console: { sessions: [], active: null } });
			},
		},
	};

	return { get, set, update, subscribe, select, reset, actions };
}

// Singleton store for the IDE
export const ideStore = createStore();

// Expose for debugging in the browser console without polluting too much
try {
	if (typeof window !== "undefined") {
		window.pequeroku = window.pequeroku || {};
		window.pequeroku.store = ideStore;
		window.pequeroku.bus = bus;
	}
} catch {
	// ignore if window not available
}
