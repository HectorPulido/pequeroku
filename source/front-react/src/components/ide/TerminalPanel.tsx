import { FitAddon } from "@xterm/addon-fit";
import type { ITheme } from "@xterm/xterm";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import {
	GithubCircle,
	Menu,
	MultiplePagesPlus,
	NavArrowDown,
	SparksSolid,
	TerminalTag,
	Xmark,
} from "iconoir-react";
import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createSlashCommandHandler } from "@/lib/slashCommands";
import type { Theme } from "@/lib/theme";
import type { TerminalTab } from "@/types/ide";

const ensureViewport = (terminal: Terminal) => {
	const element = terminal.element;
	if (!element) return;
	const viewport = element.querySelector(".xterm-viewport") as HTMLElement | null;
	if (viewport) {
		viewport.style.overflowY = "auto";
		viewport.style.overscrollBehavior = "contain";
		viewport.style.scrollbarWidth = "thin";
		viewport.style.setProperty("-webkit-overflow-scrolling", "touch");
	}
};

const TERMINAL_THEMES: Record<Theme, ITheme> = {
	dark: {
		background: "#0B1220",
		foreground: "#E5E7EB",
		cursor: "#E5E7EB",
		black: "#1F2937",
		red: "#EF4444",
		green: "#22C55E",
		yellow: "#F59E0B",
		blue: "#4F46E5",
		magenta: "#A855F7",
		cyan: "#06B6D4",
		white: "#E5E7EB",
		brightBlack: "#1F2937",
		brightRed: "#F87171",
		brightGreen: "#34D399",
		brightYellow: "#FBBF24",
		brightBlue: "#6366F1",
		brightMagenta: "#C084FC",
		brightCyan: "#22D3EE",
		brightWhite: "#F3F4F6",
	},
	light: {
		background: "#FFFFFF",
		foreground: "#1E293B",
		cursor: "#1E293B",
		black: "#CBD5F5",
		red: "#DC2626",
		green: "#16A34A",
		yellow: "#D97706",
		blue: "#2563EB",
		magenta: "#9333EA",
		cyan: "#0891B2",
		white: "#0F172A",
		brightBlack: "#94A3B8",
		brightRed: "#B91C1C",
		brightGreen: "#15803D",
		brightYellow: "#B45309",
		brightBlue: "#1D4ED8",
		brightMagenta: "#7E22CE",
		brightCyan: "#0E7490",
		brightWhite: "#0B1120",
	},
};

const TerminalPanel: React.FC<{
	terminalTabs: TerminalTab[];
	activeTerminalId: string | null;
	onTabChange: (id: string) => void;
	onTabClose: (id: string) => void;
	onNewTab: (sid?: string) => void;
	isCollapsed: boolean;
	onToggleCollapse: () => void;
	storageKey: string;
	onToggleSidebar: () => void;
	onThemeClick: () => void;
	onTemplatesClick: () => void;
	onGithubClick: () => void;
	onAiClick: () => void;
	onRunCommand: () => Promise<void> | void;
	onSaveActive: () => Promise<void> | void;
	onOpenFile: (path: string) => Promise<void> | void;
	onListSessions: () => string[];
	onClearActive: (sid: string | null) => void;
	onSendCommand: (data: string) => Promise<boolean>;
	theme: Theme;
}> = ({
	terminalTabs,
	activeTerminalId,
	onTabChange,
	onTabClose,
	onNewTab,
	isCollapsed,
	onToggleCollapse,
	storageKey,
	onToggleSidebar,
	onThemeClick,
	onTemplatesClick,
	onGithubClick,
	onAiClick,
	onRunCommand,
	onSaveActive,
	onOpenFile,
	onListSessions,
	onClearActive,
	onSendCommand,
	theme,
}) => {
	const terminalRefs = useRef<Record<string, HTMLDivElement | null>>({});
	const terminalsInitialized = useRef<Record<string, boolean>>({});
	const containerRef = useRef<HTMLDivElement>(null);
	const dragSnapshot = useRef<{ startY: number; startHeight: number }>({
		startY: 0,
		startHeight: 320,
	});
	const shortcutRef = useRef<HTMLDivElement | null>(null);
	const [command, setCommand] = useState("");
	const [showShortcutMenu, setShowShortcutMenu] = useState(false);

	const fitTerminal = useCallback((tab: TerminalTab | null) => {
		if (!tab?.terminal || !tab.fitAddon) return;
		const element = tab.terminal.element;
		if (!element) return;
		const parent = element.parentElement;
		if (!parent) return;
		if (parent.clientWidth <= 0 || parent.clientHeight <= 0) {
			return;
		}
		try {
			tab.fitAddon.fit();
		} catch (error) {
			console.error("terminal fit failed", error);
		}
	}, []);

	const fitAllTerminals = useCallback(() => {
		terminalTabs.forEach((tab) => {
			fitTerminal(tab ?? null);
		});
	}, [fitTerminal, terminalTabs]);

	useEffect(() => {
		const knownIds = new Set(terminalTabs.map((tab) => tab.id));
		Object.keys(terminalsInitialized.current).forEach((id) => {
			if (!knownIds.has(id)) {
				delete terminalsInitialized.current[id];
			}
		});
	}, [terminalTabs]);

	useEffect(() => {
		// Lazily bootstrap xterm containers
		terminalTabs.forEach((tab) => {
			const container = terminalRefs.current[tab.id];
			if (container && !terminalsInitialized.current[tab.id]) {
				const terminal = new Terminal({
					cursorBlink: true,
					fontSize: 13,
					fontFamily: 'Menlo, Monaco, "Courier New", monospace',
					theme: TERMINAL_THEMES[theme],
					scrollback: 2000,
				});

				const fitAddon = new FitAddon();
				terminal.loadAddon(fitAddon);

				terminal.open(container);
				tab.terminal = terminal;
				tab.fitAddon = fitAddon;
				terminalsInitialized.current[tab.id] = true;
				ensureViewport(terminal);
				fitTerminal(tab);
				requestAnimationFrame(() => fitTerminal(tab));

				if (tab.service) {
					tab.service.onMessage((e) => {
						if (!tab.terminal) return;
						if (e.data instanceof ArrayBuffer) {
							tab.terminal.write(new Uint8Array(e.data));
						} else if (typeof e.data === "string") {
							tab.terminal.write(e.data);
						}
					});

					terminal.onData((data) => {
						if (tab.service) {
							tab.service.send(data);
						}
					});
				}
			}
		});
	}, [fitTerminal, terminalTabs, theme]);

	useEffect(() => {
		terminalTabs.forEach((tab) => {
			if (!tab.terminal) return;
			try {
				tab.terminal.options.theme = { ...TERMINAL_THEMES[theme] };
				const rows = tab.terminal.rows ?? 0;
				if (rows > 0) {
					tab.terminal.refresh(0, rows - 1);
				}
			} catch (error) {
				console.error("terminal theme update failed", error);
			}
		});
	}, [terminalTabs, theme]);

	useEffect(() => {
		const active = terminalTabs.find((tab) => tab.id === activeTerminalId);
		active?.terminal?.focus();
	}, [activeTerminalId, terminalTabs]);

	useEffect(() => {
		terminalTabs.forEach((tab) => {
			if (tab.terminal) {
				ensureViewport(tab.terminal);
			}
		});
		fitAllTerminals();
	}, [fitAllTerminals, terminalTabs]);

	useEffect(() => {
		if (isCollapsed) return;
		requestAnimationFrame(() => fitAllTerminals());
	}, [fitAllTerminals, isCollapsed]);

	useEffect(() => {
		const handleResize = () => {
			fitAllTerminals();
		};
		const handleCustomResize = () => {
			fitAllTerminals();
		};
		window.addEventListener("resize", handleResize);
		window.addEventListener("terminal-resize", handleCustomResize);
		return () => {
			window.removeEventListener("resize", handleResize);
			window.removeEventListener("terminal-resize", handleCustomResize);
		};
	}, [fitAllTerminals]);

	const readInitialHeight = () => {
		if (typeof window === "undefined") return 320;
		const savedHeight = window.localStorage.getItem(storageKey);
		return savedHeight ? parseInt(savedHeight, 10) : 320;
	};

	const [height, setHeight] = useState(readInitialHeight);
	const [isResizing, setIsResizing] = useState(false);

	const handleDrag = useCallback(
		(event: MouseEvent) => {
			if (!isResizing) return;
			const { startY, startHeight } = dragSnapshot.current;
			const delta = startY - event.clientY;
			const newHeight = Math.max(180, Math.min(640, startHeight + delta));
			setHeight(newHeight);
		},
		[isResizing],
	);

	const handleStopDrag = useCallback(() => {
		if (!isResizing) return;
		setIsResizing(false);
		if (typeof window !== "undefined") {
			window.localStorage.setItem(storageKey, String(height));
			window.dispatchEvent(new CustomEvent("terminal-resize", { detail: { target: "console" } }));
		}
	}, [height, isResizing, storageKey]);

	useEffect(() => {
		if (!isResizing) return;
		document.addEventListener("mousemove", handleDrag);
		document.addEventListener("mouseup", handleStopDrag);
		return () => {
			document.removeEventListener("mousemove", handleDrag);
			document.removeEventListener("mouseup", handleStopDrag);
		};
	}, [handleDrag, handleStopDrag, isResizing]);

	const getActiveTab = useCallback(
		() => terminalTabs.find((tab) => tab.id === activeTerminalId) ?? null,
		[terminalTabs, activeTerminalId],
	);

	const addLine = useCallback(
		(text: string) => {
			const active = getActiveTab();
			if (!active?.terminal) return;
			active.terminal.write(`\r\n${text}\r\n`);
		},
		[getActiveTab],
	);

	const slash = useMemo(
		() =>
			createSlashCommandHandler({
				addLine,
				getActiveSession: () => activeTerminalId,
				clear: (sid) => onClearActive(sid ?? activeTerminalId),
				openAi: onAiClick,
				openGithub: onGithubClick,
				toggleTheme: onThemeClick,
				listSessions: onListSessions,
				openSession: (sid) => onNewTab(sid),
				closeSession: (sid) => onTabClose(sid),
				focusSession: (sid) => onTabChange(sid),
				run: async () => {
					await onRunCommand();
				},
				openFile: async (path) => {
					await onOpenFile(path);
				},
				saveFile: async () => {
					await onSaveActive();
				},
			}),
		[
			addLine,
			activeTerminalId,
			onAiClick,
			onClearActive,
			onGithubClick,
			onListSessions,
			onNewTab,
			onOpenFile,
			onRunCommand,
			onSaveActive,
			onTabChange,
			onTabClose,
			onThemeClick,
		],
	);

	const sendCommand = async (raw: string) => {
		const trimmed = raw.trim();
		const active = getActiveTab();
		if (!active) return;
		if (trimmed.startsWith("/") && slash.handle(trimmed)) {
			active.terminal?.write(`\r\n${trimmed}\r\n`);
			setCommand("");
			setShowShortcutMenu(false);
			return;
		}
		const payload = raw.endsWith("\r") ? raw : `${raw}\r`;
		try {
			const sent = await onSendCommand(payload);
			if (!sent) {
				return;
			}
			setCommand("");
			setShowShortcutMenu(false);
		} catch (error) {
			console.error("terminal send failed", error);
		}
	};

	const handleShortcut = (kind: "ctrlc" | "ctrld" | "clear" | "reload") => {
		const active = getActiveTab();
		if (!active) return;
		switch (kind) {
			case "ctrlc":
				active.service?.send("\u0003");
				break;
			case "ctrld":
				active.service?.send("\u0004");
				break;
			case "clear":
				active.terminal?.clear();
				onClearActive(active.id);
				break;
			case "reload":
				onNewTab();
				onTabClose(active.id);
				break;
			default:
				break;
		}
		setShowShortcutMenu(false);
	};

	useEffect(() => {
		if (!showShortcutMenu) return;
		const handleClickOutside = (event: MouseEvent) => {
			if (!shortcutRef.current) return;
			if (!shortcutRef.current.contains(event.target as Node)) {
				setShowShortcutMenu(false);
			}
		};
		document.addEventListener("mousedown", handleClickOutside);
		return () => {
			document.removeEventListener("mousedown", handleClickOutside);
		};
	}, [showShortcutMenu]);

	const containerStyle = isCollapsed ? {} : { height: `${height}px` };

	return (
		<div
			ref={containerRef}
			className="border-t border-slate-200 bg-white flex flex-col flex-none overflow-hidden dark:border-gray-800 dark:bg-[#0B1220]"
			style={containerStyle}
			aria-hidden={isCollapsed}
		>
			<button
				type="button"
				aria-label="Resize console"
				className={`h-1 cursor-row-resize bg-transparent transition-colors hover:bg-indigo-600 ${isCollapsed ? "hidden" : ""}`}
				onMouseDown={(event) => {
					event.preventDefault();
					dragSnapshot.current = {
						startY: event.clientY,
						startHeight: containerRef.current?.getBoundingClientRect().height ?? height,
					};
					setIsResizing(true);
				}}
				onDoubleClick={() => {
					const initial = readInitialHeight();
					setHeight(initial);
					if (typeof window !== "undefined") {
						window.localStorage.setItem(storageKey, String(initial));
					}
				}}
				onKeyDown={(event) => {
					const step = 20;
					if (event.key === "Enter") {
						const initial = readInitialHeight();
						setHeight(initial);
						if (typeof window !== "undefined") {
							window.localStorage.setItem(storageKey, String(initial));
						}
						event.preventDefault();
						return;
					}
					if (event.key === "ArrowUp" || event.key === "ArrowDown") {
						const delta = event.key === "ArrowUp" ? step : -step;
						const next = Math.max(180, Math.min(640, height + delta));
						setHeight(next);
						if (typeof window !== "undefined") {
							window.localStorage.setItem(storageKey, String(next));
						}
						event.preventDefault();
					}
				}}
			></button>

			<div
				className={`flex items-center justify-between border-b border-slate-200 bg-slate-100 px-2 min-h-9 dark:border-gray-800 dark:bg-[#111827] ${isCollapsed ? "hidden" : ""}`}
			>
				<div className="flex items-center overflow-x-auto">
					{terminalTabs.map((tab) => {
						const isActive = activeTerminalId === tab.id;
						return (
							<button
								key={tab.id}
								onClick={() => onTabChange(tab.id)}
								className={`flex items-center gap-2 border-r border-slate-200 px-3 py-1.5 text-xs dark:border-gray-800 ${
									isActive
										? "bg-slate-200 text-slate-900 dark:bg-[#0B1220] dark:text-white"
										: "text-slate-500 dark:text-gray-400"
								}`}
							>
								<button
									type="button"
									className={`flex items-center gap-2 ${isActive ? "" : "hover:text-slate-900 dark:hover:text-white"}`}
								>
									<span>{tab.title}</span>
								</button>
								<button
									type="button"
									onClick={() => onTabClose(tab.id)}
									className="hover:text-red-400"
									aria-label={`Close terminal ${tab.title}`}
								>
									<Xmark className="w-3 h-3" />
								</button>
							</button>
						);
					})}
				</div>
				<div className="flex items-center gap-2">
					<button
						type="button"
						onClick={() => onNewTab()}
						className="text-slate-500 hover:text-slate-900 text-xs px-2 py-1 dark:text-gray-400 dark:hover:text-white"
					>
						<MultiplePagesPlus className="w-4 h-4 inline-block mr-1" />
						New
					</button>
					<button
						type="button"
						onClick={onToggleCollapse}
						className="text-slate-500 hover:text-slate-900 text-xs px-2 py-1 dark:text-gray-400 dark:hover:text-white"
					>
						Close
					</button>
				</div>
			</div>

			<div className={`flex-1 relative overflow-hidden ${isCollapsed ? "hidden" : ""}`}>
				{terminalTabs.map((tab) => (
					<div
						key={tab.id}
						ref={(el) => {
							terminalRefs.current[tab.id] = el;
						}}
						className="absolute inset-0"
						style={{ display: activeTerminalId === tab.id ? "block" : "none" }}
					/>
				))}
			</div>

			<div
				className={`border-t border-slate-200 bg-slate-100 px-4 py-3 flex items-center gap-3 text-xs text-slate-600 dark:border-gray-800 dark:bg-[#111827] dark:text-gray-300 ${isCollapsed ? "hidden" : ""}`}
			>
				<input
					value={command}
					onChange={(event) => setCommand(event.target.value)}
					placeholder="bash command..."
					className="flex-1 rounded border border-slate-300 bg-white px-3 py-1 text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-gray-800 dark:bg-[#0B1220] dark:text-gray-200"
					onKeyDown={(event) => {
						if (event.key === "Enter" && command.trim()) {
							event.preventDefault();
							sendCommand(command);
						}
					}}
				/>
				<button
					className="bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-1 rounded"
					onClick={() => {
						if (!command) return;
						sendCommand(command);
					}}
				>
					Send
				</button>
				<div className="relative" ref={shortcutRef}>
					<button
						onClick={() => setShowShortcutMenu((prev) => !prev)}
						aria-label="Toggle terminal shortcuts"
						title="Terminal shortcuts"
						className="flex items-center gap-0 md:gap-1 rounded border border-slate-300 bg-white px-2 py-1 text-slate-600 hover:text-slate-900 dark:border-gray-800 dark:bg-[#0B1220] dark:text-gray-300 dark:hover:text-white"
					>
						<NavArrowDown
							className={`w-4 h-4 transition-transform ${showShortcutMenu ? "rotate-180" : ""}`}
						/>
						<span className="sr-only">Shortcuts</span>
					</button>
					{showShortcutMenu && (
						<div className="absolute right-0 bottom-full mb-1 w-40 rounded border border-slate-200 bg-white py-1 text-xs text-slate-600 shadow-lg z-20 dark:border-gray-800 dark:bg-[#111827] dark:text-gray-300">
							<button
								onClick={() => handleShortcut("ctrld")}
								className="w-full text-left px-3 py-1.5 hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-[#1f2937] dark:text-gray-300 dark:hover:text-white"
							>
								Ctrl+D
							</button>
							<button
								onClick={() => handleShortcut("ctrlc")}
								className="w-full text-left px-3 py-1.5 hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-[#1f2937] dark:text-gray-300 dark:hover:text-white"
							>
								Ctrl+C
							</button>
							<button
								onClick={() => handleShortcut("clear")}
								className="w-full text-left px-3 py-1.5 hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-[#1f2937] dark:text-gray-300 dark:hover:text-white"
							>
								Clear
							</button>
							<button
								onClick={() => handleShortcut("reload")}
								className="w-full text-left px-3 py-1.5 hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-[#1f2937] dark:text-gray-300 dark:hover:text-white"
							>
								Reload console
							</button>
						</div>
					)}
				</div>
			</div>

			<div className="border-t border-slate-200 bg-slate-100 px-4 py-2 flex items-center justify-between text-xs text-slate-600 dark:border-gray-800 dark:bg-[#0B1220] dark:text-gray-300">
				<div className="flex items-center gap-2">
					<button
						onClick={onToggleSidebar}
						aria-label="Toggle tree panel"
						className="flex items-center gap-0 md:gap-2 hover:text-slate-900 dark:hover:text-white"
					>
						<Menu className="w-4 h-4" />
						<span className="hidden md:inline">Toggle tree</span>
					</button>
				</div>
				<div className="flex items-center gap-2">
					<button
						onClick={onTemplatesClick}
						aria-label="Open templates modal"
						className="flex items-center gap-0 md:gap-2 hover:text-slate-900 dark:hover:text-white"
					>
						<MultiplePagesPlus className="w-4 h-4" />
						<span className="hidden md:inline">Templates</span>
					</button>
					<button
						onClick={onGithubClick}
						aria-label="Open GitHub modal"
						className="flex items-center gap-0 md:gap-2 hover:text-slate-900 dark:hover:text-white"
					>
						<GithubCircle className="w-4 h-4" />
						<span className="hidden md:inline">Github</span>
					</button>
					<button
						onClick={onAiClick}
						aria-label="Open AI panel"
						className="flex items-center gap-0 md:gap-1 hover:text-slate-900 dark:hover:text-white"
					>
						<SparksSolid className="w-4 h-4" />
						<span className="hidden md:inline">AI</span>
					</button>
					<button
						onClick={onToggleCollapse}
						aria-label="Toggle console visibility"
						className="flex items-center gap-0 md:gap-2 hover:text-slate-900 dark:hover:text-white"
					>
						<TerminalTag className="w-4 h-4" />
						<span className="hidden md:inline">Toggle console</span>
					</button>
				</div>
			</div>
		</div>
	);
};

export default TerminalPanel;
