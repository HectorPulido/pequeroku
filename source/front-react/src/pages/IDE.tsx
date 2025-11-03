/** biome-ignore-all lint/suspicious/noTemplateCurlyInString: Not a template */
import {
	CloudDownload,
	CloudUpload,
	FloppyDisk,
	FolderPlus,
	Globe,
	Menu,
	MultiplePagesPlus,
	Play,
	RefreshDouble,
	Search,
} from "iconoir-react";
import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import Header from "@/components/Header";
import AiAssistantPanel from "@/components/ide/AiAssistantPanel";
import Editor from "@/components/ide/Editor";
import FileTabs from "@/components/ide/FileTabs";
import FileTree from "@/components/ide/FileTree";
import GithubModal from "@/components/ide/GithubModal";
import ResizablePanel from "@/components/ide/ResizablePanel";
import TemplatesModal from "@/components/ide/TemplatesModal";
import TerminalPanel from "@/components/ide/TerminalPanel";
import UploadModal from "@/components/ide/UploadModal";
import { ACTION_DELAYS } from "@/constants";
import { useEditor } from "@/hooks/useEditor";
import { useFileTree } from "@/hooks/useFileTree";
import { useIsMobile } from "@/hooks/useIsMobile";
import { useTerminals } from "@/hooks/useTerminals";
import { alertStore } from "@/lib/alertStore";
import { detectLanguageFromPath } from "@/lib/langMap";
import { type Theme, themeManager } from "@/lib/theme";
import {
	applyTemplate,
	buildDownloadUrl,
	fetchRunConfig,
	fetchTemplates,
	pollPreview,
	uploadFile,
} from "@/services/ide/actions";
import FileSystemWebService, {
	type FileSystemSearchResult,
} from "@/services/ide/FileSystemWebService";
import type { FileNode } from "@/types/ide";
import type { TemplateSummary } from "@/types/template";

const MissingContainer: React.FC<{ showHeader: boolean }> = ({ showHeader }) => (
	<div className="min-h-screen bg-[#0B1220] text-gray-200">
		{showHeader ? <Header /> : null}
		<div className="flex min-h-[60vh] items-center justify-center px-6">
			<div className="max-w-md rounded-xl border border-gray-800 bg-[#111827] p-6 text-sm shadow-lg shadow-indigo-900/10">
				<h1 className="mb-3 text-lg font-semibold text-white">Container unavailable</h1>
				<p className="text-gray-300">
					The IDE requires a valid <code>containerId</code> query parameter. Launch it from the
					dashboard or append <code>?containerId=&lt;id&gt;</code> to the URL and reload the page.
				</p>
			</div>
		</div>
	</div>
);

const findNodeByPath = (nodes: FileNode[], target: string): FileNode | null => {
	for (const node of nodes) {
		if (node.path === target) {
			return node;
		}
		if (node.children?.length) {
			const nested = findNodeByPath(node.children, target);
			if (nested) {
				return nested;
			}
		}
	}
	return null;
};

const escapeForDoubleQuotes = (value: string) => value.replace(/"/g, '\\"');

const buildCloneCommand = (repo: string, basePath: string, clean: boolean) => {
	const escapedRepo = escapeForDoubleQuotes(repo);
	const sanitizedBase = basePath || "/";
	const escapedBase = escapeForDoubleQuotes(sanitizedBase);
	const baseCheck = "${X:-/}";
	const baseSub = "${X#/}";
	const cleanSegment = clean
		? 'find /app -mindepth 1 -not -name "readme.txt" -not -name "config.json" -exec rm -rf {} +; '
		: "";
	const command = [
		"bash -lc 'set -euo pipefail; ",
		`REPO="${escapedRepo}"; `,
		`X="${escapedBase}"; `,
		'TMP="$(mktemp -d)"; ',
		'git clone "$REPO" "$TMP/repo"; ',
		"sudo mkdir -p /app; ",
		cleanSegment,
		'SRC="$TMP/repo"; ',
		`[ "${baseCheck}" != "/" ] && SRC="$TMP/repo/${baseSub}"; `,
		"shopt -s dotglob nullglob; ",
		'mv "$SRC"/* /app/; ',
		'rm -rf "$TMP"',
	]
		.filter(Boolean)
		.join("");
	return `${command}'`;
};

const IDELayout: React.FC<{ containerId: string; showHeader: boolean }> = ({
	containerId,
	showHeader,
}) => {
	const fileSystemService = useMemo(() => new FileSystemWebService(containerId), [containerId]);
	useEffect(() => {
		return () => {
			fileSystemService.close();
		};
	}, [fileSystemService]);

	const {
		fileTree,
		selectedFile,
		setSelectedFile,
		handleToggleFolder,
		handleAction: handleFileTreeAction,
		refreshTree,
		search,
		ensurePathVisible,
	} = useFileTree(containerId, fileSystemService);
	const {
		tabs,
		activeTab,
		editorContent,
		setEditorContent,
		openFile,
		handleCloseTab,
		handleTabChange,
		saveActiveFile,
	} = useEditor(containerId, fileSystemService);
	const {
		terminalTabs,
		activeTerminalId,
		setActiveTerminalId,
		handleNewTerminal,
		handleCloseTerminal,
		sendToActiveTerminal,
		listSessions,
		clearTerminal,
	} = useTerminals(containerId);
	const isMobile = useIsMobile();

	const [sidebarState, setSidebarState] = useState<"open" | "collapsed">(() => {
		if (typeof window === "undefined") {
			return isMobile ? "collapsed" : "open";
		}
		const stored = window.localStorage.getItem(`ide:${containerId}:sidebar`) as
			| "open"
			| "collapsed"
			| null;
		if (stored === "open" || stored === "collapsed") {
			return stored;
		}
		return isMobile ? "collapsed" : "open";
	});
	const [consoleState, setConsoleState] = useState<"open" | "collapsed">(() => {
		if (typeof window === "undefined") return "open";
		return (
			(window.localStorage.getItem(`ide:${containerId}:console`) as "open" | "collapsed") ?? "open"
		);
	});
	const [showSearch, setShowSearch] = useState(false);
	const [showPreview, setShowPreview] = useState(false);
	const [previewPath, setPreviewPath] = useState("");
	const [previewTargetUrl, setPreviewTargetUrl] = useState<string | null>(null);
	const [previewLoading, setPreviewLoading] = useState(false);
	const [previewError, setPreviewError] = useState<string | null>(null);
	const [isUploadModalOpen, setUploadModalOpen] = useState(false);
	const [isTemplatesModalOpen, setTemplatesModalOpen] = useState(false);
	const [isGithubModalOpen, setGithubModalOpen] = useState(false);
	const [isAiPanelOpen, setAiPanelOpen] = useState(false);
	const [theme, setTheme] = useState<Theme>(() => themeManager.get());
	const [searchPattern, setSearchPattern] = useState("");
	const [searchInclude, setSearchInclude] = useState("");
	const [searchExclude, setSearchExclude] = useState(".git,.venv");
	const [searchCaseSensitive, setSearchCaseSensitive] = useState(false);
	const [searchResults, setSearchResults] = useState<FileSystemSearchResult[]>([]);
	const [searchLoading, setSearchLoading] = useState(false);
	const [searchPerformed, setSearchPerformed] = useState(false);
	const [runCommand, setRunCommand] = useState<string | null>(null);
	const [runPort, setRunPort] = useState<number | null>(null);
	const [runLoading, setRunLoading] = useState(false);
	const [templates, setTemplates] = useState<TemplateSummary[]>([]);
	const [templatesLoading, setTemplatesLoading] = useState(false);
	const [templatesError, setTemplatesError] = useState<string | null>(null);
	const initialFileLoadRef = useRef<string | null>(null);
	const lastOpenedPathKey = useMemo(
		() => (containerId ? `ide:${containerId}:last-file` : null),
		[containerId],
	);

	useEffect(() => {
		if (!isMobile) return;
		setSidebarState((prev) => {
			if (prev === "collapsed") {
				return prev;
			}
			try {
				window.localStorage.setItem(`ide:${containerId}:sidebar`, "collapsed");
			} catch {
				/* ignore */
			}
			return "collapsed";
		});
	}, [containerId, isMobile]);

	useEffect(() => {
		const unsubscribe = themeManager.subscribe(setTheme);
		return unsubscribe;
	}, []);

	const selectedNode = useMemo(
		() => (selectedFile ? findNodeByPath(fileTree, selectedFile) : null),
		[fileTree, selectedFile],
	);
	const isSidebarCollapsed = sidebarState !== "open";
	const isTerminalCollapsed = consoleState !== "open";

	const onFileSelect = useCallback(
		(path: string) => {
			const node = findNodeByPath(fileTree, path);
			if (!node) {
				setSelectedFile(path);
				return;
			}
			setSelectedFile(path);
			if (node.type === "file") {
				openFile(path);
			}
		},
		[fileTree, openFile, setSelectedFile],
	);

	const handleFileAction = useCallback(
		async (action: string, path: string, selectionType: string) => {
			if (action === "open") {
				onFileSelect(path);
				return;
			}
			if (action === "download") {
				const url = buildDownloadUrl(
					containerId,
					path,
					selectionType === "folder" ? "folder" : "file",
				);
				window.open(url, "_blank", "noopener,noreferrer");
				return;
			}
			try {
				await handleFileTreeAction(action, path, selectionType);
			} catch (error) {
				const message = error instanceof Error ? error.message : "File action failed";
				alertStore.push({ message, variant: "error" });
			}
		},
		[containerId, handleFileTreeAction, onFileSelect],
	);

	const handleSearch = useCallback(async () => {
		const pattern = searchPattern.trim();
		if (!pattern) {
			alertStore.push({ message: "Enter a search pattern before searching.", variant: "warning" });
			return;
		}
		setSearchLoading(true);
		try {
			const results = await search({
				pattern,
				includeGlobs: searchInclude.trim() || undefined,
				excludeDirs: searchExclude.trim() || undefined,
				caseSensitive: searchCaseSensitive,
			});
			setSearchResults(results);
			setSearchPerformed(true);
		} catch (error) {
			const message = error instanceof Error ? error.message : "Search failed";
			alertStore.push({ message, variant: "error" });
		} finally {
			setSearchLoading(false);
		}
	}, [searchPattern, searchInclude, searchExclude, searchCaseSensitive, search]);

	const handleSearchKey = useCallback(
		(event: React.KeyboardEvent<HTMLInputElement>) => {
			if (event.key === "Enter") {
				event.preventDefault();
				void handleSearch();
			}
		},
		[handleSearch],
	);

	const handleClearSearch = () => {
		setSearchPattern("");
		setSearchInclude("");
		setSearchExclude(".git,.venv");
		setSearchCaseSensitive(false);
		setSearchResults([]);
		setSearchPerformed(false);
	};

	const handleDownloadSelection = useCallback(() => {
		const fallback = fileTree[0] ?? null;
		const node = selectedNode ?? fallback;
		if (!node) {
			alertStore.push({
				message: "Select a file or folder before downloading.",
				variant: "info",
			});
			return;
		}
		const url = buildDownloadUrl(containerId, node.path, node.type);
		window.open(url, "_blank", "noopener,noreferrer");
	}, [containerId, fileTree, selectedNode]);

	const handleSearchResultClick = useCallback(
		async (path: string, line?: number) => {
			await ensurePathVisible(path);
			const normalizedPath = path.startsWith("/") ? path : `/app/${path}`.replace(/\/{2,}/g, "/");
			try {
				await openFile(normalizedPath);
				setSelectedFile(normalizedPath);
			} catch (error) {
				const message = error instanceof Error ? error.message : "Failed to open file";
				alertStore.push({ message, variant: "error" });
				return;
			}
			if (typeof line === "number" && Number.isFinite(line)) {
				window.dispatchEvent(
					new CustomEvent("ide:reveal-line", { detail: { path: normalizedPath, line } }),
				);
			}
		},
		[ensurePathVisible, openFile, setSelectedFile],
	);

	const openFileFromSlash = useCallback(
		async (rawPath: string) => {
			const trimmed = rawPath.trim();
			if (!trimmed) {
				alertStore.push({ message: "Provide a path to open.", variant: "warning" });
				return;
			}
			const normalized = trimmed.startsWith("/")
				? trimmed
				: `/app/${trimmed}`.replace(/\/{2,}/g, "/");
			try {
				await openFile(normalized);
				setSelectedFile(normalized);
			} catch (error) {
				const message = error instanceof Error ? error.message : "Failed to open file";
				alertStore.push({ message, variant: "error" });
			}
		},
		[openFile, setSelectedFile],
	);

	const handlePreviewGo = useCallback(
		async (rawPath?: string): Promise<{ ok: boolean; error?: string }> => {
			if (!runPort) {
				const message = "No preview port configured. Update /app/config.json to expose a port.";
				setPreviewError(message);
				return { ok: false, error: message };
			}
			const trimmed = (rawPath ?? previewPath).trim();
			const normalized = trimmed ? (trimmed.startsWith("/") ? trimmed : `/${trimmed}`) : "/";
			setPreviewLoading(true);
			setPreviewError(null);
			setPreviewPath(normalized);
			try {
				const response = await pollPreview({
					containerId,
					port: runPort,
					path: normalized,
				});
				if (!response) {
					const message = "Preview not ready yet. Start the app and try again.";
					setPreviewTargetUrl(null);
					setPreviewError(message);
					return { ok: false, error: message };
				}
				setPreviewTargetUrl(response.url);
				return { ok: true };
			} catch (error) {
				const message = error instanceof Error ? error.message : "Failed to refresh preview";
				setPreviewTargetUrl(null);
				setPreviewError(message);
				return { ok: false, error: message };
			} finally {
				setPreviewLoading(false);
			}
		},
		[containerId, previewPath, runPort],
	);

	const handlePreviewRefresh = useCallback(() => {
		void handlePreviewGo(previewPath || "/");
	}, [handlePreviewGo, previewPath]);

	const handlePreviewPopout = useCallback(() => {
		if (!previewTargetUrl) {
			alertStore.push({
				message: "Open the preview before using pop out.",
				variant: "info",
			});
			return;
		}
		window.open(previewTargetUrl, "_blank", "noopener,noreferrer");
	}, [previewTargetUrl]);

	const hydrateRunConfig = useCallback(async () => {
		setRunLoading(true);
		try {
			const { run, port } = await fetchRunConfig(containerId, fileSystemService);
			setRunCommand(run);
			setRunPort(port);
		} catch (error) {
			console.error("Failed to load run config", error);
			setRunCommand(null);
			setRunPort(null);
		} finally {
			setRunLoading(false);
		}
	}, [containerId, fileSystemService]);

	useEffect(() => {
		void hydrateRunConfig();
	}, [hydrateRunConfig]);

	useEffect(() => {
		if (!containerId) {
			setPreviewTargetUrl(null);
			setPreviewPath("");
			setPreviewError(null);
			return;
		}
		setPreviewTargetUrl(null);
		setPreviewPath("");
		setPreviewError(null);
	}, [containerId]);

	useEffect(() => {
		if (runPort && !previewPath) {
			setPreviewPath("/");
		}
	}, [previewPath, runPort]);

	useEffect(() => {
		if (!showPreview) return;
		if (previewLoading || previewTargetUrl) return;
		if (!runPort) return;
		void handlePreviewGo(previewPath || "/");
	}, [handlePreviewGo, previewLoading, previewPath, previewTargetUrl, runPort, showPreview]);

	const loadTemplates = useCallback(async () => {
		setTemplatesLoading(true);
		setTemplatesError(null);
		try {
			const list = await fetchTemplates();
			setTemplates(list);
		} catch (error) {
			const message = error instanceof Error ? error.message : "Failed to load templates";
			setTemplatesError(message);
		} finally {
			setTemplatesLoading(false);
		}
	}, []);

	const refreshWorkspace = useCallback(async () => {
		await refreshTree();
		await hydrateRunConfig();
	}, [hydrateRunConfig, refreshTree]);

	const handleTemplateApply = useCallback(
		async (templateId: string, options: { destination: string; clean: boolean }) => {
			await applyTemplate(templateId, {
				containerId,
				destPath: options.destination,
				clean: options.clean,
			});
			await refreshWorkspace();
		},
		[containerId, refreshWorkspace],
	);

	useEffect(() => {
		if (!isTemplatesModalOpen) return;
		void loadTemplates();
	}, [isTemplatesModalOpen, loadTemplates]);

	const handleGithubClone = useCallback(
		async ({ url, basePath, clean }: { url: string; basePath: string; clean: boolean }) => {
			const repo = url.trim();
			if (!repo) {
				alertStore.push({ message: "Repository URL is required", variant: "warning" });
				return;
			}
			const command = buildCloneCommand(repo, basePath.trim() || "/", clean);
			const sent = await sendToActiveTerminal(command);
			if (!sent) {
				alertStore.push({
					message: "Open a terminal session before cloning a repository.",
					variant: "warning",
				});
				return;
			}
			alertStore.push({
				message: clean
					? `Cloning ${repo} into /app (clean destination)...`
					: `Cloning ${repo} into /app (keeping existing files)...`,
				variant: "info",
			});
			await new Promise((resolve) => setTimeout(resolve, ACTION_DELAYS.cloneRepoWaitMs));
			await refreshWorkspace();
			alertStore.push({ message: "Repository cloned successfully.", variant: "success" });
		},
		[refreshWorkspace, sendToActiveTerminal],
	);

	const activeTabData = useMemo(() => tabs.find((tab) => tab.id === activeTab), [tabs, activeTab]);
	const editorLanguage = useMemo(
		() => detectLanguageFromPath(activeTabData?.path),
		[activeTabData?.path],
	);
	const defaultDestination = useMemo(() => {
		if (!selectedNode) return "/app";
		if (selectedNode.type === "folder") return selectedNode.path;
		const lastSlash = selectedNode.path.lastIndexOf("/");
		if (lastSlash <= 0) return "/app";
		return selectedNode.path.slice(0, lastSlash);
	}, [selectedNode]);

	const activeSelection = useMemo(() => {
		if (selectedNode) {
			return { path: selectedNode.path, type: selectedNode.type };
		}
		if (selectedFile) {
			return { path: selectedFile, type: "file" as const };
		}
		return { path: "/app", type: "folder" as const };
	}, [selectedFile, selectedNode]);

	const handleSaveActiveFile = useCallback(async () => {
		const targetTab = activeTabData ?? tabs[tabs.length - 1] ?? null;
		if (!targetTab) return;
		try {
			await saveActiveFile();
			alertStore.push({
				message: `File ${targetTab.path} saved.`,
				variant: "success",
			});
		} catch (error) {
			const message = error instanceof Error ? error.message : "Failed to save file";
			alertStore.push({ message, variant: "error" });
		}
	}, [activeTabData, saveActiveFile, tabs]);

	useEffect(() => {
		if (!lastOpenedPathKey || typeof window === "undefined") {
			return;
		}
		const path = activeTabData?.path;
		if (path) {
			window.localStorage.setItem(lastOpenedPathKey, path);
			return;
		}
		if (tabs.length === 0) {
			window.localStorage.removeItem(lastOpenedPathKey);
		}
	}, [activeTabData?.path, lastOpenedPathKey, tabs.length]);

	useEffect(() => {
		if (!containerId || !lastOpenedPathKey || typeof window === "undefined") {
			return;
		}
		if (initialFileLoadRef.current === containerId) {
			return;
		}
		initialFileLoadRef.current = containerId;
		let cancelled = false;

		const normalizeCandidate = (candidate: string | null) => {
			if (!candidate) return null;
			const trimmed = candidate.trim();
			if (!trimmed) return null;
			return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
		};

		const loadInitialFile = async () => {
			const storedPathRaw = window.localStorage.getItem(lastOpenedPathKey);
			const storedPath = normalizeCandidate(storedPathRaw);
			const fallbackPath = normalizeCandidate("/app/readme.txt");
			const candidates = [storedPath, fallbackPath];
			const tried = new Set<string>();

			for (const candidate of candidates) {
				if (!candidate || tried.has(candidate)) continue;
				tried.add(candidate);
				try {
					await openFile(candidate);
					if (cancelled) {
						return;
					}
					setSelectedFile(candidate);
					window.localStorage.setItem(lastOpenedPathKey, candidate);
					return;
				} catch (error) {
					if (candidate === storedPath) {
						window.localStorage.removeItem(lastOpenedPathKey);
					}
					console.debug("Initial file open failed", error);
				}
			}
		};

		void loadInitialFile();

		return () => {
			cancelled = true;
		};
	}, [containerId, lastOpenedPathKey, openFile, setSelectedFile]);

	const handleUpload = useCallback(
		async (file: File, destination?: string) => {
			const fallbackDestination = defaultDestination || "/app";
			const target = destination?.trim() || fallbackDestination;
			const result = await uploadFile(containerId, file, target);
			await refreshWorkspace();
			if (result && typeof (result as { dest?: string }).dest === "string") {
				const resolved = (result as { dest?: string }).dest ?? target;
				return resolved.trim() || target;
			}
			return target;
		},
		[containerId, defaultDestination, refreshWorkspace],
	);

	const handleDropFile = useCallback(
		async (destination: string, file: File) => {
			try {
				const effectiveDest = await handleUpload(file, destination);
				alertStore.push({
					message: `Uploaded ${file.name} → ${effectiveDest}`,
					variant: "success",
				});
			} catch (error) {
				const message = error instanceof Error ? error.message : "Upload failed";
				alertStore.push({ message, variant: "error" });
			}
		},
		[handleUpload],
	);

	const handleRun = useCallback(async () => {
		if (!runCommand) {
			alertStore.push({
				message: "No run command configured. Edit /app/config.json to set a run script.",
				variant: "info",
			});
			return;
		}

		setRunLoading(true);

		const trimmedPath = (previewPath || "/").trim();
		const normalizedPath = trimmedPath
			? trimmedPath.startsWith("/")
				? trimmedPath
				: `/${trimmedPath}`
			: "/";

		try {
			await handleSaveActiveFile();
		} catch (error) {
			const message = error instanceof Error ? error.message : "Failed to save file";
			alertStore.push({ message, variant: "error" });
		}

		const sent = await sendToActiveTerminal(runCommand);
		if (!sent) {
			setRunLoading(false);
			alertStore.push({
				message: "Open a terminal session before running the project.",
				variant: "warning",
			});
			return;
		}

		alertStore.push({ message: `Running "${runCommand}"`, variant: "success" });

		if (!runPort) {
			setRunLoading(false);
			alertStore.push({
				message:
					"There is no preview port configured in /app/config.json. Update it to enable the mini browser.",
				variant: "info",
			});
			return;
		}

		setShowPreview(true);
		const previewResult = await handlePreviewGo(normalizedPath);
		if (!previewResult.ok) {
			alertStore.push({
				message: previewResult.error ?? "Preview not ready yet. Start the app and try again.",
				variant: "warning",
			});
		}
		setRunLoading(false);
	}, [
		handlePreviewGo,
		handleSaveActiveFile,
		previewPath,
		runCommand,
		runPort,
		sendToActiveTerminal,
	]);

	useEffect(() => {
		const keyHandler = (event: KeyboardEvent) => {
			if (!(event.metaKey || event.ctrlKey)) {
				return;
			}
			const key = event.key.toLowerCase();
			if (key === "s") {
				event.preventDefault();
				void handleSaveActiveFile();
				return;
			}
			if (key === "enter") {
				event.preventDefault();
				void handleRun();
			}
		};
		window.addEventListener("keydown", keyHandler);
		return () => {
			window.removeEventListener("keydown", keyHandler);
		};
	}, [handleRun, handleSaveActiveFile]);

	const toggleSidebar = () => {
		setSidebarState((prev) => {
			const next = prev === "open" ? "collapsed" : "open";
			if (typeof window !== "undefined") {
				window.localStorage.setItem(`ide:${containerId}:sidebar`, next);
				window.dispatchEvent(new CustomEvent("terminal-resize", { detail: { target: "sidebar" } }));
			}
			if (next === "collapsed") {
				setShowSearch(false);
				setShowPreview(false);
			}
			return next;
		});
	};

	const toggleConsole = () => {
		setConsoleState((prev) => {
			const next = prev === "open" ? "collapsed" : "open";
			if (typeof window !== "undefined") {
				window.localStorage.setItem(`ide:${containerId}:console`, next);
				window.dispatchEvent(new CustomEvent("terminal-resize", { detail: { target: "console" } }));
			}
			return next;
		});
	};

	return (
		<div className="h-screen flex flex-col bg-slate-50 text-slate-900 dark:bg-[#0B1220] dark:text-gray-200">
			{showHeader ? <Header /> : null}

			<div className="flex flex-1 overflow-hidden">
				<ResizablePanel
					side="left"
					storageKey={`ide:${containerId}:sidebar:px`}
					defaultWidth={240}
					maxWidth={720}
					isCollapsed={isSidebarCollapsed}
					onResize={() => {
						window.dispatchEvent(
							new CustomEvent("terminal-resize", { detail: { target: "sidebar" } }),
						);
					}}
				>
					<div className="h-full flex flex-col">
						<div className="border-b border-slate-200 px-3 py-2 flex items-center justify-between bg-slate-100 dark:border-gray-800 dark:bg-[#111827]">
							<div className="flex items-center gap-1 text-slate-500 dark:text-gray-400">
								<button
									onClick={refreshTree}
									className="p-1 transition-colors hover:text-slate-900 dark:hover:text-white"
									title="Reload"
								>
									<RefreshDouble className="w-4 h-4" />
								</button>
								<button
									onClick={() =>
										handleFileAction("new-folder", activeSelection.path, activeSelection.type)
									}
									className="p-1 transition-colors hover:text-slate-900 dark:hover:text-white"
									title="Create folder"
								>
									<FolderPlus className="w-4 h-4" />
								</button>
								<button
									onClick={() =>
										handleFileAction("new-file", activeSelection.path, activeSelection.type)
									}
									className="p-1 transition-colors hover:text-slate-900 dark:hover:text-white"
									title="Create file"
								>
									<MultiplePagesPlus className="w-4 h-4" />
								</button>
								<button
									onClick={() => setUploadModalOpen(true)}
									className="p-1 transition-colors hover:text-slate-900 dark:hover:text-white"
									title="Upload"
								>
									<CloudUpload className="w-4 h-4" />
								</button>
								<button
									onClick={handleDownloadSelection}
									className="p-1 transition-colors hover:text-slate-900 dark:hover:text-white"
									title="Download"
								>
									<CloudDownload className="w-4 h-4" />
								</button>
								<button
									onClick={() => setShowSearch((prev) => !prev)}
									className={`p-1 transition-colors hover:text-slate-900 dark:hover:text-white ${showSearch ? "text-indigo-600 dark:text-white" : ""}`}
									title="Toggle search"
								>
									<Search className="w-4 h-4" />
								</button>
								<button
									onClick={() => setShowPreview((prev) => !prev)}
									className={`p-1 transition-colors hover:text-slate-900 dark:hover:text-white ${showPreview ? "text-indigo-600 dark:text-white" : ""}`}
									title="Toggle preview"
								>
									<Globe className="w-4 h-4" />
								</button>
								<button
									onClick={toggleSidebar}
									className="p-1 transition-colors hover:text-slate-900 dark:hover:text-white"
									title="Toggle sidebar"
								>
									<Menu className="w-4 h-4" />
								</button>
							</div>
						</div>

						{showSearch && (
							<div className="border-b border-slate-200 bg-slate-100 px-3 py-3 space-y-3 dark:border-gray-800 dark:bg-[#0B1220]">
								<div className="space-y-2">
									<input
										type="text"
										value={searchPattern}
										onChange={(event) => setSearchPattern(event.target.value)}
										onKeyDown={handleSearchKey}
										placeholder="Search pattern..."
										className="w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-800 dark:bg-[#111827] dark:text-gray-200"
									/>
									<div className="flex flex-col gap-2 sm:flex-row">
										<input
											type="text"
											value={searchInclude}
											onChange={(event) => setSearchInclude(event.target.value)}
											placeholder="Include globs (comma separated)"
											className="flex-1 rounded border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-800 dark:bg-[#111827] dark:text-gray-200"
										/>
										<input
											type="text"
											value={searchExclude}
											onChange={(event) => setSearchExclude(event.target.value)}
											placeholder="Exclude directories"
											className="flex-1 rounded border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-800 dark:bg-[#111827] dark:text-gray-200"
										/>
									</div>
								</div>

								<div className="flex flex-wrap items-center justify-between gap-3 text-xs text-slate-600 dark:text-gray-400">
									<label className="inline-flex items-center gap-2">
										<input
											type="checkbox"
											className="h-3.5 w-3.5 rounded border border-slate-400 bg-transparent accent-indigo-500 dark:border-gray-600"
											checked={searchCaseSensitive}
											onChange={(event) => setSearchCaseSensitive(event.target.checked)}
										/>
										Case sensitive
									</label>
									<div className="flex items-center gap-2">
										<button
											type="button"
											onClick={handleClearSearch}
											className="rounded border border-slate-300 px-3 py-1.5 text-xs uppercase tracking-wide text-slate-600 transition hover:border-slate-400 hover:text-slate-900 dark:border-gray-700 dark:text-gray-300 dark:hover:border-gray-500 dark:hover:text-white"
										>
											Clear
										</button>
										<button
											type="button"
											onClick={() => void handleSearch()}
											disabled={searchLoading}
											className="inline-flex items-center gap-2 rounded border border-indigo-500 bg-indigo-500 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-white transition hover:bg-indigo-600 disabled:cursor-not-allowed disabled:opacity-60"
										>
											{searchLoading ? (
												<span className="h-3.5 w-3.5 animate-spin rounded-full border border-white/60 border-t-transparent" />
											) : (
												"Search"
											)}
										</button>
									</div>
								</div>

								<div className="max-h-64 overflow-y-auto rounded border border-slate-200 bg-white dark:border-gray-800 dark:bg-[#0B1220]">
									{searchLoading ? (
										<div className="flex items-center justify-center gap-2 px-4 py-6 text-xs text-slate-500 dark:text-gray-400">
											<span className="h-4 w-4 animate-spin rounded-full border border-indigo-400 border-t-transparent" />
											Searching...
										</div>
									) : searchResults.length > 0 ? (
										<ul className="divide-y divide-slate-200 text-sm text-slate-700 dark:divide-gray-800 dark:text-gray-200">
											{searchResults.map((result) => {
												const relativePath = result.path.startsWith("/app/")
													? result.path.slice(5)
													: result.path;
												const firstMatchLine = result.matches[0]?.line ?? undefined;
												return (
													<li key={result.path} className="px-3 py-2">
														<button
															type="button"
															onClick={() => {
																void handleSearchResultClick(result.path, firstMatchLine);
															}}
															className="w-full text-left text-slate-700 hover:text-slate-900 dark:text-gray-200 dark:hover:text-white"
														>
															<div className="font-mono text-xs uppercase tracking-wide text-indigo-300">
																{relativePath}
															</div>
															<div className="text-[11px] text-slate-500 dark:text-gray-400">
																{result.matches.length} match
																{result.matches.length === 1 ? "" : "es"}
															</div>
														</button>
														{result.matches.length > 0 ? (
															<ul className="mt-2 space-y-1 text-xs text-slate-600 dark:text-gray-300">
																{result.matches.map((match, index) => (
																	<li key={`${result.path}:${match.line}:${index}`}>
																		<button
																			type="button"
																			onClick={() => {
																				void handleSearchResultClick(result.path, match.line);
																			}}
																			className="w-full rounded border border-transparent px-2 py-1 text-left font-mono hover:border-indigo-600 hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-[#111827] dark:hover:text-white"
																		>
																			<span className="text-indigo-300">L{match.line}:</span>{" "}
																			{match.preview || "(no preview)"}
																		</button>
																	</li>
																))}
															</ul>
														) : null}
													</li>
												);
											})}
										</ul>
									) : searchPerformed ? (
										<div className="px-4 py-6 text-xs text-slate-600 dark:text-gray-400">
											No results found.
										</div>
									) : (
										<div className="px-4 py-6 text-xs text-slate-500 dark:text-gray-500">
											Enter a pattern and run a search to see matching files.
										</div>
									)}
								</div>
							</div>
						)}

						{showPreview && (
							<div className="border-b border-slate-200 bg-slate-100 dark:border-gray-800 dark:bg-[#0B1220]">
								<div className="px-3 py-3 space-y-2">
									<div className="flex flex-col gap-2 sm:flex-row sm:items-center">
										<input
											type="text"
											value={previewPath}
											onChange={(event) => setPreviewPath(event.target.value)}
											placeholder="/"
											className="flex-1 rounded border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-700 dark:bg-[#111827] dark:text-gray-200"
										/>
										<button
											type="button"
											className="inline-flex items-center justify-center rounded bg-indigo-600 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
											disabled={previewLoading || !runPort}
											onClick={() => void handlePreviewGo()}
										>
											{previewLoading ? (
												<span className="h-3.5 w-3.5 animate-spin rounded-full border border-white/60 border-t-transparent" />
											) : (
												"Go"
											)}
										</button>
									</div>
									<div className="flex flex-wrap items-center gap-4 text-xs text-slate-600 dark:text-gray-400">
										<button
											type="button"
											onClick={handlePreviewRefresh}
											disabled={previewLoading || !runPort}
											className="underline decoration-dotted underline-offset-4 transition hover:text-slate-900 disabled:cursor-not-allowed disabled:text-slate-400 dark:hover:text-white dark:disabled:text-gray-600"
										>
											Refresh
										</button>
										<button
											type="button"
											onClick={handlePreviewPopout}
											disabled={!previewTargetUrl}
											className="underline decoration-dotted underline-offset-4 transition hover:text-slate-900 disabled:cursor-not-allowed disabled:text-slate-400 dark:hover:text-white dark:disabled:text-gray-600"
										>
											Pop out
										</button>
										{runPort ? (
											<span>Preview port: {runPort}</span>
										) : (
											<span className="text-amber-500">
												Add a <code>port</code> in <code>/app/config.json</code> to enable preview.
											</span>
										)}
									</div>
									{previewError ? (
										<p className="text-xs text-red-400">{previewError}</p>
									) : previewTargetUrl ? (
										<p className="text-xs text-slate-500 dark:text-gray-400">
											Connected to {previewTargetUrl}
										</p>
									) : (
										<p className="text-xs text-slate-500 dark:text-gray-500">
											Run the project and click Go to load the preview.
										</p>
									)}
								</div>
								<iframe
									title="Preview"
									src={previewTargetUrl ?? "about:blank"}
									className="w-full border-t border-slate-200 bg-white dark:border-gray-800 dark:bg-[#0B1220]"
									style={{ minHeight: "220px" }}
								/>
							</div>
						)}

						<FileTree
							fileTree={fileTree}
							selectedFile={selectedFile}
							onSelect={onFileSelect}
							onToggle={handleToggleFolder}
							onAction={handleFileAction}
							onDropFile={handleDropFile}
						/>
					</div>
				</ResizablePanel>

				<div className="relative flex flex-1 flex-col overflow-hidden">
					<div className="flex flex-1 flex-col overflow-hidden">
						<FileTabs
							tabs={tabs}
							activeTab={activeTab}
							onTabChange={handleTabChange}
							onTabClose={handleCloseTab}
							rightActions={
								<div className="flex flex-wrap items-center gap-2">
									<button
										type="button"
										className="inline-flex items-center gap-1 md:gap-2 rounded border border-gray-700 px-3 py-1.5 text-xs text-gray-200 transition hover:border-indigo-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
										onClick={() => void handleSaveActiveFile()}
										disabled={tabs.length === 0}
										aria-label="Save file"
									>
										<FloppyDisk className="h-4 w-4" />
										<span className="hidden md:inline">Save</span>
									</button>
									<button
										type="button"
										className="inline-flex items-center gap-1 md:gap-2 rounded bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-indigo-600/60"
										onClick={() => void handleRun()}
										disabled={runLoading || !runCommand}
										title={
											runCommand
												? `Run "${runCommand}"`
												: "Define the run command in /app/config.json"
										}
										aria-label={runCommand ? `Run ${runCommand}` : "Run command"}
									>
										{runLoading ? (
											<span className="h-3.5 w-3.5 animate-spin rounded-full border border-white/70 border-t-transparent" />
										) : (
											<Play className="h-4 w-4" />
										)}
										<span className="hidden md:inline">{runLoading ? "Running..." : "Run"}</span>
									</button>
								</div>
							}
						/>
						<Editor
							content={editorContent}
							onChange={setEditorContent}
							theme={theme}
							language={editorLanguage}
							isMobile={isMobile}
						/>
					</div>
					<TerminalPanel
						terminalTabs={terminalTabs}
						activeTerminalId={activeTerminalId}
						onTabChange={setActiveTerminalId}
						onTabClose={handleCloseTerminal}
						onNewTab={handleNewTerminal}
						isCollapsed={isTerminalCollapsed}
						onToggleCollapse={toggleConsole}
						storageKey={`ide:${containerId}:console:px`}
						onToggleSidebar={toggleSidebar}
						onThemeClick={() => themeManager.toggle()}
						onTemplatesClick={() => setTemplatesModalOpen(true)}
						onGithubClick={() => setGithubModalOpen(true)}
						onAiClick={() => setAiPanelOpen(true)}
						onRunCommand={handleRun}
						onSaveActive={handleSaveActiveFile}
						onOpenFile={openFileFromSlash}
						onListSessions={listSessions}
						onClearActive={clearTerminal}
						onSendCommand={sendToActiveTerminal}
						theme={theme}
					/>
				</div>
			</div>

			<UploadModal
				isOpen={isUploadModalOpen}
				onClose={() => setUploadModalOpen(false)}
				onUpload={handleUpload}
				initialDestination={defaultDestination}
			/>
			<TemplatesModal
				isOpen={isTemplatesModalOpen}
				onClose={() => setTemplatesModalOpen(false)}
				templates={templates}
				loading={templatesLoading}
				error={templatesError}
				onReload={loadTemplates}
				onApply={handleTemplateApply}
				defaultDestination={defaultDestination}
			/>
			<GithubModal
				isOpen={isGithubModalOpen}
				onClose={() => setGithubModalOpen(false)}
				onClone={handleGithubClone}
			/>
			<AiAssistantPanel
				isOpen={isAiPanelOpen}
				onClose={() => setAiPanelOpen(false)}
				containerId={containerId}
			/>
		</div>
	);
};

const IDE: React.FC = () => {
	const [searchParams] = useSearchParams();
	const rawId = (searchParams.get("containerId") ?? "").trim();
	const shouldShowHeader = !searchParams.has("showHeader");

	if (!rawId) {
		return <MissingContainer showHeader={shouldShowHeader} />;
	}

	return <IDELayout containerId={rawId} showHeader={shouldShowHeader} />;
};

export default IDE;
