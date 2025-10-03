import { notifyAlert } from "../core/alerts.js";

export async function loadRunConfig(api) {
	let run = null;
	let port = null;
	const path = "/app/config.json";
	try {
		const { content } = await api(
			`/read_file/?path=${encodeURIComponent(path)}`,
		);
		try {
			const cfg = JSON.parse(content);
			if (cfg && typeof cfg.run === "string" && cfg.run.trim()) {
				run = cfg.run.trim();
			}
			if (
				cfg &&
				(typeof cfg.port === "number" || typeof cfg.port === "string")
			) {
				const p = parseInt(String(cfg.port), 10);
				if (!Number.isNaN(p) && p > 0 && p < 65536) {
					port = p;
				}
			}
		} catch {
			notifyAlert("config.json is not valid", "warning");
		}
	} catch {}

	return { run, port };
}
