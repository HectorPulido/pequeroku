import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAiChat } from "./useAiChat";

export type { ConnectionState } from "./useAiChat";

/**
 * UI glue shared by the full AI studio page and the IDE's slide-over assistant.
 * Wraps {@link useAiChat} with the composer input, autoscroll, send/pick and
 * edit-as-fork handlers both surfaces need, so the only thing that differs
 * between them is the surrounding layout/chrome.
 */
export const useAiChatSession = (containerId: string) => {
	const chat = useAiChat(containerId);
	const { messages, connectionState, isSending, sendMessage, forkConversation } = chat;

	const [input, setInput] = useState("");
	// Bumped after a fork pre-fills the composer, to refocus + caret-to-end.
	const [composerFocus, setComposerFocus] = useState(0);
	const scrollerRef = useRef<HTMLDivElement | null>(null);

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

	const canSend = useMemo(
		() => connectionState === "connected" && input.trim().length > 0 && !isSending,
		[connectionState, input, isSending],
	);

	const lastMessage = messages[messages.length - 1];
	const showStandaloneThinking = isSending && (!lastMessage || lastMessage.role === "user");

	return {
		...chat,
		input,
		setInput,
		composerFocus,
		scrollerRef,
		handleSend,
		handlePick,
		handleEditMessage,
		canSend,
		showStandaloneThinking,
	};
};
