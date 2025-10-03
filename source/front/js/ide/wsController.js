/**
 * WebSocket controller for PequeRoku IDE
 *
 * Encapsulates WebSocket setup and multi-console session lifecycle,
 * reducing responsibilities in main.js.
 *
 * Responsibilities:
 * - Manage WebSocket connection creation and teardown
 * - Route backend stream/info/error frames to the console UI
 * - Keep ideStore console state in sync (sessions list and active session)
 * - Provide helpers for session control (open/close/focus) and sending input
 *
 * Usage:
 *   import { setupWSController } from "./wsController.js";
 *
 *   const wsCtrl = setupWSController({
 *     containerId,
 *     consoleApi,
 *     onTabsChange: () => fileTabs.update?.(), // optional: refresh UI tabs
 *   });
 *
 *   wsCtrl.connect();
 *   wsCtrl.openSession("s2");
 *   wsCtrl.sendInput("ls -la\n");
 *   wsCtrl.close();
 */

import { notifyAlert } from "../core/alerts.js";
import { ideStore } from "../core/store.js";
import { createWS } from "./websockets.js";

/**
 * @typedef {Object} WSControllerOptions
 * @property {string} containerId
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
 * Create a WS Controller instance
 * @param {WSControllerOptions} opts
 */
export function setupWSController({ containerId, consoleApi, onTabsChange }) {
	/** @type {ReturnType<typeof createWS>|null} */
	let ws = null;
	/** @type {string|null} */
	let lastBytesSid = null;

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

	function handleOpen() {
		try {
			// Reset local sessions; the server will resend session list
			const sids = consoleApi.listSessions?.() || [];
			// biome-ignore lint/suspicious/useIterableCallbackReturn: We want side-effects
			sids.forEach((sid) => consoleApi.closeSession?.(sid));
			ideStore.actions.console.clear();
			onTabsChange?.();
			consoleApi.addLine?.("[connected]");
			dispatchTerminalResize("console");
		} catch {
			// ignore
		}
	}

	function handleInfoMessage(msg) {
		try {
			if (msg.message === "Connected") {
				const sessions = Array.isArray(msg.sessions) ? msg.sessions : [];
				const active = msg.active || sessions[0] || "s1";
				// biome-ignore lint/suspicious/useIterableCallbackReturn: We want side-effects
				sessions.forEach((sid) => consoleApi.openSession?.(sid, false));
				consoleApi.focusSession?.(active);
				ideStore.actions.console.setAll(sessions, active);
				consoleApi.addLine?.(
					`[info] Connected. Sessions: ${sessions.join(", ") || "none"}, active: ${active}`,
					active,
				);
				onTabsChange?.();
				return;
			}

			if (msg.message === "session-opened") {
				const makeActive = msg.active ? msg.active === msg.sid : true;
				consoleApi.openSession?.(msg.sid, !!makeActive);
				if (makeActive) {
					consoleApi.focusSession?.(msg.sid);
				}
				ideStore.actions.console.open(msg.sid, makeActive);
				onTabsChange?.();
				return;
			}

			if (msg.message === "session-closed") {
				consoleApi.closeSession?.(msg.sid);
				ideStore.actions.console.close(msg.sid);
				onTabsChange?.();
				return;
			}

			if (msg.message === "session-focused") {
				consoleApi.focusSession?.(msg.sid);
				ideStore.actions.console.focus(msg.sid);
				onTabsChange?.();
				return;
			}

			// Generic info, route to sid if provided
			const sid = msg.sid || consoleApi.getActive?.();
			consoleApi.addLine?.(`[info] ${msg.message ?? ""}`, sid);
		} catch {
			// ignore
		}
	}

	function handleMessage(ev) {
		try {
			const msg = JSON.parse(ev.data);
			if (msg && typeof msg === "object") {
				if (msg.type === "stream") {
					const sid = msg.sid || consoleApi.getActive?.();
					const payload = typeof msg.payload === "string" ? msg.payload : "";
					consoleApi.write?.(payload, sid);
					return;
				}
				if (msg.type === "stream-bytes") {
					lastBytesSid = msg.sid || consoleApi.getActive?.();
					return;
				}
				if (msg.type === "info") {
					handleInfoMessage(msg);
					return;
				}
				if (msg.type === "error") {
					notifyAlert(msg.message || "Unknown error", "error");
					return;
				}
			}

			// Fallback: treat as text line
			let text = String(ev.data || "");
			text = text.replace(/\r(?!\n)/g, "\r\n");
			consoleApi.write?.(text);
		} catch {
			// Not JSON: binary or text
			if (ev.data instanceof ArrayBuffer) {
				const targetSid = lastBytesSid || consoleApi.getActive?.();
				lastBytesSid = null;
				consoleApi.write?.(new Uint8Array(ev.data), targetSid);
			} else {
				let text = String(ev.data || "");
				text = text.replace(/\r(?!\n)/g, "\r\n");
				consoleApi.write?.(text);
			}
		}
	}

	function handleClose() {
		try {
			consoleApi.write?.("[disconnected]\n");
		} catch {
			// ignore
		}
	}

	function handleError() {
		notifyAlert("WebSocket error", "error");
	}

	function connect() {
		ws = createWS(containerId, {
			onOpen: handleOpen,
			onMessage: handleMessage,
			onClose: handleClose,
			onError: handleError,
		});
	}

	function close(code = 1000, reason = "bye") {
		try {
			ws?.close(code, reason);
		} catch {
			// ignore
		} finally {
			ws = null;
		}
	}

	function send(payload) {
		try {
			ws?.send(payload);
		} catch {
			// ignore
		}
	}

	function sendInput(data) {
		try {
			const active = consoleApi.getActive?.() || null;
			const payload = active ? { sid: active, data } : { data };
			send(payload);
		} catch {
			// ignore
		}
	}

	function openSession(sid) {
		try {
			ws?.send?.({ control: "open", sid });
		} catch {
			// ignore
		}
	}

	function closeSession(sid) {
		try {
			ws?.send?.({ control: "close", sid });
		} catch {
			// ignore
		}
	}

	function focusSession(sid) {
		try {
			ws?.send?.({ control: "focus", sid });
		} catch {
			// ignore
		}
	}

	// Best-effort: close on page unload
	try {
		window.addEventListener("beforeunload", () => {
			try {
				ws?.close?.(1000, "bye");
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
		send,
		sendInput,
		openSession,
		closeSession,
		focusSession,
		hasConnection: () => ws != null,
	};
}
