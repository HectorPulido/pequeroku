import { createWSBase } from "../core/ws.js";
export function createWS(
	containerId,
	{ sid = "s1", onOpen, onMessage, onClose, onError } = {},
) {
	const proto = location.protocol === "https:" ? "wss" : "ws";
	const wsUrl = `${proto}://${location.host}/ws/containers/${containerId}/?sid=${encodeURIComponent(sid)}`;
	const sock = createWSBase(wsUrl, {
		binaryType: "arraybuffer",
		onOpen: (ws) => onOpen?.(ws, { sid }),
		onMessage: (ev, ws) => onMessage?.(ev, ws, { sid }),
		onClose: (ev, info) => onClose?.(ev, info, { sid }),
		onError: (ev) => onError?.(ev, { sid }),
	});
	return {
		sid,
		send: (payload) => {
			// Send raw keystrokes (text) or binary buffers directly.
			if (payload instanceof ArrayBuffer || ArrayBuffer.isView?.(payload)) {
				sock.send(payload);
			} else {
				sock.send(String(payload ?? ""));
			}
		},
		close: (opts) => {
			// Allow passing close options through to helper (code, reason, reconnect)
			try {
				if (opts && typeof opts === "object") {
					sock.close(opts);
				} else {
					sock.close();
				}
			} catch {
				sock.close();
			}
		},
		isOpen: () => sock.isOpen(),
	};
}
