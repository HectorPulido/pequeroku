/**
 * Base reusable WebSocket creator with backoff and queue.
 *
 * Features:
 * - Exponential backoff auto-reconnect (configurable)
 * - Message queue while not OPEN (flushes on connect)
 * - Pluggable payload encoding/decoding
 * - Optional periodic ping (keep-alive)
 * - Graceful close with ability to disable further reconnects
 * - Handlers updateable at runtime
 *
 * Usage:
 *   import { createWSBase } from "./ws.js";
 *
 *   const sock = createWSBase("wss://example/ws", {
 *     onOpen: (ws) => console.log("open"),
 *     onMessage: (ev, ws) => console.log("msg", ev.data),
 *     onClose: (ev) => console.log("close"),
 *     onError: (ev) => console.error("err", ev),
 *   });
 *
 *   sock.send({ hello: "world" });
 *   sock.close(); // to stop and disable auto-reconnect
 *   // or sock.close({ reconnect: true }) to reconnect after close
 */

import { WS_BACKOFF } from "../core/constants.js";

/**
 * @typedef {Object} WSHandlers
 * @property {(ws: WebSocket) => void} [onOpen]
 * @property {(ev: MessageEvent, ws: WebSocket) => void} [onMessage]
 * @property {(ev: CloseEvent, info: { attempts: number }) => void} [onClose]
 * @property {(ev: Event) => void} [onError]
 */

/**
 * @typedef {Object} WSOptions
 * @property {string|string[]} [protocols]
 * @property {{ baseMs?: number, maxMs?: number }} [backoff]
 * @property {boolean} [autoReconnect=true]
 * @property {boolean} [lazy=false] - If true, do not connect immediately.
 * @property {string} [binaryType="arraybuffer"]
 * @property {number} [queueLimit=100]
 * @property {{ intervalMs?: number, payload?: any }} [ping] - Keep-alive config
 * @property {(payload:any)=>string|ArrayBuffer} [encode] - Payload encoder for send()
 * @property {(ev: MessageEvent)=>any} [decode] - Optional decoder for onMessage
 * @property {(ws: WebSocket) => void} [onOpen]
 * @property {(ev: MessageEvent, ws: WebSocket) => void} [onMessage]
 * @property {(ev: CloseEvent, info: { attempts: number }) => void} [onClose]
 * @property {(ev: Event) => void} [onError]
 */

/**
 * Default payload encoder.
 * - ArrayBuffer and views: return raw ArrayBuffer
 * - Object: JSON.stringify
 * - String/others: toString
 * @param {any} payload
 * @returns {string|ArrayBuffer}
 */
function defaultEncode(payload) {
	if (payload == null) return "";
	if (payload instanceof ArrayBuffer) return payload;
	// TypedArray / DataView
	if (ArrayBuffer.isView?.(payload)) {
		const view = payload;
		try {
			return view.buffer.slice(
				view.byteOffset,
				view.byteOffset + view.byteLength,
			);
		} catch {
			return view.buffer;
		}
	}
	if (typeof payload === "object") {
		try {
			return JSON.stringify(payload);
		} catch {
			return String(payload);
		}
	}
	if (typeof payload === "string") return payload;
	return String(payload);
}

/**
 * Transform numeric readyState into human-friendly string.
 * @param {WebSocket|undefined|null} ws
 * @returns {"CONNECTING"|"OPEN"|"CLOSING"|"CLOSED"}
 */
function readyStateString(ws) {
	if (!ws) return "CLOSED";
	switch (ws.readyState) {
		case WebSocket.CONNECTING:
			return "CONNECTING";
		case WebSocket.OPEN:
			return "OPEN";
		case WebSocket.CLOSING:
			return "CLOSING";
		default:
			return "CLOSED";
	}
}

/**
 * Create a base WebSocket client with backoff and queue.
 * @param {string} url
 * @param {WSOptions} [opts]
 */
export function createWSBase(
	url,
	{
		protocols,
		backoff = {},
		autoReconnect = true,
		lazy = false,
		binaryType = "arraybuffer",
		queueLimit = 100,
		ping,
		encode = defaultEncode,
		decode,
		onOpen,
		onMessage,
		onClose,
		onError,
	} = {},
) {
	let currentUrl = url;
	let ws = /** @type {WebSocket|null} */ (null);
	let attempts = 0;
	let reconnectTimer = /** @type {number|null} */ (null);
	let pinger = /** @type {number|null} */ (null);
	let shouldReconnect = !!autoReconnect;
	const baseMs = backoff.baseMs ?? WS_BACKOFF.baseMs;
	const maxMs = backoff.maxMs ?? WS_BACKOFF.maxMs;

	/** @type {any[]} */
	const queue = [];

	function setHandlers(h = /** @type {WSHandlers} */ ({})) {
		if ("onOpen" in h) onOpen = h.onOpen;
		if ("onMessage" in h) onMessage = h.onMessage;
		if ("onClose" in h) onClose = h.onClose;
		if ("onError" in h) onError = h.onError;
		return api;
	}

	function setUrl(nextUrl, { reconnect = true } = {}) {
		currentUrl = String(nextUrl);
		if (reconnect) {
			close({ reconnect: true });
		}
		return api;
	}

	function clearTimers() {
		if (reconnectTimer != null) {
			clearTimeout(reconnectTimer);
			reconnectTimer = null;
		}
		if (pinger != null) {
			clearInterval(pinger);
			pinger = null;
		}
	}

	function scheduleReconnect() {
		if (!shouldReconnect) return;
		clearTimers();
		const wait = Math.min(maxMs, baseMs * 2 ** attempts++);
		reconnectTimer = setTimeout(connect, wait);
	}

	function startPing() {
		if (!ping?.intervalMs) return;
		if (pinger != null) return;
		pinger = setInterval(
			() => {
				try {
					if (ws && ws.readyState === WebSocket.OPEN) {
						// Send ping payload (string/buffer/object)
						api.send(ping.payload ?? "ping");
					}
				} catch {}
			},
			Math.max(250, Number(ping.intervalMs)),
		);
	}

	function stopPing() {
		if (pinger != null) {
			clearInterval(pinger);
			pinger = null;
		}
	}

	function flushQueue(socket) {
		// Drain current snapshot to avoid loop if send enqueues again
		const toSend = queue.splice(0, queue.length);
		for (const item of toSend) {
			try {
				socket.send(encode(item));
			} catch (_e) {
				// if cannot send, push back to the front of the queue and break
				queue.unshift(item);
				break;
			}
		}
	}

	function connect() {
		// Guard against multiple parallel connects
		if (
			ws &&
			(ws.readyState === WebSocket.CONNECTING ||
				ws.readyState === WebSocket.OPEN)
		) {
			return api;
		}

		clearTimers();
		try {
			ws = new WebSocket(currentUrl, protocols);
		} catch (_e) {
			// Fallback to reconnection schedule if ctor throws
			scheduleReconnect();
			return api;
		}
		ws.binaryType = binaryType;

		ws.onopen = () => {
			attempts = 0;
			try {
				onOpen?.(ws);
			} catch {}
			try {
				flushQueue(ws);
			} catch {}
			startPing();
		};

		ws.onmessage = (ev) => {
			try {
				if (decode) {
					// Allow custom decoding before passing to handler
					const decoded = decode(ev);
					// Provide decoded payload as ev.decoded for convenience if needed
					// @ts-expect-error
					ev.decoded = decoded;
				}
			} catch {}
			try {
				onMessage?.(ev, ws);
			} catch {}
		};

		ws.onclose = (ev) => {
			stopPing();
			try {
				onClose?.(ev, { attempts });
			} catch {}
			scheduleReconnect();
		};

		ws.onerror = (ev) => {
			try {
				onError?.(ev);
			} catch {}
		};

		return api;
	}

	function send(payload) {
		const data = encode(payload);
		if (ws && ws.readyState === WebSocket.OPEN) {
			try {
				ws.send(data);
				return true;
			} catch {
				// Enqueue on failure
			}
		}
		// Not open: enqueue
		if (queue.length >= queueLimit) {
			// Drop oldest to keep the most recent messages
			queue.shift();
		}
		queue.push(payload);
		// If lazy, trigger connection on first send
		if (lazy && (!ws || ws.readyState === WebSocket.CLOSED)) {
			connect();
		}
		return false;
	}

	/**
	 * Close the socket
	 * @param {{code?: number, reason?: string, reconnect?: boolean}} [opts]
	 */
	function close(opts = {}) {
		const { code, reason, reconnect = false } = opts;
		shouldReconnect = !!reconnect;
		clearTimers();
		stopPing();
		try {
			ws?.close(code ?? 1000, reason ?? "bye");
		} catch {}
		return api;
	}

	function destroy() {
		shouldReconnect = false;
		clearTimers();
		stopPing();
		try {
			ws?.close(1000, "destroy");
		} catch {}
		ws = null;
		queue.splice(0, queue.length);
		return api;
	}

	function connectIfNeeded() {
		if (!ws || ws.readyState === WebSocket.CLOSED) connect();
		return api;
	}

	// Public API
	const api = {
		connect,
		connectIfNeeded,
		send,
		close,
		destroy,
		setHandlers,
		setUrl,
		isOpen: () => ws != null && ws.readyState === WebSocket.OPEN,
		getReadyState: () => readyStateString(ws || undefined),
		getAttempts: () => attempts,
		getBackoffWait: () => Math.min(maxMs, baseMs * 2 ** attempts),
		socket: () => ws,
	};

	// Auto-connect unless explicitly lazy
	if (!lazy) connect();

	return api;
}
