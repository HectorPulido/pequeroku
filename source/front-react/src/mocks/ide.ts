import type { TemplateSummary } from "@/types/template";

type EntryType = "file" | "folder";

type EntryRecord = {
	type: EntryType;
	content?: string;
};

type BroadcastEvent = Record<string, unknown>;

const DEFAULT_FS: Array<[string, EntryRecord]> = [
	["/app", { type: "folder" }],
	[
		"/app/readme.txt",
		{
			type: "file",
			content: "# PequeRoku Mock Project\n\nWelcome to the static prototype environment.\n",
		},
	],
	["/app/src", { type: "folder" }],
	[
		"/app/src/index.js",
		{
			type: "file",
			content: `import http from 'http';

const server = http.createServer((_, res) => {
  res.writeHead(200, { 'Content-Type': 'text/plain' });
  res.end('Hello from PequeRoku mock container!\\n');
});

server.listen(3000, () => {
  console.log('Server running at http://localhost:3000/');
});
`,
		},
	],
	["/app/src/components", { type: "folder" }],
	[
		"/app/src/components/App.tsx",
		{
			type: "file",
			content: `export function App() {
  return (
    <main>
      <h1>PequeRoku Mock IDE</h1>
      <p>Edit files to see autosave in action.</p>
    </main>
  );
}
`,
		},
	],
	[
		"/app/config.json",
		{
			type: "file",
			content: JSON.stringify({ run: "npm run dev", port: 3000 }, null, 2),
		},
	],
];

type TemplateDefinition = TemplateSummary & {
	files: Array<{ path: string; content: string }>;
};

const TEMPLATE_LIBRARY: Record<string, TemplateDefinition> = {
	fastapi: {
		id: "fastapi",
		name: "FastAPI Service",
		description: "Bootstraps a minimal FastAPI project structure with Poetry.",
		destination: "/app",
		files: [
			{
				path: "/app/main.py",
				content: `from fastapi import FastAPI

app = FastAPI()


@app.get("/")
async def read_root():
    return {"message": "Hello from FastAPI mock template"}
`,
			},
			{
				path: "/app/pyproject.toml",
				content: `[tool.poetry]
name = "fastapi-service"
version = "0.1.0"
description = "Mock FastAPI project"
authors = ["PequeRoku"]

[tool.poetry.dependencies]
python = "^3.11"
fastapi = "^0.110.0"
uvicorn = "^0.27.0"

[tool.poetry.scripts]
fastapi-service = "main:app"
`,
			},
			{
				path: "/app/config.json",
				content: JSON.stringify(
					{ run: "poetry run uvicorn main:app --reload", port: 8000 },
					null,
					2,
				),
			},
		],
	},
	react: {
		id: "react",
		name: "React SPA",
		description: "Creates a Vite + React starter inside the workspace.",
		destination: "/app/frontend",
		files: [
			{
				path: "/app/frontend/package.json",
				content: `{
  "name": "mock-react-spa",
  "private": true,
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  }
}
`,
			},
			{
				path: "/app/frontend/src/main.tsx",
				content: `import React from "react";
import ReactDOM from "react-dom/client";

const root = document.getElementById("root");

if (root) {
	const app = ReactDOM.createRoot(root);
	app.render(
		<React.StrictMode>
			<main style={{ fontFamily: "sans-serif", padding: "1.5rem" }}>
				<h1>PequeRoku Mock React Template</h1>
				<p>Happy coding!</p>
			</main>
		</React.StrictMode>,
	);
}
`,
			},
			{
				path: "/app/config.json",
				content: JSON.stringify({ run: "cd frontend && npm run dev", port: 5173 }, null, 2),
			},
		],
	},
	django: {
		id: "django",
		name: "Django Backend",
		description: "Generates a Django project with default settings and Dockerfile.",
		destination: "/app/backend",
		files: [
			{
				path: "/app/backend/manage.py",
				content: `#!/usr/bin/env python
import os
import sys

def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
`,
			},
			{
				path: "/app/backend/project/__init__.py",
				content: "",
			},
			{
				path: "/app/backend/project/settings.py",
				content: `from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = "mock-secret-key"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "project.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "project.wsgi.application"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
`,
			},
			{
				path: "/app/backend/project/urls.py",
				content: `from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
]
`,
			},
			{
				path: "/app/backend/project/wsgi.py",
				content: `import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")

application = get_wsgi_application()
`,
			},
			{
				path: "/app/config.json",
				content: JSON.stringify(
					{ run: "cd backend && python manage.py runserver 0.0.0.0:8000", port: 8000 },
					null,
					2,
				),
			},
		],
	},
};

const stateByContainer = new Map<string, Map<string, EntryRecord>>();
const listenersByContainer = new Map<string, Set<(event: BroadcastEvent) => void>>();

function ensureContainerState(containerId: string) {
	if (!stateByContainer.has(containerId)) {
		stateByContainer.set(
			containerId,
			new Map(DEFAULT_FS.map(([path, entry]) => [path, { ...entry }])),
		);
	}
	if (!listenersByContainer.has(containerId)) {
		listenersByContainer.set(containerId, new Set());
	}
}

function getContainerState(containerId: string): Map<string, EntryRecord> {
	ensureContainerState(containerId);
	const state = stateByContainer.get(containerId);
	if (!state) {
		throw new Error(`Mock state not initialized for container ${containerId}`);
	}
	return state;
}

function emit(containerId: string, event: BroadcastEvent) {
	const listeners = listenersByContainer.get(containerId);
	if (!listeners || listeners.size === 0) return;
	listeners.forEach((listener) => {
		try {
			listener(event);
		} catch (err) {
			console.error("Mock FS listener error", err);
		}
	});
}

function listDirectoryEntries(
	containerId: string,
	basePaths: string[],
): Array<{ name: string; path: string; path_type: EntryType }> {
	const state = getContainerState(containerId);
	const results: Array<{ name: string; path: string; path_type: EntryType }> = [];

	basePaths.forEach((basePath) => {
		const normalized = basePath.endsWith("/") ? basePath.slice(0, -1) : basePath;
		state.forEach((entry, path) => {
			if (path === normalized) return;
			if (!path.startsWith(`${normalized}/`)) return;
			const relative = path.slice(normalized.length + 1);
			if (relative.includes("/")) return;
			results.push({
				name: relative,
				path,
				path_type: entry.type,
			});
		});
	});

	return results;
}

function readFile(containerId: string, path: string): string {
	const state = getContainerState(containerId);
	const entry = state.get(path);
	if (!entry || entry.type !== "file") {
		return "";
	}
	return entry.content ?? "";
}

function writeFile(containerId: string, path: string, content: string) {
	const state = getContainerState(containerId);
	const normalized = path.replace(/\/{2,}/g, "/");
	state.set(normalized, { type: "file", content });
	ensureParentFolders(containerId, normalized);
	emit(containerId, { event: "file_changed", path: normalized });
}

function ensureParentFolders(containerId: string, path: string) {
	const state = getContainerState(containerId);
	const segments = path.split("/").slice(1, -1);
	let current = "";
	segments.forEach((segment) => {
		current += `/${segment}`;
		if (!state.has(current)) {
			state.set(current, { type: "folder" });
		}
	});
}

function createDir(containerId: string, path: string) {
	const state = getContainerState(containerId);
	const normalized = path.replace(/\/{2,}/g, "/");
	ensureParentFolders(containerId, normalized);
	state.set(normalized, { type: "folder" });
	emit(containerId, { event: "path_created", path: normalized });
}

function deletePath(containerId: string, path: string) {
	const state = getContainerState(containerId);
	const normalized = path.replace(/\/{2,}/g, "/");
	const entriesToDelete = Array.from(state.keys()).filter(
		(key) => key === normalized || key.startsWith(`${normalized}/`),
	);
	entriesToDelete.forEach((key) => {
		state.delete(key);
	});
	emit(containerId, { event: "path_deleted", path: normalized });
}

function movePath(containerId: string, src: string, dst: string) {
	const state = getContainerState(containerId);
	const normalizedSrc = src.replace(/\/{2,}/g, "/");
	const normalizedDst = dst.replace(/\/{2,}/g, "/");
	if (!state.has(normalizedSrc)) return;

	const entriesToMove = Array.from(state.entries()).filter(
		([key]) => key === normalizedSrc || key.startsWith(`${normalizedSrc}/`),
	);
	entriesToMove.forEach(([key, value]) => {
		state.delete(key);
		const suffix = key.slice(normalizedSrc.length);
		state.set(`${normalizedDst}${suffix}`, { ...value });
	});
	ensureParentFolders(containerId, normalizedDst);
	emit(containerId, { event: "path_moved", path: normalizedSrc, dst: normalizedDst });
}

function searchFiles(
	containerId: string,
	pattern: string,
): Array<{ path: string; matches: Array<{ line: number; preview: string }> }> {
	const state = getContainerState(containerId);
	const regex = new RegExp(pattern, "i");
	const results: Array<{ path: string; matches: Array<{ line: number; preview: string }> }> = [];

	state.forEach((entry, path) => {
		if (entry.type !== "file" || !entry.content) return;
		const lines = entry.content.split(/\r?\n/);
		const matches: Array<{ line: number; preview: string }> = [];
		lines.forEach((line, index) => {
			if (regex.test(line)) {
				matches.push({ line: index + 1, preview: line.trim() });
			}
		});
		if (matches.length > 0) {
			results.push({ path, matches });
		}
	});

	return results;
}

function normalizePath(path: string) {
	if (!path) return "/app";
	const trimmed = path.trim().replace(/\/{2,}/g, "/");
	if (!trimmed) return "/app";
	if (!trimmed.startsWith("/")) return `/${trimmed}`;
	return trimmed.endsWith("/") ? trimmed.slice(0, -1) : trimmed;
}

function cleanDestination(containerId: string, dest: string) {
	const normalizedDest = normalizePath(dest);
	const state = getContainerState(containerId);
	const keys = Array.from(state.keys());
	keys.forEach((key) => {
		if (key === normalizedDest) return;
		if (key.startsWith(`${normalizedDest}/`)) {
			state.delete(key);
		}
	});
	if (!state.has(normalizedDest)) {
		state.set(normalizedDest, { type: "folder" });
	}
	emit(containerId, { event: "path_deleted", path: normalizedDest });
}

export async function mockUploadFile(containerId: string, file: File, destination: string) {
	const targetDir = normalizePath(destination || "/app");
	const name = file?.name?.trim() ? file.name.trim() : "upload.dat";
	const relative = name.replace(/^[\\/]+/, "");
	const path = `${targetDir}/${relative}`.replace(/\/{2,}/g, "/");
	const content =
		typeof file.text === "function" ? await file.text() : await new Response(file).text();
	writeFile(containerId, path, content);
	return { dest: targetDir };
}

export async function mockFetchTemplates(): Promise<TemplateSummary[]> {
	return Object.values(TEMPLATE_LIBRARY).map(({ files: _files, ...meta }) => meta);
}

export async function mockApplyTemplate(
	templateId: string,
	options: { containerId: string; destPath: string; clean: boolean },
) {
	const template = TEMPLATE_LIBRARY[templateId];
	if (!template) {
		throw new Error("Template not found");
	}
	const containerId = options.containerId;
	const destination = normalizePath(options.destPath || template.destination);
	if (options.clean) {
		cleanDestination(containerId, destination);
	}
	let filesCount = 0;
	for (const file of template.files) {
		const relative = file.path.replace(template.destination, "").replace(/^\//, "");
		const targetPath = `${destination}/${relative}`.replace(/\/{2,}/g, "/");
		writeFile(containerId, targetPath, file.content);
		filesCount += 1;
	}
	return { files_count: filesCount };
}

export async function mockFetchRunConfig(containerId: string) {
	const raw = readFile(containerId, "/app/config.json");
	if (!raw) return { run: null, port: null };
	try {
		const parsed = JSON.parse(raw) as { run?: string; port?: number | string };
		const run = typeof parsed.run === "string" && parsed.run.trim() ? parsed.run.trim() : null;
		let port: number | null = null;
		if (typeof parsed.port === "number") {
			port = Number.isFinite(parsed.port) ? parsed.port : null;
		} else if (typeof parsed.port === "string" && parsed.port.trim()) {
			const value = Number.parseInt(parsed.port.trim(), 10);
			port = Number.isFinite(value) ? value : null;
		}
		return { run, port };
	} catch {
		return { run: null, port: null };
	}
}

export async function mockPollPreview(
	containerId: string,
	port: number,
	path: string,
): Promise<{ url: string; html: string } | null> {
	if (!port) return null;
	const normalizedPath = path.replace(/^\//, "");
	const url = `https://mock.pequeroku.local/${containerId}/${port}/${encodeURIComponent(normalizedPath)}`;
	const html = `<html><body><h1>Mock Preview ${containerId}</h1><p>Serving path: /${normalizedPath}</p></body></html>`;
	return { url, html };
}

export class MockFileSystemWebService {
	private containerId: string;

	constructor(containerId: string) {
		this.containerId = containerId;
		ensureContainerState(containerId);
		setTimeout(() => {
			emit(containerId, { event: "connected" });
		}, 0);
	}

	public async call<T = unknown>(
		action: string,
		payload: Record<string, unknown> = {},
	): Promise<T> {
		switch (action) {
			case "list_dirs": {
				const raw = typeof payload.path === "string" ? payload.path : "/app";
				const targets = raw.split(",").filter(Boolean);
				const entries = listDirectoryEntries(this.containerId, targets.length ? targets : ["/app"]);
				return { entries } as T;
			}
			case "read": {
				const path = typeof payload.path === "string" ? payload.path : "";
				return { content: readFile(this.containerId, path) } as T;
			}
			case "write": {
				const path = typeof payload.path === "string" ? payload.path : "";
				const content = typeof payload.content === "string" ? payload.content : "";
				writeFile(this.containerId, path, content);
				return { ok: true } as T;
			}
			case "create_dir": {
				const path = typeof payload.path === "string" ? payload.path : "";
				createDir(this.containerId, path);
				return { ok: true } as T;
			}
			case "delete_path": {
				const path = typeof payload.path === "string" ? payload.path : "";
				deletePath(this.containerId, path);
				return { ok: true } as T;
			}
			case "move_path": {
				const src = typeof payload.src === "string" ? payload.src : "";
				const dst = typeof payload.dst === "string" ? payload.dst : "";
				movePath(this.containerId, src, dst);
				return { ok: true } as T;
			}
			case "search": {
				const pattern =
					typeof payload.pattern === "string" && payload.pattern.trim()
						? payload.pattern.trim()
						: "";
				const results = pattern ? searchFiles(this.containerId, pattern) : [];
				return results as T;
			}
			default:
				return { ok: false } as T;
		}
	}

	public async search(options: {
		pattern: string;
	}): Promise<Array<{ path: string; matches: Array<{ line: number; preview: string }> }>> {
		if (!options.pattern.trim()) return [];
		return searchFiles(this.containerId, options.pattern.trim());
	}

	public close() {
		// No-op for mock mode
	}

	public onBroadcast(listener: (event: BroadcastEvent) => void): () => void {
		ensureContainerState(this.containerId);
		const listeners = listenersByContainer.get(this.containerId);
		if (!listeners) {
			return () => {};
		}
		listeners.add(listener);
		listener({ event: "connected" });
		return () => {
			listeners.delete(listener);
		};
	}
}
