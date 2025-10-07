/**
 * WS Controller: one WebSocket per console session (sid)
 *
 * - Frontend <-> Django: raw frames
 *   - Outgoing: text (keystrokes/strings) or binary (Uint8Array/ArrayBuffer)
 *   - Incoming: binary (ArrayBuffer) -> write to xterm, or text -> write as-is
 * - sid is passed via query string (?sid=sN)
 *
 * Public API:
 *   const wsCtrl = setupWSController({ containerId, consoleApi, onTabsChange });
 *   wsCtrl.connect();                 // ensure s1 is connected
 *   wsCtrl.openSession("s2");         // open extra session socket
 *   wsCtrl.focusSession("s2");        // set active session
 *   wsCtrl.sendInput("ls -la");       // send to active session as text
 *   wsCtrl.closeSession("s2");        // close a session socket
 *   wsCtrl.close();                   // close all sockets
 */
import { createWS } from "./websockets.js";

/**
 * @typedef {Object} WSControllerOptions
 * @property {string|number} containerId
 * @property {{
 *   getActive?: () => string | null,
 *   listSessions?: () => string[],
 *   openSession?: (sid: string, makeActive?: boolean) => void,
 *   closeSession?: (sid: string) => void,
 *   focusSession?: (sid: string) => void,
 *   addLine?: (text: string, sid?: string|null) => void,
 *   write?: (data: string | Uint8Array, sid?: string|null) => void,
 *   clear?: (sid?: string|null) => void,
 *   fit?: () => void,
 * }} consoleApi
 * @property {() => void} [onTabsChange] - optional callback to refresh tabs UI
 */

/**
 * Create a WS Controller instance with one socket per session id.
 * @param {WSControllerOptions} opts
 */
export function setupWSController({ containerId, consoleApi, onTabsChange }) {
	/** @type {Map<string, ReturnType<typeof createWSBase>>} */
	const sockets = new Map();
	/** @type {string|null} */
	let activeSid = null;

	function dispatchTerminalResize(target = "console") {
		try {
			window.dispatchEvent(
				new CustomEvent("terminal-resize", { detail: { target } }),
			);
			consoleApi?.fit?.();
		} catch {
			// ignore
		}
	}

	function ensureActiveSid() {
		if (activeSid && sockets.has(activeSid)) return activeSid;
		const uiActive = consoleApi.getActive?.() || null;
		if (uiActive && sockets.has(uiActive)) {
			activeSid = uiActive;
			return activeSid;
		}
		// Pick first available
		const first = sockets.keys().next();
		activeSid = first.done ? null : first.value;
		return activeSid;
	}

	function handleOpen(sid) {
		try {
			// Ensure UI/store know about this session (idempotent if already opened)
			consoleApi.openSession?.(sid, false);
			consoleApi.focusSession?.(sid);
			if (!activeSid) activeSid = sid;
			consoleApi.addLine?.(`[connected sid=${sid}]`, sid);

			const t = consoleApi?.term?.current;
			const cols = t?.cols ? t.cols : 80;
			const rows = t?.rows ? t.rows : 24;
			try {
				sendToSid(sid, `__RESIZE__ ${cols}x${rows}`);
			} catch {}
			setTimeout(() => {
				try {
					const tt = consoleApi?.term?.current;
					const c = tt?.cols ? tt.cols : cols;
					const r = tt?.rows ? tt.rows : rows;
					sendToSid(sid, `__RESIZE__ ${c}x${r}`);
				} catch {}
			}, 1200);

			dispatchTerminalResize("console");
			onTabsChange?.();
		} catch {
			// ignore
		}
	}

	function handleMessage(sid, ev) {
		try {
			// Binary frame
			if (ev.data instanceof ArrayBuffer) {
				consoleApi.write?.(new Uint8Array(ev.data), sid);
				return;
			}
			// Text frame
			let text = String(ev.data || "");
			// Normalize CR for nicer display in xterm
			text = text.replace(/\r(?!\n)/g, "\r\n");
			consoleApi.write?.(text, sid);
		} catch {
			// ignore
		}
	}

	function handleClose(sid, ev, info) {
		try {
			const wait = info && typeof info.waitMs === "number" ? info.waitMs : null;
			if (wait && wait > 0) {
				const secs = Math.ceil(wait / 1000);
				consoleApi.addLine?.(
					`[disconnected sid=${sid}] reconnecting in ${secs}s`,
					sid,
				);
			} else {
				consoleApi.addLine?.(`[disconnected sid=${sid}]`, sid);
			}
			onTabsChange?.();
		} catch {
			// ignore
		}
	}

	function handleError(sid, _ev) {
		try {
			consoleApi.addLine?.(`[error sid=${sid}]`, sid);
		} catch {
			// ignore
		}
	}

	function openSocketForSid(sid) {
		if (!sid || sockets.has(sid)) return;
		const sock = createWS(containerId, {
			sid,
			onOpen: () => handleOpen(sid),
			onMessage: (ev) => handleMessage(sid, ev),
			onClose: (ev, info) => handleClose(sid, ev, info),
			onError: (ev) => handleError(sid, ev),
		});
		sockets.set(sid, sock);
	}

	function closeSocketForSid(sid) {
		const sock = sockets.get(sid);
		if (!sock) return;
		try {
			sock.close({ code: 1000, reason: "bye", reconnect: false });
		} catch {
			// ignore
		} finally {
			sockets.delete(sid);
			if (activeSid === sid) {
				activeSid = null;
				ensureActiveSid();
			}
		}
	}

	function connect() {
		// Ensure default session socket exists; console UI already creates "s1" tab.
		openSocketForSid("s1");
		ensureActiveSid();
	}

	function close(code = 1000, reason = "bye") {
		for (const [_, sock] of sockets) {
			try {
				sock.close({ code, reason, reconnect: false });
			} catch {
				// ignore
			}
		}
		sockets.clear();
		activeSid = null;
	}

	function hasConnection() {
		return sockets.size > 0;
	}

	function openSession(sid) {
		if (!sid) return;
		openSocketForSid(sid);
		// UI session/tab should already be created by caller.
		activeSid = sid;
		onTabsChange?.();
	}

	function closeSession(sid) {
		if (!sid) return;
		closeSocketForSid(sid);
		// Caller handles consoleApi.closeSession UI; we keep transport minimal.
		onTabsChange?.();
	}

	function focusSession(sid) {
		if (!sid) return;
		if (sockets.has(sid)) {
			activeSid = sid;
			// UI focus is handled by caller; we only switch the target socket.
			onTabsChange?.();
		}
	}

	function sendToSid(sid, payload) {
		const sock = sockets.get(sid);
		if (!sock) return false;
		try {
			return sock.send(payload);
		} catch {
			return false;
		}
	}

	function send(payload) {
		// Generic send: route to active session (for backwards compatibility)
		const sid = ensureActiveSid();
		if (!sid) return false;
		return sendToSid(sid, payload);
	}

	function sendInput(data) {
		// Keystrokes / line input: prefer raw bytes if provided, else text
		const sid = ensureActiveSid();
		if (!sid) return false;
		if (data == null) return false;

		// Allow callers to pass Uint8Array/ArrayBuffer for precise control keys
		if (data instanceof ArrayBuffer || ArrayBuffer.isView?.(data)) {
			return sendToSid(sid, data);
		}

		// Strings: send as text frame. Do NOT force newline; caller decides.
		const text = String(data);
		return sendToSid(sid, text);
	}

	// Best-effort: close all on page unload
	try {
		window.addEventListener("beforeunload", () => {
			try {
				close(1000, "bye");
			} catch {
				// ignore
			}
		});
	} catch {
		// ignore
	}

	return {
		connect,
		close,
		hasConnection,
		send,
		sendInput,
		openSession,
		closeSession,
		focusSession,
	};
}
