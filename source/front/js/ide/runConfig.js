import { notifyAlert } from "../core/alerts.js";

export async function loadRunConfig(api) {
	let runCommand = null;
	const path = "/app/config.json";
	try {
		const { content } = await api(
			`/read_file/?path=${encodeURIComponent(path)}`,
		);
		try {
			const cfg = JSON.parse(content);
			if (cfg && typeof cfg.run === "string" && cfg.run.trim()) {
				runCommand = cfg.run.trim();
			}
		} catch {
			notifyAlert("config.json is not valid", "warning");
		}
	} catch {}
	return runCommand;
}
