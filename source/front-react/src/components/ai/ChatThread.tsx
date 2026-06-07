import type React from "react";
import type { ChatMessage as ChatMessageType } from "@/hooks/useAiChat";
import ChatMessage from "./ChatMessage";
import WelcomeScreen from "./WelcomeScreen";

interface ChatThreadProps {
	messages: ChatMessageType[];
	isSending: boolean;
	// A lone "thinking" bubble shown while the turn hasn't produced an assistant
	// message yet (i.e. the last message is still the user's).
	showStandaloneThinking: boolean;
	onPick: (prompt: string) => void;
	onEditMessage: (messageId: string, content: string, memoryIndex: number | undefined) => void;
	scrollerRef: React.RefObject<HTMLDivElement | null>;
}

/**
 * The scrolling conversation timeline shared by the AI studio page and the IDE
 * assistant panel: an empty-state welcome, the streamed message list, and a
 * trailing thinking indicator. Chrome around it (panels, composer) lives in the
 * caller.
 */
const ChatThread: React.FC<ChatThreadProps> = ({
	messages,
	isSending,
	showStandaloneThinking,
	onPick,
	onEditMessage,
	scrollerRef,
}) => (
	<div ref={scrollerRef} className="flex-1 overflow-y-auto">
		{messages.length === 0 ? (
			<WelcomeScreen onPick={onPick} />
		) : (
			<div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6">
				{messages.map((message, index) => (
					<ChatMessage
						key={message.id}
						message={message}
						streaming={isSending && index === messages.length - 1 && message.role === "assistant"}
						onEdit={
							message.role === "user"
								? () => onEditMessage(message.id, message.content, message.memoryIndex)
								: undefined
						}
					/>
				))}
				{showStandaloneThinking ? (
					<ChatMessage message={{ id: "thinking", role: "assistant", parts: [] }} streaming />
				) : null}
			</div>
		)}
	</div>
);

export default ChatThread;
