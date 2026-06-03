import { NavArrowRight, OpenNewWindow, RefreshDouble } from "iconoir-react";
import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import PortSelector from "@/components/ide/PortSelector";
import { usePreviewPorts } from "@/hooks/usePreviewPorts";
import { alertStore } from "@/lib/alertStore";
import { fetchRunConfig, pollPreview } from "@/services/ide/actions";

interface PreviewBrowserProps {
	containerId: string;
	onCollapse: () => void;
}

const normalizePath = (raw: string): string => {
	const trimmed = raw.trim();
	if (!trimmed) return "/";
	return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
};

const PreviewBrowser: React.FC<PreviewBrowserProps> = ({ containerId, onCollapse }) => {
	const [configPort, setConfigPort] = useState<number | null>(null);
	const { selectedPort, setSelectedPort, portOptions, rescanPorts } = usePreviewPorts(
		containerId,
		configPort,
	);
	const [path, setPath] = useState("/");
	const [targetUrl, setTargetUrl] = useState<string | null>(null);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const autoLoadedRef = useRef(false);

	useEffect(() => {
		let cancelled = false;
		autoLoadedRef.current = false;
		setConfigPort(null);
		setTargetUrl(null);
		setError(null);
		void fetchRunConfig(containerId)
			.then(({ port }) => {
				if (!cancelled) setConfigPort(port);
			})
			.catch(() => {
				if (!cancelled) setConfigPort(null);
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

	return (
		<div className="flex h-full flex-col bg-[#0B1220]">
			<div className="flex items-center gap-2 border-b border-gray-800 px-3 py-2.5">
				<button
					type="button"
					onClick={onCollapse}
					title="Collapse panel"
					aria-label="Collapse panel"
					className="rounded border border-gray-800 p-1 text-gray-400 transition hover:border-indigo-500 hover:text-white"
				>
					<NavArrowRight className="h-4 w-4" />
				</button>
				<span className="text-sm font-semibold text-white">Browser</span>
				{selectedPort ? (
					<span className="ml-auto text-[11px] text-gray-500">:{selectedPort}</span>
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

export default PreviewBrowser;
