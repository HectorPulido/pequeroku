import { Collapse, Expand, Globe, OpenNewWindow, RefreshDouble, Xmark } from "iconoir-react";
import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import PortSelector from "@/components/ide/PortSelector";
import { usePreviewPorts } from "@/hooks/usePreviewPorts";
import { alertStore } from "@/lib/alertStore";
import { BROWSER_DOCK_MESSAGE, isEmbeddedInDock, postBrowserDockMessage } from "@/lib/browserDock";
import { fetchRunConfig, pollPreview } from "@/services/ide/actions";

const normalizePath = (raw: string): string => {
	const trimmed = raw.trim();
	if (!trimmed) return "/";
	return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
};

const parsePortParam = (raw: string | null): number | null => {
	if (!raw) return null;
	const value = Number.parseInt(raw, 10);
	return Number.isFinite(value) ? value : null;
};

/**
 * Standalone embedded browser. Rendered at `/browser?containerId=…` and embedded
 * by the IDE and AI studio through an iframe (`BrowserDock`), so both hosts get
 * the exact same preview UI. When embedded it exposes expand (fullscreen) and
 * close controls that drive the host panel via `postMessage`; opened directly in
 * a tab it is already fullscreen, so those controls are hidden.
 */
const BrowserPage: React.FC = () => {
	const [searchParams] = useSearchParams();
	const containerId = (searchParams.get("containerId") ?? "").trim();
	const initialPort = parsePortParam(searchParams.get("port"));
	const initialPath = normalizePath(searchParams.get("path") ?? "/");

	const [configPort, setConfigPort] = useState<number | null>(initialPort);
	const { selectedPort, setSelectedPort, portOptions, rescanPorts } = usePreviewPorts(
		containerId,
		configPort,
	);
	const [path, setPath] = useState(initialPath);
	const [targetUrl, setTargetUrl] = useState<string | null>(null);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [expanded, setExpanded] = useState(false);
	const autoLoadedRef = useRef(false);
	const embedded = isEmbeddedInDock();

	// Load the run config port (the preferred default) and kick off port detection.
	// initialPort is derived from the (stable) query string, so re-run on container only.
	// biome-ignore lint/correctness/useExhaustiveDependencies: reset-on-container-change
	useEffect(() => {
		if (!containerId) return;
		let cancelled = false;
		autoLoadedRef.current = false;
		setConfigPort(initialPort);
		setTargetUrl(null);
		setError(null);
		void fetchRunConfig(containerId)
			.then(({ port }) => {
				if (!cancelled) setConfigPort(port ?? initialPort);
			})
			.catch(() => {
				if (!cancelled) setConfigPort(initialPort);
			});
		void rescanPorts();
		return () => {
			cancelled = true;
		};
	}, [containerId, rescanPorts]);

	const go = useCallback(
		async (rawPath?: string) => {
			if (!selectedPort) {
				setError("No preview port selected. Pick a detected port or set one in /app/config.json.");
				return;
			}
			const normalized = normalizePath(rawPath ?? path);
			setPath(normalized);
			setLoading(true);
			setError(null);
			try {
				const response = await pollPreview({
					containerId,
					port: selectedPort,
					path: normalized,
					attempts: 6,
					delayMs: 900,
				});
				if (!response) {
					setTargetUrl(null);
					setError("Preview not ready yet. Start the app and try again.");
					return;
				}
				setTargetUrl(response.url);
			} catch (err) {
				setTargetUrl(null);
				setError(err instanceof Error ? err.message : "Failed to load preview");
			} finally {
				setLoading(false);
			}
		},
		[containerId, path, selectedPort],
	);

	// Auto-load once a port is known so the app shows up without a manual "Go".
	useEffect(() => {
		if (!selectedPort || autoLoadedRef.current) return;
		autoLoadedRef.current = true;
		void go("/");
	}, [go, selectedPort]);

	const popOut = useCallback(() => {
		if (!targetUrl) {
			alertStore.push({ message: "Open the preview before using pop out.", variant: "info" });
			return;
		}
		window.open(targetUrl, "_blank", "noopener,noreferrer");
	}, [targetUrl]);

	const toggleExpand = useCallback(() => {
		setExpanded((prev) => {
			const next = !prev;
			postBrowserDockMessage({ source: BROWSER_DOCK_MESSAGE, type: "expand", expanded: next });
			return next;
		});
	}, []);

	const close = useCallback(() => {
		postBrowserDockMessage({ source: BROWSER_DOCK_MESSAGE, type: "close" });
	}, []);

	if (!containerId) {
		return (
			<div className="flex h-screen items-center justify-center bg-[#0B1220] px-6 text-sm text-gray-300">
				Missing <code className="mx-1 rounded bg-[#111827] px-1">containerId</code> query parameter.
			</div>
		);
	}

	return (
		<div className="flex h-screen flex-col bg-[#0B1220]">
			<div className="flex items-center gap-2 border-b border-gray-800 px-3 py-2.5">
				<Globe className="h-4 w-4 text-gray-400" />
				<span className="text-sm font-semibold text-white">Browser</span>
				{selectedPort ? <span className="text-[11px] text-gray-500">:{selectedPort}</span> : null}
				{embedded ? (
					<div className="ml-auto flex items-center gap-1.5">
						<button
							type="button"
							onClick={toggleExpand}
							title={expanded ? "Restore" : "Expand"}
							aria-label={expanded ? "Restore preview" : "Expand preview"}
							className="rounded border border-gray-800 p-1 text-gray-400 transition hover:border-indigo-500 hover:text-white"
						>
							{expanded ? <Collapse className="h-4 w-4" /> : <Expand className="h-4 w-4" />}
						</button>
						<button
							type="button"
							onClick={close}
							title="Close"
							aria-label="Close preview"
							className="rounded border border-gray-800 p-1 text-gray-400 transition hover:border-rose-500 hover:text-white"
						>
							<Xmark className="h-4 w-4" />
						</button>
					</div>
				) : null}
			</div>

			<div className="flex items-center gap-2 border-b border-gray-800 px-3 py-2">
				<PortSelector
					value={selectedPort}
					options={portOptions}
					onOpen={() => void rescanPorts()}
					onChange={(port) => {
						setSelectedPort(port);
						// Switching target invalidates the current preview so it reloads.
						setTargetUrl(null);
						setError(null);
						autoLoadedRef.current = false;
					}}
					className="rounded border border-gray-800 bg-[#111827] px-2 py-1.5 font-mono text-xs text-gray-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
				/>
				<input
					type="text"
					value={path}
					onChange={(event) => setPath(event.target.value)}
					onKeyDown={(event) => {
						if (event.key === "Enter") {
							event.preventDefault();
							void go();
						}
					}}
					placeholder="/"
					className="flex-1 rounded border border-gray-800 bg-[#111827] px-2.5 py-1.5 font-mono text-xs text-gray-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
				/>
				<button
					type="button"
					onClick={() => void go()}
					disabled={loading || !selectedPort}
					className="rounded bg-indigo-600 px-2.5 py-1.5 text-xs font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
				>
					{loading ? (
						<span className="block h-3.5 w-3.5 animate-spin rounded-full border border-white/70 border-t-transparent" />
					) : (
						"Go"
					)}
				</button>
				<button
					type="button"
					onClick={() => {
						void rescanPorts();
						void go(path);
					}}
					disabled={loading || !selectedPort}
					title="Refresh (re-scan ports + reload)"
					aria-label="Refresh preview"
					className="rounded border border-gray-800 p-1.5 text-gray-400 transition hover:border-indigo-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
				>
					<RefreshDouble className="h-4 w-4" />
				</button>
				<button
					type="button"
					onClick={popOut}
					disabled={!targetUrl}
					title="Pop out"
					aria-label="Pop out preview"
					className="rounded border border-gray-800 p-1.5 text-gray-400 transition hover:border-indigo-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
				>
					<OpenNewWindow className="h-4 w-4" />
				</button>
			</div>

			{error ? (
				<div className="border-b border-gray-800 bg-rose-950/20 px-3 py-2 text-xs text-rose-300">
					{error}
				</div>
			) : !selectedPort ? (
				<div className="border-b border-gray-800 px-3 py-2 text-xs text-amber-400">
					{portOptions.length > 0
						? "Select a port to enable preview."
						: "No listening ports detected — run your app."}
				</div>
			) : null}

			<iframe
				title="Container preview"
				src={targetUrl ?? "about:blank"}
				className="w-full flex-1 bg-white"
			/>
		</div>
	);
};

export default BrowserPage;
