import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAiChat } from "./useAiChat";

export type { ConnectionState } from "./useAiChat";

const TITLES_KEY = (containerId: string) => `ai:${containerId}:titles`;

const readTitles = (containerId: string): Record<number, string> => {
	if (typeof window === "undefined") return {};
	try {
		const raw = window.localStorage.getItem(TITLES_KEY(containerId));
		return raw ? (JSON.parse(raw) as Record<number, string>) : {};
	} catch {
		return {};
	}
};

/**
 * UI glue shared by the full AI studio page and the IDE's slide-over assistant.
 * Wraps {@link useAiChat} with the composer input, autoscroll, send/pick and
 * edit-as-fork handlers both surfaces need, so the only thing that differs
 * between them is the surrounding layout/chrome.
 */
export const useAiChatSession = (containerId: string) => {
	const chat = useAiChat(containerId);
	const {
		messages,
		connectionState,
		currentConversation,
		isSending,
		sendMessage,
		forkConversation,
	} = chat;

	const [input, setInput] = useState("");
	// Conversations come from the backend as bare ids; auto-title each one from its
	// first user message and persist locally so the sidebar stays readable.
	const [conversationTitles, setConversationTitles] = useState<Record<number, string>>(() =>
		readTitles(containerId),
	);

	useEffect(() => {
		setConversationTitles(readTitles(containerId));
	}, [containerId]);

	useEffect(() => {
		if (typeof currentConversation !== "number") return;
		if (conversationTitles[currentConversation]) return;
		const firstUser = messages.find((m) => m.role === "user" && m.content.trim().length > 0);
		if (firstUser?.role !== "user") return;
		const title = firstUser.content.trim().replace(/\s+/g, " ").slice(0, 48);
		setConversationTitles((prev) => {
			if (prev[currentConversation]) return prev;
			const next = { ...prev, [currentConversation]: title };
			try {
				window.localStorage.setItem(TITLES_KEY(containerId), JSON.stringify(next));
			} catch {
				/* ignore */
			}
			return next;
		});
	}, [messages, currentConversation, conversationTitles, containerId]);
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
		conversationTitles,
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
