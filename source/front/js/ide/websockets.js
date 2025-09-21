export function createWS(
	containerId,
	{ onOpen, onMessage, onClose, onError } = {},
) {
	let ws;
	let attempts = 0;
	const maxBackoff = 8000;
	const proto = location.protocol === "https:" ? "wss" : "ws";
	const wsUrl = `${proto}://${location.host}/ws/containers/${containerId}/`;
	const queue = [];

	function encodePayload(payload) {
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

	function flush(socket) {
		while (queue.length) {
			const p = queue.shift();
			const data = encodePayload(p);
			try {
				socket.send(data);
			} catch {}
		}
	}

	function connect() {
		ws = new WebSocket(wsUrl);
		ws.binaryType = "arraybuffer";
		ws.onopen = () => {
			attempts = 0;
			flush(ws);
			onOpen?.(ws);
		};
		ws.onmessage = (ev) => onMessage?.(ev, ws);
		ws.onclose = () => {
			onClose?.();
			const wait = Math.min(maxBackoff, 500 * 2 ** attempts++);
			setTimeout(connect, wait);
		};
		ws.onerror = (e) => onError?.(e);
	}
	connect();

	function send(payload) {
		const data = encodePayload(payload);
		if (ws && ws.readyState === 1) ws.send(data);
		else queue.push(payload);
	}
	function close() {
		try {
			ws?.close(1000, "bye");
		} catch {}
	}

	return { send, close };
}
