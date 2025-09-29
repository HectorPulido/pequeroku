import { FSWS } from "../core/constants.js";
import { createWSBase } from "../core/ws.js";

export function createFSWS({ containerPk, onBroadcast, onOpen }) {
	const proto = location.protocol === "https:" ? "wss" : "ws";
	const url = `${proto}://${location.host}/ws/fs/${containerPk}/`;

	let nextId = 1;
	const pending = new Map();
	const revs = new Map();

	const sock = createWSBase(url, {
		onOpen: () => {
			onOpen?.();
		},
		onMessage: (e) => {
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
		},
		onError: (e) => {
			console.error("FS WS error:", e);
		},
	});

	function waitOpenAndCall(action, payload) {
		return new Promise((resolve, reject) => {
			const id = setInterval(() => {
				if (sock.isOpen()) {
					clearInterval(id);
					call(action, payload).then(resolve, reject);
				}
			}, FSWS.waitOpenIntervalMs);
			// failsafe in case it never opens
			setTimeout(() => {
				clearInterval(id);
				reject(new Error(`timeout waiting WS open for ${action}`));
			}, FSWS.openTimeoutMs);
		});
	}

	function call(action, payload = {}) {
		if (!sock.isOpen()) {
			return waitOpenAndCall(action, payload);
		}
		const req_id = nextId++;
		const msg = { action, req_id, ...payload };
		sock.send(msg);
		return new Promise((resolve, reject) => {
			pending.set(req_id, { resolve, reject });
			setTimeout(() => {
				if (pending.has(req_id)) {
					pending.delete(req_id);
					reject(new Error(`timeout calling ${action}`));
				}
			}, FSWS.callTimeoutMs);
		});
	}

	// Search files in container via WS
	async function search({ pattern, root = "/app" }) {
		const res = await call("search", { root, pattern });
		let list = [];
		if (Array.isArray(res)) {
			list = res;
		} else if (Array.isArray(res?.results)) {
			list = res.results;
		} else if (res && typeof res === "object") {
			list = Object.values(res).flat().filter(Boolean);
		}
		return list.map((item) => {
			const path = String(item?.path || item?.file || "");
			const matches =
				(Array.isArray(item?.matchs) && item.matchs) ||
				(Array.isArray(item?.matches) && item.matches) ||
				[];
			return { path, matches };
		});
	}

	return {
		call,
		revs,
		search,
	};
}
