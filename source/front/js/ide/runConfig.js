import { notifyAlert } from "../core/alerts.js";

export async function loadRunConfig(api) {
	let run = null;
	let url = null;
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
			if (cfg && typeof cfg.url === "string" && cfg.url.trim()) {
				url = cfg.url.trim();
			}
		} catch {
			notifyAlert("config.json is not valid", "warning");
		}
	} catch {}
	return { run, url };
}
