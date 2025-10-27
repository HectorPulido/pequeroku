import { USE_MOCKS } from "@/config";
import { FSWS } from "@/constants";
import { MockFileSystemWebService } from "@/mocks/ide";

type OkMessage = {
	event: "ok";
	req_id: number;
	data?: unknown;
	rev?: unknown;
};

type ErrorMessage = {
	event: "error";
	req_id: number;
	error?: string;
};

type BroadcastMessage = Record<string, unknown>;
type WsMessage = OkMessage | ErrorMessage | BroadcastMessage;
type PendingRequest = {
	resolve: (data: unknown) => void;
	reject: (error: Error) => void;
	action: string;
	payload: Record<string, unknown>;
};

export type FileSystemSearchMatch = {
	line: number;
	preview: string;
};

export type FileSystemSearchResult = {
	path: string;
	matches: FileSystemSearchMatch[];
};

export interface FileSystemSearchOptions {
	pattern: string;
	root?: string;
	includeGlobs?: string;
	excludeDirs?: string;
	caseSensitive?: boolean;
}

class FileSystemWebService {
	private readonly url: string;
	private ws: WebSocket | null = null;
	private nextId = 1;
	private pending = new Map<number, PendingRequest>();
	private broadcastListeners = new Set<(message: BroadcastMessage) => void>();
	public readonly revs = new Map<string, number>();
	private reconnectTimer: number | null = null;
	private reconnectAttempts = 0;
	private manualClose = false;

	constructor(containerPk: string) {
		const proto = location.protocol === "https:" ? "wss" : "ws";
		this.url = `${proto}://${location.host}/ws/fs/${containerPk}/`;
		this.openSocket();
	}

	private openSocket() {
		if (this.ws) {
			const state = this.ws.readyState;
			if (
				state === WebSocket.OPEN ||
				state === WebSocket.CONNECTING ||
				state === WebSocket.CLOSING
			) {
				return;
			}
		}
		this.manualClose = false;
		this.clearReconnectTimer();
		this.ws = new WebSocket(this.url);

		this.ws.onopen = () => {
			console.log("FS WS connected");
			this.reconnectAttempts = 0;
		};

		this.ws.onmessage = (event) => {
			try {
				const parsed: WsMessage | null = JSON.parse(event.data);
				if (!parsed || typeof parsed !== "object") {
					return;
				}

				const eventType = "event" in parsed ? parsed.event : undefined;

				if (eventType === "ok") {
					const reqId = "req_id" in parsed ? Number(parsed.req_id) : Number.NaN;
					const pendingRequest = Number.isFinite(reqId) ? this.pending.get(reqId) : undefined;
					if (pendingRequest) {
						const okMessage = parsed as OkMessage;
						this.pending.delete(reqId);
						this.trackRevisionFromResponse(
							pendingRequest.action,
							pendingRequest.payload,
							okMessage,
						);
						pendingRequest.resolve(okMessage.data);
					}
					return;
				}

				if (eventType === "error") {
					const reqId = "req_id" in parsed ? Number(parsed.req_id) : Number.NaN;
					const pendingRequest = Number.isFinite(reqId) ? this.pending.get(reqId) : undefined;
					if (pendingRequest) {
						this.pending.delete(reqId);
						const rawError = (parsed as ErrorMessage).error;
						const message = typeof rawError === "string" ? rawError : "WS error";
						pendingRequest.reject(new Error(message));
					}
					return;
				}

				const broadcast = parsed as BroadcastMessage;
				this.trackRevisionFromBroadcast(broadcast);
				this.emitBroadcast(broadcast);
			} catch (err) {
				console.error("FS WS parse error:", err);
			}
		};

		this.ws.onerror = (e) => {
			console.error("FS WS error:", e);
		};

		this.ws.onclose = () => {
			this.ws = null;
			this.failAllPending(new Error("filesystem websocket closed"));
			if (!this.manualClose) {
				this.scheduleReconnect();
			}
		};
	}

	private scheduleReconnect() {
		if (this.manualClose || this.reconnectTimer != null) {
			return;
		}
		const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 5000);
		this.reconnectAttempts += 1;
		this.reconnectTimer = window.setTimeout(() => {
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

	private failAllPending(error: Error) {
		if (this.pending.size === 0) return;
		this.pending.forEach((request) => {
			try {
				request.reject(error);
			} catch (rejectError) {
				console.error("FS WS pending reject error:", rejectError);
			}
		});
		this.pending.clear();
	}

	private static normalizeAction(action: string): string {
		switch (action) {
			case "read":
				return "read_file";
			case "write":
				return "write_file";
			default:
				return action;
		}
	}

	private preparePayload(
		action: string,
		payload: Record<string, unknown>,
	): Record<string, unknown> {
		if (action !== "write_file") {
			return { ...payload };
		}
		const rawPath = "path" in payload ? payload.path : undefined;
		const path = typeof rawPath === "string" ? rawPath : "";
		const prevRev = this.revs.get(path) ?? 0;
		return {
			...payload,
			...(path ? { path } : {}),
			prev_rev: prevRev,
		};
	}

	private callInternal<T = unknown>(
		action: string,
		payload: Record<string, unknown>,
		originalAction: string,
	): Promise<T> {
		if (!this.ws) {
			return Promise.reject(new Error("filesystem websocket not available"));
		}
		const req_id = this.nextId++;
		const msg = { action, req_id, ...payload };
		this.ws.send(JSON.stringify(msg));
		return new Promise<T>((resolve, reject) => {
			this.pending.set(req_id, {
				resolve: (data: unknown) => resolve(data as T),
				reject,
				action,
				payload,
			});
			// TODO, this is always being called
			setTimeout(() => {
				if (this.pending.has(req_id)) {
					this.pending.delete(req_id);
					reject(new Error(`timeout calling ${originalAction}`));
				}
			}, FSWS.callTimeoutMs);
		});
	}

	private waitOpenAndCall<T>(
		action: string,
		payload: Record<string, unknown>,
		originalAction: string,
	): Promise<T> {
		this.openSocket();
		return new Promise<T>((resolve, reject) => {
			const tryResolve = () => {
				if (!this.ws) {
					this.openSocket();
					return;
				}
				if (this.ws.readyState !== WebSocket.OPEN) {
					return;
				}
				clearInterval(intervalId);
				clearTimeout(timeoutId);
				this.callInternal<T>(action, payload, originalAction).then(resolve).catch(reject);
			};

			const intervalId = setInterval(tryResolve, FSWS.waitOpenIntervalMs);
			const timeoutId = setTimeout(() => {
				clearInterval(intervalId);
				reject(new Error(`timeout waiting WS open for ${originalAction}`));
			}, FSWS.openTimeoutMs);
			this.openSocket();
			tryResolve();
		});
	}

	public call<T = unknown>(action: string, payload: Record<string, unknown> = {}): Promise<T> {
		const normalizedAction = FileSystemWebService.normalizeAction(action);
		const preparedPayload = this.preparePayload(normalizedAction, payload);
		this.openSocket();
		if (!this.ws) {
			return Promise.reject(new Error("filesystem websocket not initialized"));
		}
		if (this.ws.readyState !== WebSocket.OPEN) {
			return this.waitOpenAndCall<T>(normalizedAction, preparedPayload, action);
		}
		return this.callInternal<T>(normalizedAction, preparedPayload, action);
	}

	public close() {
		this.manualClose = true;
		this.clearReconnectTimer();
		this.broadcastListeners.clear();
		this.failAllPending(new Error("filesystem websocket closed"));
		this.revs.clear();
		if (this.ws) {
			try {
				this.ws.close();
			} catch (error) {
				console.error("FS WS close error:", error);
			}
		}
		this.ws = null;
	}

	public onBroadcast(listener: (message: BroadcastMessage) => void): () => void {
		this.broadcastListeners.add(listener);
		return () => {
			this.broadcastListeners.delete(listener);
		};
	}

	public async search(options: FileSystemSearchOptions): Promise<FileSystemSearchResult[]> {
		const payload = {
			root: options.root ?? "/app",
			pattern: options.pattern,
			include_globs: options.includeGlobs ?? "",
			exclude_dirs: options.excludeDirs ?? "",
			// Backend expects `"true"` to mean case-insensitive (legacy quirk)
			case: options.caseSensitive ? "false" : "true",
		};
		const response = await this.call("search", payload);
		return FileSystemWebService.normalizeSearchResults(response);
	}

	private trackRevisionFromResponse(
		action: string,
		payload: Record<string, unknown>,
		message: OkMessage,
	) {
		if (action !== "write_file" && action !== "read_file" && action !== "move_path") {
			return;
		}
		const explicitRev = FileSystemWebService.extractRev(message);
		const pathFromMessage = FileSystemWebService.extractPath(message);
		const pathFromPayload = FileSystemWebService.extractPath(payload);
		const targetPath = pathFromMessage ?? pathFromPayload;
		if (!targetPath) return;

		if (action === "write_file") {
			const prevRev =
				typeof payload.prev_rev === "number" ? payload.prev_rev : (this.revs.get(targetPath) ?? 0);
			const nextRev = explicitRev ?? prevRev + 1;
			this.revs.set(targetPath, nextRev);
			return;
		}

		if (explicitRev != null) {
			this.revs.set(targetPath, explicitRev);
		}
	}

	private trackRevisionFromBroadcast(message: BroadcastMessage) {
		const explicitRev = FileSystemWebService.extractRev(message);
		if (explicitRev == null) return;
		const path = FileSystemWebService.extractPath(message);
		if (!path) return;
		this.revs.set(path, explicitRev);
	}

	private static extractRev(input: Record<string, unknown>): number | null {
		const topLevel = "rev" in input ? input.rev : undefined;
		const topLevelNumber =
			typeof topLevel === "number"
				? topLevel
				: typeof topLevel === "string"
					? Number.parseInt(topLevel, 10)
					: Number.NaN;
		if (Number.isFinite(topLevelNumber)) {
			return topLevelNumber;
		}
		if ("data" in input && input.data && typeof input.data === "object") {
			const dataRaw = (input.data as { rev?: unknown }).rev;
			const dataNumber =
				typeof dataRaw === "number"
					? dataRaw
					: typeof dataRaw === "string"
						? Number.parseInt(dataRaw, 10)
						: Number.NaN;
			if (Number.isFinite(dataNumber)) {
				return dataNumber;
			}
		}
		return null;
	}

	private static extractPath(input: Record<string, unknown>): string | null {
		if ("data" in input && input.data && typeof input.data === "object") {
			const data = input.data as Record<string, unknown>;
			const pathValue =
				typeof data.path === "string"
					? data.path
					: typeof data.dst === "string"
						? data.dst
						: undefined;
			if (typeof pathValue === "string" && pathValue) {
				return pathValue;
			}
		}
		const pathValue =
			typeof input.path === "string"
				? input.path
				: typeof input.dst === "string"
					? input.dst
					: undefined;
		if (typeof pathValue === "string" && pathValue) {
			return pathValue;
		}
		const rawPayload = input as { payload?: Record<string, unknown> };
		if (rawPayload?.payload) {
			const nested = FileSystemWebService.extractPath(rawPayload.payload);
			if (nested) return nested;
		}
		return null;
	}

	private emitBroadcast(message: BroadcastMessage) {
		if (this.broadcastListeners.size === 0) return;
		this.broadcastListeners.forEach((listener) => {
			try {
				listener(message);
			} catch (error) {
				console.error("FS WS listener error:", error);
			}
		});
	}

	private static normalizeSearchResults(input: unknown): FileSystemSearchResult[] {
		const rawItems = FileSystemWebService.extractRawResults(input);
		return rawItems
			.map<FileSystemSearchResult | null>((item) => {
				if (!item || typeof item !== "object") return null;
				const pathValue = "path" in item ? item.path : undefined;
				const path = typeof pathValue === "string" ? pathValue : "";
				if (!path) return null;
				const matchArray =
					(Array.isArray((item as { matches?: unknown }).matches) &&
						(item as { matches: unknown[] }).matches) ||
					(Array.isArray((item as { matchs?: unknown }).matchs) &&
						(item as { matchs: unknown[] }).matchs) ||
					[];
				const matches = matchArray.map((entry) => {
					const raw = typeof entry === "string" ? entry : String(entry ?? "").trim();
					const trimmed = raw.trim();
					const match = trimmed.match(/^L(\d+):\s*(.*)$/);
					const line = match ? Number.parseInt(match[1] ?? "1", 10) : 1;
					const preview = match ? (match[2] ?? "") : trimmed;
					return { line: Number.isFinite(line) ? line : 1, preview };
				});

				return { path, matches };
			})
			.filter((item): item is FileSystemSearchResult => item !== null);
	}

	private static extractRawResults(input: unknown): unknown[] {
		if (Array.isArray(input)) return input;
		if (input && typeof input === "object") {
			if (Array.isArray((input as { results?: unknown[] }).results)) {
				return (input as { results: unknown[] }).results;
			}
			try {
				return Object.values(input).flat().filter(Boolean);
			} catch {
				return [];
			}
		}
		return [];
	}
}

const FileSystemServiceExport = USE_MOCKS ? MockFileSystemWebService : FileSystemWebService;

export default FileSystemServiceExport;
