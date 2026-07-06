import { buildAppUrl } from "@/lib/appBase";

/**
 * Message contract between the standalone `/browser` page (which always runs
 * inside an iframe when embedded) and its host dock (IDE / AiStudio).
 *
 * The page lives in a same-origin iframe, so it cannot resize the host panel
 * directly — it asks the host to close or to toggle fullscreen via `postMessage`.
 * The host verifies `event.origin` before trusting anything.
 */
export const BROWSER_DOCK_MESSAGE = "pequeroku-browser" as const;

export type BrowserDockMessage =
	| { source: typeof BROWSER_DOCK_MESSAGE; type: "close" }
	| { source: typeof BROWSER_DOCK_MESSAGE; type: "expand"; expanded: boolean };

export function isBrowserDockMessage(data: unknown): data is BrowserDockMessage {
	if (typeof data !== "object" || data === null) return false;
	const record = data as Record<string, unknown>;
	if (record.source !== BROWSER_DOCK_MESSAGE) return false;
	return record.type === "close" || record.type === "expand";
}

/** Post a dock message to the host window (no-op when not embedded). */
export function postBrowserDockMessage(message: BrowserDockMessage): void {
	if (typeof window === "undefined" || window.parent === window) return;
	window.parent.postMessage(message, window.location.origin);
}

/** True when this document is embedded inside a host frame (the dock). */
export function isEmbeddedInDock(): boolean {
	return typeof window !== "undefined" && window.parent !== window;
}

/** Build the `/browser` route URL used as the dock iframe `src`. */
export function buildBrowserSrc(
	containerId: string,
	options: { port?: number | null; path?: string } = {},
): string {
	const params = new URLSearchParams({ containerId: String(containerId) });
	if (options.port != null) params.set("port", String(options.port));
	if (options.path) params.set("path", options.path);
	return buildAppUrl(`browser?${params.toString()}`);
}
