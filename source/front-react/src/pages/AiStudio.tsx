import { Globe, MultiBubble, NavArrowLeft, NavArrowRight } from "iconoir-react";
import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import ChatComposer from "@/components/ai/ChatComposer";
import ChatMessage from "@/components/ai/ChatMessage";
import CommandsPanel from "@/components/ai/CommandsPanel";
import PreviewBrowser from "@/components/ai/PreviewBrowser";
import WelcomeScreen from "@/components/ai/WelcomeScreen";
import Header from "@/components/Header";
import ResizablePanel from "@/components/ide/ResizablePanel";
import { useAiChat } from "@/hooks/useAiChat";

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
}

const CollapsedRail: React.FC<RailProps> = ({ side, label, icon, onExpand }) => (
	<div
		className={`flex h-full w-11 shrink-0 flex-col items-center gap-3 bg-[#0B1220] py-3 ${
			side === "left" ? "border-r border-gray-800" : "border-l border-gray-800"
		}`}
	>
		<button
			type="button"
			onClick={onExpand}
			title={`Expand ${label}`}
			aria-label={`Expand ${label}`}
			className="rounded border border-gray-800 p-1 text-gray-400 transition hover:border-indigo-500 hover:text-white"
		>
			{side === "left" ? (
				<NavArrowRight className="h-4 w-4" />
			) : (
				<NavArrowLeft className="h-4 w-4" />
			)}
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
		isSending,
		conversations,
		currentConversation,
		sendMessage,
		newConversation,
		switchConversation,
		deleteConversation,
		forkConversation,
		reconnect,
	} = useAiChat(containerId);
	const [input, setInput] = useState("");
	const [composerFocus, setComposerFocus] = useState(0);
	const [leftOpen, setLeftOpen] = useState(() => readPanelState(`ai:${containerId}:left`, true));
	// Browser starts hidden by default; the user expands it via the right rail.
	const [rightOpen, setRightOpen] = useState(() =>
		readPanelState(`ai:${containerId}:right`, false),
	);
	const scrollerRef = useRef<HTMLDivElement | null>(null);

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
			setRightOpen(open);
			persistPanel(`ai:${containerId}:right`, open);
		},
		[containerId, persistPanel],
	);

	// biome-ignore lint/correctness/useExhaustiveDependencies: pin the view to the bottom whenever the conversation grows or a turn starts/ends.
	useEffect(() => {
		const el = scrollerRef.current;
		if (!el) return;
		el.scrollTop = el.scrollHeight;
	}, [messages, isSending]);

	const handleSend = useCallback(() => {
		if (sendMessage(input)) {
			setInput("");
		}
	}, [input, sendMessage]);

	const handlePick = useCallback(
		(prompt: string) => {
			sendMessage(prompt);
		},
		[sendMessage],
	);

	// Fork at the edited user message: send its backend memory index when known
	// plus its user-bubble ordinal (always available as a fallback), then drop its
	// text in the composer and focus it to edit and re-send.
	const handleEditMessage = useCallback(
		(messageId: string, content: string, memoryIndex: number | undefined) => {
			let ordinal = -1;
			let found = false;
			for (const message of messages) {
				if (message.role !== "user") continue;
				ordinal += 1;
				if (message.id === messageId) {
					found = true;
					break;
				}
			}
			if (!found) return;
			forkConversation({ index: memoryIndex, userOrdinal: ordinal });
			setInput(content);
			setComposerFocus((n) => n + 1);
		},
		[messages, forkConversation],
	);

	const handleNewChat = useCallback(() => newConversation(), [newConversation]);

	const canSend = useMemo(
		() => connectionState === "connected" && input.trim().length > 0 && !isSending,
		[connectionState, input, isSending],
	);

	const lastMessage = messages[messages.length - 1];
	const showStandaloneThinking = isSending && (!lastMessage || lastMessage.role === "user");

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
							onNewChat={handleNewChat}
							onCollapse={() => toggleLeft(false)}
							onReconnect={reconnect}
							onSwitchConversation={switchConversation}
							onDeleteConversation={deleteConversation}
							conversations={conversations}
							currentConversation={currentConversation}
							connectionState={connectionState}
							usesLeft={usesLeft}
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
					<div ref={scrollerRef} className="flex-1 overflow-y-auto">
						{messages.length === 0 ? (
							<WelcomeScreen onPick={handlePick} />
						) : (
							<div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6">
								{messages.map((message, index) => (
									<ChatMessage
										key={message.id}
										message={message}
										streaming={
											isSending && index === messages.length - 1 && message.role === "assistant"
										}
										onEdit={
											message.role === "user"
												? () => handleEditMessage(message.id, message.content, message.memoryIndex)
												: undefined
										}
									/>
								))}
								{showStandaloneThinking ? (
									<ChatMessage
										message={{ id: "thinking", role: "assistant", parts: [] }}
										streaming
									/>
								) : null}
							</div>
						)}
					</div>

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

				{rightOpen ? (
					<ResizablePanel
						side="right"
						storageKey={`ai:${containerId}:right:px`}
						defaultWidth={420}
						minWidth={280}
						maxWidth={760}
						isCollapsed={false}
					>
						<PreviewBrowser containerId={containerId} onCollapse={() => toggleRight(false)} />
					</ResizablePanel>
				) : (
					<CollapsedRail
						side="right"
						label="Browser"
						icon={<Globe className="h-4 w-4" />}
						onExpand={() => toggleRight(true)}
					/>
				)}
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
