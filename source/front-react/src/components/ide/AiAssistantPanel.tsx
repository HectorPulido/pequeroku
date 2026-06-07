import { Expand, PlusCircle, RefreshDouble, Xmark } from "iconoir-react";
import type React from "react";
import { useRef } from "react";
import ChatComposer from "@/components/ai/ChatComposer";
import ChatThread from "@/components/ai/ChatThread";
import { type ConnectionState, useAiChatSession } from "@/hooks/useAiChatSession";

const STATUS_LABEL: Record<ConnectionState, string> = {
	connected: "Connected",
	connecting: "Connecting...",
	error: "Disconnected",
	idle: "Idle",
};

interface AiAssistantPanelProps {
	isOpen: boolean;
	onClose: () => void;
	containerId: string;
	// Optional "pop out" to the full-page AI studio (same conversation/container).
	onOpenStudio?: () => void;
}

// Inner body, mounted only once the panel has been opened. It owns the chat
// transport via the shared useAiChatSession hook, so it renders the exact same
// markdown / tool / todo / conversation timeline and slash-command composer as
// the full AI studio page — only the surrounding chrome differs.
const AiAssistantBody: React.FC<{
	containerId: string;
	onClose: () => void;
	onOpenStudio?: () => void;
}> = ({ containerId, onClose, onOpenStudio }) => {
	const {
		messages,
		connectionState,
		usesLeft,
		isSending,
		newConversation,
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

	return (
		<>
			<div className="flex items-center justify-between border-b border-gray-800 px-4 py-3">
				<div>
					<h3 className="text-base font-semibold text-white">AI Assistant</h3>
					<div className="flex items-center gap-2 text-xs text-gray-400">
						<span
							className={`inline-block h-2 w-2 rounded-full ${
								connectionState === "connected"
									? "bg-emerald-400"
									: connectionState === "error"
										? "bg-rose-500"
										: "bg-amber-400"
							}`}
						/>
						<span>{STATUS_LABEL[connectionState]}</span>
						{typeof usesLeft === "number" ? (
							<span className="text-gray-500">· Uses left today: {usesLeft}</span>
						) : null}
					</div>
				</div>
				<div className="flex items-center gap-1">
					{connectionState === "error" ? (
						<button
							type="button"
							className="rounded p-1 text-indigo-400 transition-colors hover:text-indigo-200"
							onClick={reconnect}
							title="Reconnect"
							aria-label="Reconnect AI assistant"
						>
							<RefreshDouble className="h-5 w-5" />
						</button>
					) : null}
					<button
						type="button"
						className="rounded p-1 text-gray-400 transition-colors hover:text-white"
						onClick={newConversation}
						title="New chat"
						aria-label="Start a new chat"
					>
						<PlusCircle className="h-5 w-5" />
					</button>
					{onOpenStudio ? (
						<button
							type="button"
							className="rounded p-1 text-gray-400 transition-colors hover:text-white"
							onClick={onOpenStudio}
							title="Open in AI studio"
							aria-label="Open in AI studio"
						>
							<Expand className="h-5 w-5" />
						</button>
					) : null}
					<button
						type="button"
						onClick={onClose}
						className="rounded p-1 text-gray-400 transition-colors hover:text-white"
						aria-label="Close AI assistant"
					>
						<Xmark className="h-5 w-5" />
					</button>
				</div>
			</div>

			<ChatThread
				messages={messages}
				isSending={isSending}
				showStandaloneThinking={showStandaloneThinking}
				onPick={handlePick}
				onEditMessage={handleEditMessage}
				scrollerRef={scrollerRef}
			/>

			<div className="border-t border-gray-800 bg-[#0B1220] px-3 py-3">
				<ChatComposer
					value={input}
					onChange={setInput}
					onSubmit={handleSend}
					disabled={connectionState !== "connected"}
					canSend={canSend}
					focusSignal={composerFocus}
				/>
			</div>
		</>
	);
};

const AiAssistantPanel: React.FC<AiAssistantPanelProps> = ({
	isOpen,
	onClose,
	containerId,
	onOpenStudio,
}) => {
	// Mount the body — and therefore open the WebSocket — only after the first
	// time the panel is opened, then keep it mounted so the connection persists
	// across open/close. Opening flips the `isOpen` prop, which re-renders us, so
	// the latch is read in the same frame the panel slides in (no empty flash).
	const everOpenedRef = useRef(false);
	if (isOpen) everOpenedRef.current = true;

	return (
		<div
			className={`fixed inset-y-0 right-0 z-40 flex w-full max-w-md transform flex-col border-l border-gray-800 bg-[#0B1220] shadow-2xl transition-transform duration-200 ${
				isOpen ? "translate-x-0" : "translate-x-full"
			}`}
		>
			{everOpenedRef.current ? (
				<AiAssistantBody containerId={containerId} onClose={onClose} onOpenStudio={onOpenStudio} />
			) : null}
		</div>
	);
};

export default AiAssistantPanel;
