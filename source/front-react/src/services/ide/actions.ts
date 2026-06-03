import { USE_MOCKS } from "@/config";
import {
	mockApplyTemplate,
	mockFetchListeningPorts,
	mockFetchRunConfig,
	mockFetchTemplates,
	mockPollPreview,
	mockUploadFile,
} from "@/mocks/ide";
import { makeApi } from "@/services/api";
import FileSystemWebService from "@/services/ide/FileSystemWebService";
import type { TemplateSummary } from "@/types/template";

type RunConfig = {
	run: string | null;
	port: number | null;
};

export type ListeningPort = {
	port: number;
	address: string;
	process: string | null;
	pid: number | null;
};

type TemplateApplyResponse = {
	files_count?: number;
};

type PollPreviewOptions = {
	containerId: string;
	port: number;
	path: string;
	attempts?: number;
	delayMs?: number;
};

const containerApiCache = new Map<string, ReturnType<typeof makeApi>>();

function getContainerApi(containerId: string) {
	const normalized = String(containerId);
	let api = containerApiCache.get(normalized);
	if (!api) {
		api = makeApi(`/api/containers/${normalized}`);
		containerApiCache.set(normalized, api);
	}
	return api;
}

export async function uploadFile(containerId: string, file: File, destination: string) {
	const dest = destination?.trim() ? destination.trim() : "/app";
	if (USE_MOCKS) {
		return mockUploadFile(containerId, file, dest);
	}
	const api = getContainerApi(containerId);
	const form = new FormData();
	form.append("file", file);
	form.append("dest_path", dest);
	return api<{ dest?: string }>("/upload_file/", {
		method: "POST",
		body: form,
	});
}

export function buildDownloadUrl(containerId: string, path: string, type: "file" | "folder") {
	const normalized = path?.trim() ? path.trim() : "/app";
	const base = `/api/containers/${containerId}`;
	if (type === "folder") {
		return `${base}/download_folder/?root=${encodeURIComponent(normalized)}`;
	}
	return `${base}/download_file/?path=${encodeURIComponent(normalized)}`;
}

export async function fetchRunConfig(
	containerId: string,
	service?: InstanceType<typeof FileSystemWebService>,
): Promise<RunConfig> {
	if (USE_MOCKS) {
		return mockFetchRunConfig(containerId);
	}
	const localService = service ?? new FileSystemWebService(containerId);
	const shouldClose = !service;
	try {
		const response = await localService.call<{ content?: string }>("read_file", {
			path: "/app/config.json",
		});
		const content = typeof response?.content === "string" ? response.content : "";
		if (!content) {
			return { run: null, port: null };
		}
		const parsed = JSON.parse(content) as { run?: unknown; port?: unknown };
		const run = typeof parsed.run === "string" && parsed.run.trim() ? parsed.run.trim() : null;
		let port: number | null = null;
		if (typeof parsed.port === "number" && Number.isFinite(parsed.port)) {
			port = parsed.port;
		} else if (typeof parsed.port === "string" && parsed.port.trim()) {
			const value = Number.parseInt(parsed.port.trim(), 10);
			port = Number.isFinite(value) ? value : null;
		}
		return { run, port };
	} catch (error) {
		console.error("Failed to fetch run config", error);
		return { run: null, port: null };
	} finally {
		if (shouldClose) {
			localService.close();
		}
	}
}

export async function fetchListeningPorts(containerId: string): Promise<ListeningPort[]> {
	if (USE_MOCKS) {
		return mockFetchListeningPorts(containerId);
	}
	const api = getContainerApi(containerId);
	try {
		const ports = await api<Array<Record<string, unknown>>>("/ports/", {
			method: "GET",
			noLoader: true,
			noAuthRedirect: true,
			noAuthAlert: true,
		});
		return (ports || [])
			.map((raw): ListeningPort | null => {
				const port =
					typeof raw.port === "number" ? raw.port : Number.parseInt(String(raw.port ?? ""), 10);
				if (!Number.isFinite(port)) return null;
				return {
					port,
					address: typeof raw.address === "string" ? raw.address : "",
					process: typeof raw.process === "string" ? raw.process : null,
					pid: typeof raw.pid === "number" ? raw.pid : null,
				};
			})
			.filter((value): value is ListeningPort => value !== null);
	} catch (error) {
		// Read-only suggestion endpoint: a booting VM / unreachable node should not
		// surface an error — the caller treats an empty list as "nothing detected".
		console.warn("Failed to fetch listening ports", error);
		return [];
	}
}

export async function fetchTemplates(): Promise<TemplateSummary[]> {
	if (USE_MOCKS) {
		return mockFetchTemplates();
	}
	const api = makeApi("/api");
	const templates = await api<Array<Record<string, unknown>>>("/templates/", {
		method: "GET",
		noLoader: true,
		noAuthRedirect: true,
		noAuthAlert: true,
	});
	return (templates || []).map<TemplateSummary>((template, index) => {
		const rawId = (template as { id?: unknown }).id;
		let id: string;
		if (typeof rawId === "string" && rawId.trim()) {
			id = rawId.trim();
		} else if (typeof rawId === "number" && Number.isFinite(rawId)) {
			id = String(rawId);
		} else {
			id = `tpl-${index.toString()}`;
		}
		const name =
			typeof template.name === "string" && template.name ? template.name : "Unnamed template";
		const description = typeof template.description === "string" ? template.description : "";
		const destination =
			typeof template.destination === "string" && template.destination.trim()
				? template.destination.trim()
				: "/app";
		return { id, name, description, destination };
	});
}

export async function applyTemplate(
	templateId: string,
	options: { containerId: string; destPath: string; clean: boolean },
) {
	const { containerId, destPath, clean } = options;
	if (USE_MOCKS) {
		return mockApplyTemplate(templateId, { containerId, destPath, clean });
	}
	const api = makeApi("/api/templates");
	return api<TemplateApplyResponse>(`/${templateId}/apply/`, {
		method: "POST",
		body: JSON.stringify({
			container_id: Number.parseInt(containerId, 10),
			dest_path: destPath,
			clean,
		}),
	});
}

function buildPreviewUrl(containerId: string, port: number, rawPath: string) {
	// Real paths (no %2F encoding): the binary-safe proxy serves at this prefix and
	// the injected <base> resolves relative assets against it. No cache-buster —
	// the proxy passes through the app's real cache headers.
	const sanitized = rawPath.replace(/^\/+/, "");
	const base = `/api/containers/${containerId}/preview/${port}/`;
	return new URL(base + sanitized, window.location.href).toString();
}

export async function pollPreview(options: PollPreviewOptions) {
	const { containerId, port, path, attempts = 10, delayMs = 5000 } = options;
	if (!port) return null;

	if (USE_MOCKS) {
		return mockPollPreview(containerId, port, path);
	}

	const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
	await delay(delayMs);

	for (let i = 0; i < attempts; i += 1) {
		const url = buildPreviewUrl(containerId, port, path);
		try {
			const response = await fetch(url, {
				method: "GET",
				credentials: "same-origin",
			});
			if (response.status !== 200) {
				await delay(delayMs);
				continue;
			}
			const html = await response.text();
			if (html.trim().length < 10) {
				await delay(delayMs);
				continue;
			}
			return { url, html };
		} catch (error) {
			console.warn("Preview polling error", error);
			await delay(delayMs);
		}
	}
	return null;
}

export type { TemplateSummary };
