import { USE_MOCKS } from "@/config";
import {
	mockApplyTemplate,
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
	const sanitized = rawPath.replace(/^\//, "");
	const encoded = sanitized ? `/${encodeURIComponent(sanitized)}/` : "/";
	const base = `/api/containers/${containerId}/curl/${port}`;
	const url = `${base}${encoded}`;
	const u = new URL(url, window.location.href);
	u.searchParams.set("_cb", String(Date.now()));
	return u.toString();
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
