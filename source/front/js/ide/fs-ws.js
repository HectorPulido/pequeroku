export function createFSWS({ containerPk, onBroadcast, onOpen }) {
	const proto = location.protocol === "https:" ? "wss" : "ws";
	const url = `${proto}://${location.host}/ws/fs/${containerPk}/`;

	let ws;
	let nextId = 1;
	const pending = new Map();
	const revs = new Map();
	let attempts = 0;
	const maxBackoff = 8000;

	function connect() {
		ws = new WebSocket(url);

		ws.onopen = () => {
			attempts = 0;
			onOpen?.();
		};

		ws.onmessage = (e) => {
			try {
				const msg = JSON.parse(e.data);

				if (msg.event === "ok") {
					const { req_id, data, rev } = msg;
					// If the backend included `data.path` here, we could cache its rev
					if (rev != null && (data?.path || data?.dst)) {
						const key = data.path || data.dst;
						revs.set(String(key), Number(rev));
					}
					const p = pending.get(req_id);
					if (p) {
						pending.delete(req_id);
						p.resolve(data);
					}
					return;
				}

				if (msg.event === "error") {
					const p = pending.get(msg.req_id);
					if (p) {
						pending.delete(msg.req_id);
						p.reject(new Error(msg.error || "WS error"));
					}
					return;
				}

				if (msg.event === "connected") {
					// listo para usar
					return;
				}

				// Broadcasts del server: file_changed, path_moved, path_deleted
				onBroadcast?.(msg);
				if (msg.rev != null && (msg.path || msg.dst)) {
					const key = msg.path || msg.dst;
					revs.set(String(key), Number(msg.rev));
				}
			} catch (err) {
				console.error("FS WS parse error:", err);
			}
		};

		ws.onclose = () => {
			const wait = Math.min(maxBackoff, 500 * 2 ** attempts++);
			setTimeout(connect, wait);
		};

		ws.onerror = (e) => {
			console.error("FS WS error:", e);
		};
	}

	connect();

	function waitOpenAndCall(action, payload) {
		return new Promise((resolve, reject) => {
			const id = setInterval(() => {
				if (ws && ws.readyState === WebSocket.OPEN) {
					clearInterval(id);
					call(action, payload).then(resolve, reject);
				}
			}, 100);
			// failsafe in case it never opens
			setTimeout(() => {
				clearInterval(id);
				reject(new Error(`timeout waiting WS open for ${action}`));
			}, 20000);
		});
	}

	function call(action, payload = {}) {
		if (!ws || ws.readyState !== WebSocket.OPEN) {
			return waitOpenAndCall(action, payload);
		}
		const req_id = nextId++;
		const msg = { action, req_id, ...payload };
		ws.send(JSON.stringify(msg));
		return new Promise((resolve, reject) => {
			pending.set(req_id, { resolve, reject });
			setTimeout(() => {
				if (pending.has(req_id)) {
					pending.delete(req_id);
					reject(new Error(`timeout calling ${action}`));
				}
			}, 20000);
		});
	}

	return {
		call,
		revs,
	};
}
