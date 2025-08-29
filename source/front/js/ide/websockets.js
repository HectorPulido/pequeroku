export function createWS(containerId, { onOpen, onMessage, onClose, onError }) {
	let ws,
		attempts = 0;
	const maxBackoff = 8000;
	const proto = location.protocol === "https:" ? "wss" : "ws";
	const wsUrl = `${proto}://${location.host}/ws/containers/${containerId}/`;

	function connect() {
		ws = new WebSocket(wsUrl);
		ws.onopen = () => {
			attempts = 0;
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
		const msg =
			typeof payload === "string"
				? JSON.stringify({ action: "cmd", data: payload })
				: JSON.stringify(payload);
		if (ws && ws.readyState === 1) ws.send(msg);
		else queue.push(msg);
	}
	const queue = [];
	const handleOpen = (socket) => {
		while (queue.length) socket.send(queue.shift());
	};
	if (!onOpen) onOpen = handleOpen;

	return { send };
}
