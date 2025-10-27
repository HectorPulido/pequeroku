import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
	type FileSystemSearchOptions,
	type FileSystemSearchResult,
} from "@/services/ide/FileSystemWebService";
import type { FileNode } from "@/types/ide";

type FileSystemWebService = InstanceType<
	typeof import("@/services/ide/FileSystemWebService").default
>;

type RawListDirEntry = {
	name: string;
	path: string;
	path_type: "file" | "folder" | "directory";
};

type ListDirEntry = {
	name: string;
	path: string;
	path_type: "file" | "folder";
};

type ListDirsResponse = {
	entries?: RawListDirEntry[];
};

const DEFAULT_ROOT = "/app";

const normalizePath = (value: string) => {
	const trimmed = value?.trim() || DEFAULT_ROOT;
	const withLeading = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
	return withLeading.replace(/\/{2,}/g, "/") || DEFAULT_ROOT;
};

const parentPath = (value: string) => {
	const normalized = normalizePath(value);
	if (normalized === DEFAULT_ROOT) return DEFAULT_ROOT;
	const withoutTrailing = normalized.replace(/\/$/, "");
	const idx = withoutTrailing.lastIndexOf("/");
	return idx > 0 ? withoutTrailing.slice(0, idx) : DEFAULT_ROOT;
};

const collectFolderAncestors = (value: string, includeSelf = false): string[] => {
	const normalized = normalizePath(value);
	if (!normalized.startsWith(DEFAULT_ROOT)) return [];
	const segments = normalized.split("/").filter(Boolean);
	if (segments.length === 0 || segments[0] !== DEFAULT_ROOT.slice(1)) {
		return [];
	}
	const folders: string[] = [`/${segments[0]}`];
	const lastIndex = includeSelf ? segments.length - 1 : segments.length - 2;
	for (let index = 1; index <= lastIndex; index += 1) {
		const part = segments[index];
		if (!part) continue;
		const previous = folders[folders.length - 1] ?? DEFAULT_ROOT;
		const combined = `${previous}/${part}`.replace(/\/{2,}/g, "/");
		folders.push(combined);
	}
	return Array.from(new Set(folders.filter((folder) => folder.startsWith(DEFAULT_ROOT))));
};

const sortEntries = (entries: ListDirEntry[]) =>
	entries.slice().sort((a, b) => {
		if (a.path_type !== b.path_type) {
			return a.path_type === "folder" ? -1 : 1;
		}
		return a.name.localeCompare(b.name);
	});

const buildTreeFromMap = (
	entriesMap: Map<string, ListDirEntry[]>,
	expanded: Set<string>,
): FileNode[] => {
	const buildChildren = (path: string): FileNode[] => {
		const entries = sortEntries(entriesMap.get(path) ?? []);
		return entries.map((entry) => {
			const normalized = normalizePath(entry.path);
			const isFolder = entry.path_type === "folder";
			const isOpen = isFolder && expanded.has(normalized);
			const children = isFolder && isOpen ? buildChildren(normalized) : [];
			return {
				name: entry.name,
				path: normalized,
				type: entry.path_type,
				isOpen,
				children,
			};
		});
	};

	return [
		{
			name: "app",
			path: DEFAULT_ROOT,
			type: "folder" as const,
			isOpen: true,
			children: buildChildren(DEFAULT_ROOT),
		},
	];
};

export const buildFileTreeFromEntries = (entries: RawListDirEntry[]): FileNode[] => {
	const entriesMap = new Map<string, ListDirEntry[]>();
	const expanded = new Set<string>([DEFAULT_ROOT]);

	entries.forEach((entry) => {
		const normalizedPath = normalizePath(entry.path);
		const normalizedType = entry.path_type === "directory" ? "folder" : entry.path_type;
		const parent = parentPath(normalizedPath);
		const list = entriesMap.get(parent) ?? [];
		list.push({
			name: entry.name,
			path: normalizedPath,
			path_type: normalizedType,
		});
		entriesMap.set(parent, list);

		if (normalizedType === "folder") {
			expanded.add(normalizedPath);
			if (!entriesMap.has(normalizedPath)) {
				entriesMap.set(normalizedPath, []);
			}
		}
	});

	if (!entriesMap.has(DEFAULT_ROOT)) {
		entriesMap.set(DEFAULT_ROOT, []);
	}

	return buildTreeFromMap(entriesMap, expanded);
};

export interface FileActionUI {
	confirm: (message: string) => boolean;
	prompt: (message: string, defaultValue?: string) => string | null;
}

const defaultUI: FileActionUI = {
	confirm: (message) => window.confirm(message),
	prompt: (message, defaultValue) => window.prompt(message, defaultValue),
};

export async function performFileAction(
	action: string,
	path: string,
	selectionType: string,
	fs: { call: (action: string, payload: Record<string, unknown>) => Promise<unknown> },
	refresh: (targets?: string[]) => Promise<void> | void,
	ui: FileActionUI = defaultUI,
) {
	switch (action) {
		case "delete": {
			if (ui.confirm(`Delete "${path}"?`)) {
				await fs.call("delete_path", { path });
				await refresh([parentPath(path)]);
			}
			break;
		}
		case "rename": {
			const currentName = path.split("/").pop();
			const newName = ui.prompt("New name:", currentName ?? "");
			if (newName && newName !== currentName) {
				const base = path.substring(0, path.lastIndexOf("/"));
				const newPath = `${base}/${newName}`.replace("//", "/");
				await fs.call("move_path", { src: path, dst: newPath });
				await refresh([base || DEFAULT_ROOT, parentPath(newPath)]);
			}
			break;
		}
		case "new-file": {
			const newFileName = ui.prompt("File name:");
			if (newFileName) {
				const destination =
					selectionType === "folder" ? path : path.substring(0, path.lastIndexOf("/"));
				const newFilePath = `${destination}/${newFileName}`.replace("//", "/");
				await fs.call("write", { path: newFilePath, content: "" });
				await refresh([destination || DEFAULT_ROOT]);
			}
			break;
		}
		case "new-folder": {
			const newFolderName = ui.prompt("Folder name:");
			if (newFolderName) {
				const destination =
					selectionType === "folder" ? path : path.substring(0, path.lastIndexOf("/"));
				const newFolderPath = `${destination}/${newFolderName}`.replace("//", "/");
				await fs.call("create_dir", { path: newFolderPath });
				await refresh([destination || DEFAULT_ROOT]);
			}
			break;
		}
		case "download": {
			await refresh();
			break;
		}
		default:
			break;
	}
}

export const useFileTree = (containerId: string, service: FileSystemWebService) => {
	const [fileTree, setFileTree] = useState<FileNode[]>([]);
	const [selectedFileState, setSelectedFileState] = useState<string | null>(null);
	const entriesRef = useRef<Map<string, ListDirEntry[]>>(new Map());
	const expandedRef = useRef<Set<string>>(new Set());

	const storageKeys = useMemo(
		() => ({
			expanded: `ide:${containerId}:tree:expanded`,
			selected: `ide:${containerId}:tree:selected`,
		}),
		[containerId],
	);

	const persistExpanded = useCallback(() => {
		try {
			const arr = Array.from(expandedRef.current);
			window.localStorage.setItem(storageKeys.expanded, JSON.stringify(arr));
		} catch {
			/* ignore */
		}
	}, [storageKeys.expanded]);

	const persistSelected = useCallback(
		(path: string | null) => {
			try {
				if (path) {
					window.localStorage.setItem(storageKeys.selected, path);
				} else {
					window.localStorage.removeItem(storageKeys.selected);
				}
			} catch {
				/* ignore */
			}
		},
		[storageKeys.selected],
	);

	// biome-ignore lint/correctness/useExhaustiveDependencies: reset when container changes.
	useEffect(() => {
		setFileTree([]);
		setSelectedFileState(null);
		entriesRef.current = new Map();
		expandedRef.current = new Set();
	}, [containerId, service]);

	const rebuildTree = useCallback(() => {
		setFileTree(buildTreeFromMap(entriesRef.current, expandedRef.current));
	}, []);

	const ensureRoot = useCallback(() => {
		if (!entriesRef.current.has(DEFAULT_ROOT)) {
			entriesRef.current.set(DEFAULT_ROOT, []);
		}
		if (!expandedRef.current.has(DEFAULT_ROOT)) {
			expandedRef.current.add(DEFAULT_ROOT);
		}
	}, []);

	const fetchDirectories = useCallback(
		async (paths: string[]) => {
			const uniqueTargets = Array.from(
				new Set(
					paths.map((path) => normalizePath(path)).filter((path) => path.startsWith(DEFAULT_ROOT)),
				),
			);

			if (!uniqueTargets.length) return;

			for (const path of uniqueTargets) {
				try {
					const res = await service.call<ListDirsResponse>("list_dirs", { path });
					const rawEntries = Array.isArray(res?.entries) ? res.entries : [];
					const entries = rawEntries
						.map<ListDirEntry | null>((entry) => {
							const normalizedType = entry.path_type === "directory" ? "folder" : entry.path_type;
							const safeType: ListDirEntry["path_type"] =
								normalizedType === "folder" ? "folder" : "file";
							const normalizedPath = normalizePath(entry.path);
							if (!normalizedPath || normalizedPath === path) {
								return null;
							}
							return {
								name: entry.name,
								path: normalizedPath,
								path_type: safeType,
							};
						})
						.filter((entry): entry is ListDirEntry => entry !== null);
					entriesRef.current.set(path, entries);
				} catch (error) {
					console.error("file tree fetch failed", error);
				}
			}
			rebuildTree();
		},
		[rebuildTree, service],
	);

	const refreshPaths = useCallback(
		async (paths?: string[]) => {
			const targets = paths?.length
				? paths
				: [DEFAULT_ROOT, ...Array.from(expandedRef.current.values())];
			await fetchDirectories(targets);
		},
		[fetchDirectories],
	);

	useEffect(() => {
		ensureRoot();

		try {
			const raw = window.localStorage.getItem(storageKeys.expanded);
			if (raw) {
				const parsed = JSON.parse(raw) as unknown;
				if (Array.isArray(parsed)) {
					expandedRef.current = new Set(parsed.map((item) => normalizePath(String(item))));
				}
			}
		} catch {
			expandedRef.current = new Set();
		}
		if (!expandedRef.current.has(DEFAULT_ROOT)) {
			expandedRef.current.add(DEFAULT_ROOT);
		}

		try {
			const stored = window.localStorage.getItem(storageKeys.selected);
			if (stored) {
				const normalized = normalizePath(stored);
				setSelectedFileState(normalized === DEFAULT_ROOT ? null : normalized);
			}
		} catch {
			setSelectedFileState(null);
		}

		refreshPaths([DEFAULT_ROOT, ...Array.from(expandedRef.current.values())]).catch((error) => {
			console.error("file tree bootstrap failed", error);
		});
	}, [ensureRoot, refreshPaths, storageKeys.expanded, storageKeys.selected]);

	useEffect(() => {
		const refreshEvents = new Set([
			"path_deleted",
			"path_moved",
			"path_created",
			"path_added",
			"dir_created",
			"file_created",
			"file_changed",
		]);
		let refreshTimer: ReturnType<typeof setTimeout> | null = null;

		const queueRefresh = (targets?: string[]) => {
			if (refreshTimer) return;
			refreshTimer = setTimeout(() => {
				refreshTimer = null;
				refreshPaths(targets).catch((error) => {
					console.error("file tree refresh failed", error);
				});
			}, 120);
		};

		const unsubscribe = service.onBroadcast(
			(event: { event?: unknown; type?: unknown; path?: unknown; dst?: unknown }) => {
				const rawType = event?.event ?? event?.type;
				const eventType = typeof rawType === "string" ? rawType : "";
				if (eventType === "connected") {
					queueRefresh();
					return;
				}
				if (!eventType || !refreshEvents.has(eventType)) {
					return;
				}
				const targets = new Set<string>();
				if ("path" in event && typeof event.path === "string") {
					targets.add(parentPath(event.path));
				}
				if ("dst" in event && typeof event.dst === "string") {
					targets.add(parentPath(event.dst));
				}
				queueRefresh(targets.size ? Array.from(targets) : undefined);
			},
		);

		return () => {
			unsubscribe();
			if (refreshTimer) {
				clearTimeout(refreshTimer);
			}
		};
	}, [refreshPaths, service]);

	const handleToggleFolder = (path: string) => {
		const normalized = normalizePath(path);
		if (expandedRef.current.has(normalized)) {
			expandedRef.current.delete(normalized);
			persistExpanded();
			rebuildTree();
			return;
		}
		expandedRef.current.add(normalized);
		persistExpanded();
		fetchDirectories([normalized]).catch((error) => {
			console.error("file tree expand failed", error);
		});
	};

	const handleAction = async (action: string, path: string, selectionType: string) => {
		await performFileAction(
			action,
			path,
			selectionType,
			service,
			(targets) => refreshPaths(targets?.length ? targets : [parentPath(path), DEFAULT_ROOT]),
			defaultUI,
		);
	};

	const search = useCallback(
		(options: FileSystemSearchOptions): Promise<FileSystemSearchResult[]> =>
			service.search(options),
		[service],
	);

	const reset = useCallback(async () => {
		setFileTree([]);
		setSelectedFileState(null);
		entriesRef.current = new Map();
		expandedRef.current = new Set([DEFAULT_ROOT]);
		await refreshPaths([DEFAULT_ROOT]);
	}, [refreshPaths]);

	const setSelectedFile = useCallback(
		(path: string | null) => {
			const normalized = path ? normalizePath(path) : null;
			const next = normalized === DEFAULT_ROOT ? null : normalized;
			setSelectedFileState(next);
			persistSelected(next);
		},
		[persistSelected],
	);

	const ensurePathVisible = useCallback(
		async (targetPath: string, options?: { includeTarget?: boolean }) => {
			const normalized = normalizePath(targetPath);
			if (!normalized.startsWith(DEFAULT_ROOT)) return;
			const includeTarget = options?.includeTarget ?? false;
			const folders = collectFolderAncestors(normalized, includeTarget);
			if (folders.length === 0) return;
			let expandedChanged = false;
			for (const folder of folders) {
				if (!expandedRef.current.has(folder)) {
					expandedRef.current.add(folder);
					expandedChanged = true;
				}
			}
			if (expandedChanged) {
				persistExpanded();
			}
			await fetchDirectories(folders);
			rebuildTree();
		},
		[fetchDirectories, persistExpanded, rebuildTree],
	);

	return {
		fileTree,
		selectedFile: selectedFileState,
		setSelectedFile,
		handleToggleFolder,
		handleAction,
		refreshTree: () => refreshPaths(),
		search,
		reset,
		ensurePathVisible,
	};
};
