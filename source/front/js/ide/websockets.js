import { createWSBase } from "../core/ws.js";
export function createWS(
	containerId,
	{ onOpen, onMessage, onClose, onError } = {},
) {
	const proto = location.protocol === "https:" ? "wss" : "ws";
	const wsUrl = `${proto}://${location.host}/ws/containers/${containerId}/`;
	const sock = createWSBase(wsUrl, {
		binaryType: "arraybuffer",
		onOpen,
		onMessage,
		onClose: () => onClose?.(),
		onError,
	});
	return {
		send: (payload) => {
			sock.send(payload);
		},
		close: () => {
			sock.close();
		},
	};
}
