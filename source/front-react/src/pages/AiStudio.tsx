import { Code, Globe, MultiBubble, NavArrowLeft, NavArrowRight } from "iconoir-react";
import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import ChatComposer from "@/components/ai/ChatComposer";
import ChatThread from "@/components/ai/ChatThread";
import CommandsPanel from "@/components/ai/CommandsPanel";
import Header from "@/components/Header";
import ResizablePanel from "@/components/ide/ResizablePanel";
import BrowserDock from "@/components/preview/BrowserDock";
import { useAiChatSession } from "@/hooks/useAiChatSession";
import { fetchListeningPorts } from "@/services/ide/actions";

const MissingContainer: React.FC<{ showHeader: boolean }> = ({ showHeader }) => (
	<div className="min-h-screen bg-[#0B1220] text-gray-200">
		{showHeader ? <Header /> : null}
		<div className="flex min-h-[60vh] items-center justify-center px-6">
			<div className="max-w-md rounded-xl border border-gray-800 bg-[#111827] p-6 text-sm shadow-lg shadow-indigo-900/10">
				<h1 className="mb-3 text-lg font-semibold text-white">Container unavailable</h1>
				<p className="text-gray-300">
					The AI studio requires a valid <code>containerId</code> query parameter. Launch it from
					the dashboard or append <code>?containerId=&lt;id&gt;</code> to the URL and reload the
					page.
				</p>
			</div>
		</div>
	</div>
);

const readPanelState = (key: string, fallback: boolean): boolean => {
	if (typeof window === "undefined") return fallback;
	const stored = window.localStorage.getItem(key);
	if (stored === "open") return true;
	if (stored === "collapsed") return false;
	return fallback;
};

interface RailProps {
	side: "left" | "right";
	label: string;
	icon: React.ReactNode;
	onExpand: () => void;
	pulse?: boolean;
}

const CollapsedRail: React.FC<RailProps> = ({ side, label, icon, onExpand, pulse = false }) => (
	<div
		className={`flex h-full w-11 shrink-0 flex-col items-center gap-3 bg-[#0B1220] py-3 ${
			side === "left" ? "border-r border-gray-800" : "border-l border-gray-800"
		}`}
	>
		<button
			type="button"
			onClick={onExpand}
			title={pulse ? `${label} — app detected, click to preview` : `Expand ${label}`}
			aria-label={`Expand ${label}`}
			className={`relative rounded border p-1 transition hover:border-indigo-500 hover:text-white ${
				pulse ? "border-emerald-500/60 text-emerald-300" : "border-gray-800 text-gray-400"
			}`}
		>
			{side === "left" ? (
				<NavArrowRight className="h-4 w-4" />
			) : (
				<NavArrowLeft className="h-4 w-4" />
			)}
			{pulse ? (
				<span className="absolute -right-1 -top-1 h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
			) : null}
		</button>
		<div className="flex flex-col items-center gap-2 text-gray-500">
			{icon}
			<span className="[writing-mode:vertical-rl] text-[11px] uppercase tracking-wide">
				{label}
			</span>
		</div>
	</div>
);

const AiStudioLayout: React.FC<{ containerId: string; showHeader: boolean }> = ({
	containerId,
	showHeader,
}) => {
	const {
		messages,
		connectionState,
		usesLeft,
		conversationTitles,
		isSending,
		conversations,
		currentConversation,
		newConversation,
		switchConversation,
		deleteConversation,
		reconnect,
		input,
		setInput,
		composerFocus,
		scrollerRef,
		handleSend,
		handlePick,
		handleEditMessage,
		canSend,
		showStandaloneThinking,
	} = useAiChatSession(containerId);
	const [leftOpen, setLeftOpen] = useState(() => readPanelState(`ai:${containerId}:left`, true));
	// Browser starts hidden by default; the user expands it via the right rail.
	const [rightOpen, setRightOpen] = useState(() =>
		readPanelState(`ai:${containerId}:right`, false),
	);
	// Auto-open the browser the first time an app starts listening — but only for
	// users who have not expressed a panel preference yet (no saved state), and
	// never after they toggle it manually this session.
	const [hasDetectedPorts, setHasDetectedPorts] = useState(false);
	const allowAutoOpenRef = useRef(
		typeof window === "undefined" ||
			window.localStorage.getItem(`ai:${containerId}:right`) === null,
	);
	const navigate = useNavigate();

	// Mirror of the IDE's "Open AI studio" button, going the other way. Preserve
	// the embedded mode (showHeader=false) so the chrome stays hidden in the IDE.
	const openIde = useCallback(() => {
		const suffix = showHeader ? "" : "&showHeader=1";
		navigate(`/ide?containerId=${containerId}${suffix}`);
	}, [containerId, navigate, showHeader]);

	const persistPanel = useCallback((key: string, open: boolean) => {
		if (typeof window === "undefined") return;
		window.localStorage.setItem(key, open ? "open" : "collapsed");
	}, []);

	const toggleLeft = useCallback(
		(open: boolean) => {
			setLeftOpen(open);
			persistPanel(`ai:${containerId}:left`, open);
		},
		[containerId, persistPanel],
	);
	const toggleRight = useCallback(
		(open: boolean) => {
			// A manual toggle is an explicit preference: stop auto-opening from now on.
			allowAutoOpenRef.current = false;
			setRightOpen(open);
			persistPanel(`ai:${containerId}:right`, open);
		},
		[containerId, persistPanel],
	);

	// Poll for listening ports only while the browser is collapsed (to pulse the
	// Browser button when an app appears); once open, the embedded browser owns
	// detection. Gated on a live chat connection as a cheap "container reachable"
	// signal.
	useEffect(() => {
		if (rightOpen || connectionState !== "connected") return;
		let cancelled = false;
		const scan = async () => {
			try {
				const ports = await fetchListeningPorts(containerId);
				if (!cancelled && ports.length > 0) setHasDetectedPorts(true);
			} catch {
				/* ignore: container may not be ready yet */
			}
		};
		void scan();
		const timer = window.setInterval(scan, 10_000);
		return () => {
			cancelled = true;
			window.clearInterval(timer);
		};
	}, [rightOpen, connectionState, containerId]);

	useEffect(() => {
		if (hasDetectedPorts && !rightOpen && allowAutoOpenRef.current) {
			allowAutoOpenRef.current = false;
			toggleRight(true);
		}
	}, [hasDetectedPorts, rightOpen, toggleRight]);

	return (
		<div className="flex h-screen flex-col bg-[#0B1220] text-gray-200">
			{showHeader ? <Header /> : null}

			<div className="flex flex-1 overflow-hidden">
				{leftOpen ? (
					<ResizablePanel
						side="left"
						storageKey={`ai:${containerId}:left:px`}
						defaultWidth={260}
						minWidth={220}
						maxWidth={420}
						isCollapsed={false}
					>
						<CommandsPanel
							onNewChat={newConversation}
							onCollapse={() => toggleLeft(false)}
							onReconnect={reconnect}
							onSwitchConversation={switchConversation}
							onDeleteConversation={deleteConversation}
							conversations={conversations}
							currentConversation={currentConversation}
							connectionState={connectionState}
							usesLeft={usesLeft}
							titles={conversationTitles}
						/>
					</ResizablePanel>
				) : (
					<CollapsedRail
						side="left"
						label="Chat"
						icon={<MultiBubble className="h-4 w-4" />}
						onExpand={() => toggleLeft(true)}
					/>
				)}

				<div className="flex min-w-0 flex-1 flex-col overflow-hidden">
					<div className="flex items-center justify-end gap-2 border-b border-gray-800 px-4 py-2">
						<button
							type="button"
							className={`relative inline-flex items-center gap-1 md:gap-2 rounded border px-3 py-1.5 text-xs transition hover:border-indigo-500 hover:text-white ${
								rightOpen
									? "border-indigo-500 text-white"
									: hasDetectedPorts
										? "border-emerald-500/60 text-emerald-300"
										: "border-gray-700 text-gray-200"
							}`}
							onClick={() => toggleRight(!rightOpen)}
							aria-label="Toggle browser"
							title={
								!rightOpen && hasDetectedPorts
									? "Browser — app detected, click to preview"
									: "Toggle embedded browser"
							}
						>
							<Globe className="h-4 w-4" />
							<span className="hidden md:inline">Browser</span>
							{!rightOpen && hasDetectedPorts ? (
								<span className="absolute -right-1 -top-1 h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
							) : null}
						</button>
						<button
							type="button"
							className="inline-flex items-center gap-1 md:gap-2 rounded border border-gray-700 px-3 py-1.5 text-xs text-gray-200 transition hover:border-indigo-500 hover:text-white"
							onClick={openIde}
							aria-label="Open IDE"
							title="Open IDE"
						>
							<Code className="h-4 w-4" />
							<span className="hidden md:inline">IDE</span>
						</button>
					</div>
					<ChatThread
						messages={messages}
						isSending={isSending}
						showStandaloneThinking={showStandaloneThinking}
						onPick={handlePick}
						onEditMessage={handleEditMessage}
						scrollerRef={scrollerRef}
					/>

					<div className="border-t border-gray-800 bg-[#0B1220] px-4 py-3">
						<div className="mx-auto max-w-3xl">
							<ChatComposer
								value={input}
								onChange={setInput}
								onSubmit={handleSend}
								disabled={connectionState !== "connected"}
								canSend={canSend}
								focusSignal={composerFocus}
							/>
						</div>
					</div>
				</div>

				<BrowserDock
					containerId={containerId}
					open={rightOpen}
					onClose={() => toggleRight(false)}
					storageKey={`ai:${containerId}:right:px`}
				/>
			</div>
		</div>
	);
};

const AiStudio: React.FC = () => {
	const [searchParams] = useSearchParams();
	const rawId = (searchParams.get("containerId") ?? "").trim();
	const shouldShowHeader = !searchParams.has("showHeader");

	if (!rawId) {
		return <MissingContainer showHeader={shouldShowHeader} />;
	}

	return <AiStudioLayout containerId={rawId} showHeader={shouldShowHeader} />;
};

export default AiStudio;
