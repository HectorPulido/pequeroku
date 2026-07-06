import type React from "react";
import { useEffect, useState } from "react";
import ResizablePanel from "@/components/ide/ResizablePanel";
import { buildBrowserSrc, isBrowserDockMessage } from "@/lib/browserDock";

interface BrowserDockProps {
	containerId: string;
	/** Whether the dock is open. When false nothing is rendered. */
	open: boolean;
	/** Called when the embedded browser asks to close (its X button). */
	onClose: () => void;
	/** Preferred port hint forwarded to the browser page (config.json still wins). */
	port?: number | null;
	/** localStorage key for the resizable panel width. */
	storageKey: string;
	/**
	 * Bump to force the embedded browser to reload (e.g. after "Run"). Remounting
	 * the iframe re-runs port detection and re-polls the freshly started app.
	 */
	reloadKey?: number;
	defaultWidth?: number;
	minWidth?: number;
	maxWidth?: number;
}

/**
 * Host wrapper for the standalone `/browser` page. Both the IDE and the AI studio
 * embed it identically: a right-side resizable panel by default, or a fullscreen
 * overlay when the user hits expand inside the browser. The browser lives in an
 * iframe and drives this chrome (close / expand) through `postMessage`.
 */
const BrowserDock: React.FC<BrowserDockProps> = ({
	containerId,
	open,
	onClose,
	port,
	storageKey,
	reloadKey = 0,
	defaultWidth = 420,
	minWidth = 280,
	maxWidth = 760,
}) => {
	const [expanded, setExpanded] = useState(false);

	// A freshly opened dock always starts docked, never fullscreen.
	useEffect(() => {
		if (!open) setExpanded(false);
	}, [open]);

	useEffect(() => {
		const onMessage = (event: MessageEvent) => {
			if (event.origin !== window.location.origin) return;
			if (!isBrowserDockMessage(event.data)) return;
			if (event.data.type === "close") {
				onClose();
			} else if (event.data.type === "expand") {
				setExpanded(event.data.expanded);
			}
		};
		window.addEventListener("message", onMessage);
		return () => window.removeEventListener("message", onMessage);
	}, [onClose]);

	if (!open) return null;

	const frame = (
		<iframe
			key={reloadKey}
			title="Preview browser"
			src={buildBrowserSrc(containerId, { port })}
			className="h-full w-full border-0 bg-[#0B1220]"
		/>
	);

	if (expanded) {
		return <div className="fixed inset-0 z-40 bg-[#0B1220]">{frame}</div>;
	}

	return (
		<ResizablePanel
			side="right"
			storageKey={storageKey}
			defaultWidth={defaultWidth}
			minWidth={minWidth}
			maxWidth={maxWidth}
			isCollapsed={false}
		>
			<div className="h-full w-full">{frame}</div>
		</ResizablePanel>
	);
};

export default BrowserDock;
