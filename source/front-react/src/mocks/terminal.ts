type MessageListener = (event: MessageEvent) => void;

function createMessage(data: string | ArrayBuffer): MessageEvent {
	return {
		data,
	} as MessageEvent;
}

export class MockTerminalWebService {
	private listener: MessageListener | null = null;
	private closed = false;
	private readonly prefix: string;
	private connected = false;

	constructor(containerId: string, sid: string) {
		this.prefix = `[mock ${containerId} ${sid}]`;
		setTimeout(() => {
			if (!this.closed) {
				this.connected = true;
			}
			if (!this.closed && this.listener) {
				this.listener(createMessage(`${this.prefix} Terminal session ready\r\n$ `));
			}
		}, 10);
	}

	public send(payload: string | ArrayBuffer) {
		if (this.closed || !this.listener) return;
		if (typeof payload === "string") {
			const trimmed = payload.replace(/\r?\n/g, "").trim();
			const echo = trimmed ? `${this.prefix} you typed: ${trimmed}\r\n$ ` : "$ ";
			setTimeout(() => {
				this.listener?.(createMessage(`\r\n${echo}`));
			}, 50);
			return;
		}
		this.listener(createMessage("\r\n[mock terminal received binary data]\r\n$ "));
	}

	public close() {
		this.closed = true;
		this.connected = false;
		this.listener = null;
	}

	public onMessage(callback: MessageListener) {
		this.listener = callback;
	}

	public isConnected() {
		return this.connected && !this.closed;
	}

	public hasConnection() {
		return this.isConnected();
	}
}
