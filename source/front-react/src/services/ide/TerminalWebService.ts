import { USE_MOCKS } from "@/config";
import { MockTerminalWebService } from "@/mocks/terminal";

class TerminalWebService {
	private ws: WebSocket | null = null;
	private connected = false;
	private readonly url: string;
	private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	private reconnectAttempts = 0;
	private manualClose = false;
	private messageHandler: ((event: MessageEvent) => void) | null = null;
	// Last known PTY geometry, re-sent on every (re)connect because the upstream
	// shell is recreated at the default size on a fresh connection.
	private lastResize: string | null = null;

	constructor(containerId: string, sid: string) {
		const proto = location.protocol === "https:" ? "wss" : "ws";
		this.url = `${proto}://${location.host}/ws/containers/${containerId}/?sid=${encodeURIComponent(sid)}`;
		this.openSocket();
	}

	private openSocket() {
		if (this.ws) {
			const state = this.ws.readyState;
			if (state === WebSocket.OPEN || state === WebSocket.CONNECTING) {
				return;
			}
		}
		this.manualClose = false;
		this.clearReconnectTimer();
		this.ws = new WebSocket(this.url);
		this.ws.binaryType = "arraybuffer";

		this.ws.onopen = () => {
			console.log("Terminal WS connected");
			this.connected = true;
			this.reconnectAttempts = 0;
			// Re-apply the terminal size to the freshly created upstream shell.
			if (this.lastResize) {
				try {
					this.ws?.send(this.lastResize);
				} catch (error) {
					console.error("terminal resize resend failed", error);
				}
			}
		};

		this.ws.onmessage = (event) => {
			if (this.messageHandler) {
				this.messageHandler(event);
			}
		};

		this.ws.onerror = (e) => {
			console.error("Terminal WS error:", e);
		};

		this.ws.onclose = (event) => {
			this.connected = false;
			this.ws = null;
			console.log("Terminal WS closed:", event.reason);
			if (!this.manualClose) {
				this.scheduleReconnect();
			}
		};
	}

	public send(payload: string | ArrayBuffer) {
		if (this.ws?.readyState !== WebSocket.OPEN) {
			return false;
		}
		this.ws.send(payload);
		return true;
	}

	// Propagate the xterm geometry to the upstream PTY so TUIs (vim, htop, less)
	// and line wrapping match the visible terminal. The backend parses the
	// "__RESIZE__<cols>x<rows>" control frame and calls chan.resize_pty.
	public sendResize(cols: number, rows: number) {
		if (!Number.isFinite(cols) || !Number.isFinite(rows) || cols <= 0 || rows <= 0) {
			return;
		}
		const frame = `__RESIZE__${Math.floor(cols)}x${Math.floor(rows)}`;
		if (this.lastResize === frame) {
			return;
		}
		this.lastResize = frame;
		if (this.ws?.readyState === WebSocket.OPEN) {
			this.ws.send(frame);
		}
	}

	public close() {
		this.manualClose = true;
		this.clearReconnectTimer();
		this.ws?.close();
		this.ws = null;
	}

	public onMessage(callback: (e: MessageEvent) => void) {
		this.messageHandler = callback;
		if (this.ws) {
			this.ws.onmessage = callback;
		}
	}

	public isConnected() {
		return this.connected && this.ws?.readyState === WebSocket.OPEN;
	}

	public hasConnection() {
		return this.ws !== null;
	}

	private scheduleReconnect() {
		if (this.manualClose || this.reconnectTimer != null) {
			return;
		}
		const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 5000);
		this.reconnectAttempts += 1;
		this.reconnectTimer = setTimeout(() => {
			this.reconnectTimer = null;
			this.openSocket();
		}, delay);
	}

	private clearReconnectTimer() {
		if (this.reconnectTimer != null) {
			clearTimeout(this.reconnectTimer);
			this.reconnectTimer = null;
		}
	}
}

const TerminalServiceExport = USE_MOCKS ? MockTerminalWebService : TerminalWebService;

export default TerminalServiceExport;
