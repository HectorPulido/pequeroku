import { USE_MOCKS } from "@/config";
import { MockTerminalWebService } from "@/mocks/terminal";

class TerminalWebService {
	private ws: WebSocket | null = null;
	private connected = false;

	constructor(containerId: string, sid: string) {
		const proto = location.protocol === "https:" ? "wss" : "ws";
		const url = `${proto}://${location.host}/ws/containers/${containerId}/?sid=${encodeURIComponent(sid)}`;
		this.ws = new WebSocket(url);

		this.ws.binaryType = "arraybuffer";

		this.ws.onopen = () => {
			console.log(`Terminal WS connected for sid=${sid}`);
			this.connected = true;
		};

		this.ws.onmessage = () => {
			// The listeners will be added directly to the terminal object
		};

		this.ws.onerror = (e) => {
			console.error(`Terminal WS error for sid=${sid}:`, e);
		};

		this.ws.onclose = (event) => {
			this.connected = false;
			console.log(`Terminal WS closed for sid=${sid}`, event.reason);
		};
	}

	public send(payload: string | ArrayBuffer) {
		if (this.ws?.readyState !== WebSocket.OPEN) {
			return false;
		}
		this.ws.send(payload);
		return true;
	}

	public close() {
		this.ws?.close();
	}

	public onMessage(callback: (e: MessageEvent) => void) {
		if (this.ws) {
			this.ws.onmessage = callback;
		}
	}

	public isConnected() {
		return this.connected && this.ws?.readyState === WebSocket.OPEN;
	}

	public hasConnection() {
		return this.isConnected();
	}
}

const TerminalServiceExport = USE_MOCKS ? MockTerminalWebService : TerminalWebService;

export default TerminalServiceExport;
