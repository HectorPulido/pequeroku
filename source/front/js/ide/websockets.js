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

	function flush(socket) {
		while (queue.length) socket.send(queue.shift());
	}

	function connect() {
		ws = new WebSocket(wsUrl);
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
		const msg = payload;
		if (ws && ws.readyState === 1) ws.send(msg);
		else queue.push(msg);
	}
	function close() {
		try {
			ws?.close(1000, "bye");
		} catch {}
	}

	return { send, close };
}
