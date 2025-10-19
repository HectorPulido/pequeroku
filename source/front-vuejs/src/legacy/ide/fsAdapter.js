/**
 * FS Adapter for editor and config readers.
 *
 * Provides an API-like wrapper compatible with modules that expect to call:
 *   api(`/read_file/?path=${encodeURIComponent(path)}`)
 * and receive a `{ content: string }` response.
 *
 * It uses the FS WebSocket bridge (fsws) to read files and records the latest
 * server-side revision number in `fsws.revs` (if available), so saving logic
 * can perform conflict detection.
 */

/**
 * Extract file path from a read_file style URL.
 * Examples:
 *   "/read_file/?path=%2Fapp%2Fmain.js" => "/app/main.js"
 *   new URL("http://x/read_file/?path=/app/a.txt") => "/app/a.txt"
 *
 * @param {string | URL} url
 * @returns {string} path
 */
export function extractPathFromReadUrl(url) {
	const s = String(url || "");
	const qs = new URLSearchParams(s.split("?")[1] || "");
	const path = qs.get("path");
	if (!path) throw new Error("Missing 'path' query parameter");
	return path;
}

/**
 * Create a read_file API wrapper compatible with existing editor/config code.
 *
 * Usage:
 *   const apiReadFile = createReadFileApi(fsws);
 *   const { content } = await apiReadFile(`/read_file/?path=${encodeURIComponent("/app/main.js")}`);
 *
 * Behavior:
 * - Calls fsws.call("read_file", { path })
 * - If a numeric `rev` is returned, stores it in `fsws.revs` map
 * - Returns `{ content: string }`
 *
 * @param {{ call: (method: string, payload: any) => Promise<any>, revs?: Map<string, number> }} fsws
 * @returns {(url: string | URL) => Promise<{ content: string }>}
 */
export function createReadFileApi(fsws) {
	if (!fsws || typeof fsws.call !== "function") {
		throw new Error("Invalid fsws passed to createReadFileApi");
	}

	return async (url) => {
		const path = extractPathFromReadUrl(url);
		const data = await fsws.call("read_file", { path });

		// Persist server revision for conflict detection if the map exists
		if (
			data &&
			typeof data.rev === "number" &&
			fsws.revs &&
			typeof fsws.revs.set === "function"
		) {
			fsws.revs.set(path, data.rev);
		}

		return { content: data?.content ?? "" };
	};
}

/**
 * Convenience helper to read a file by path (bypassing the URL wrapper), while still
 * updating fsws.revs.
 *
 * @param {{ call: (method: string, payload: any) => Promise<any>, revs?: Map<string, number> }} fsws
 * @param {string} path
 * @returns {Promise<{ content: string, rev?: number }>}
 */
export async function readFileAndTrackRev(fsws, path) {
	if (!fsws || typeof fsws.call !== "function") {
		throw new Error("Invalid fsws passed to readFileAndTrackRev");
	}
	const data = await fsws.call("read_file", { path });
	if (
		data &&
		typeof data.rev === "number" &&
		fsws.revs &&
		typeof fsws.revs.set === "function"
	) {
		fsws.revs.set(path, data.rev);
	}
	return {
		content: data?.content ?? "",
		rev: typeof data?.rev === "number" ? data.rev : undefined,
	};
}
