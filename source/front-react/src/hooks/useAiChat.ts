import { useCallback, useEffect, useRef, useState } from "react";
import { alertStore } from "@/lib/alertStore";

export type Role = "user" | "assistant";
export type ConnectionState = "idle" | "connecting" | "connected" | "error";

export type TextPart = { kind: "text"; id: string; content: string };
export type ToolPart = {
	kind: "tool";
	id: string;
	name: string;
	command?: string;
	args?: unknown;
	output?: string;
	status: "running" | "done";
};
export type TodosPart = {
	kind: "todos";
	id: string;
	todos: { content: string; status: string }[];
};
export type SubagentPart = {
	kind: "subagent";
	id: string;
	agentType: string;
	status: "started" | "finished";
	prompt?: string;
};
export type NotePart = { kind: "info" | "error"; id: string; message: string };
export type AssistantPart = TextPart | ToolPart | TodosPart | SubagentPart | NotePart;

export type UserMessage = {
	id: string;
	role: "user";
	content: string;
	// Position of this message in the backend's stored OpenAI memory, supplied by
	// the server (history replay or the `user_index` event). Used to fork the
	// conversation at this exact point — the client never computes it.
	memoryIndex?: number;
};
export type AssistantMessage = { id: string; role: "assistant"; parts: AssistantPart[] };
export type ChatMessage = UserMessage | AssistantMessage;

const genId = (): string => {
	if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
		return crypto.randomUUID();
	}
	return `id-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
};

const asText = (value: unknown): string => {
	if (typeof value === "string") return value;
	try {
		return JSON.stringify(value, null, 2);
	} catch {
		return String(value);
	}
};

// Drop the backend's transient "thinking" placeholders and the redundant
// "Using <tool>..." notices — tool activity is rendered from the structured
// `tool_call`/`tool_result` events instead.
const isDisposableText = (content: string): boolean => {
	const trimmed = content.trim();
	return trimmed === "" || trimmed === "..." || /^Using\s.+\.\.\.$/.test(trimmed);
};

/**
 * Chat transport for the AI studio. Speaks the same `/ws/ai/<pk>/` protocol as
 * {@link AiAssistantPanel} but models each assistant turn as an ordered list of
 * parts (text + tool activity) so the UI can render an OpenWebUI-style timeline.
 */
export const useAiChat = (containerId: string) => {
	const [messages, setMessages] = useState<ChatMessage[]>([]);
	const [connectionState, setConnectionState] = useState<ConnectionState>("idle");
	const [usesLeft, setUsesLeft] = useState<number | null>(null);
	const [isSending, setIsSending] = useState(false);
	const [conversations, setConversations] = useState<number[]>([]);
	const [currentConversation, setCurrentConversation] = useState<number | null>(null);

	const wsRef = useRef<WebSocket | null>(null);
	// Working copy mutated imperatively inside WS handlers; `commit()` publishes a
	// fresh array reference to React. WS events are not double-invoked by
	// StrictMode, so mutating refs here is safe (unlike a setState updater).
	const messagesRef = useRef<ChatMessage[]>([]);
	const currentAssistantIdRef = useRef<string | null>(null);
	const currentTextPartIdRef = useRef<string | null>(null);
	// While true, swallow the one assistant segment that follows a `/clear`
	// (the backend's "Memory clear..." confirmation), keeping the UI empty.
	const swallowClearAckRef = useRef(false);
	// Set right before sending `/clear` so the `clear` event it triggers swallows
	// the confirmation. Conversation switches also emit `clear` (followed by
	// replayed history) but must NOT swallow — hence this per-intent flag.
	const pendingClearAckRef = useRef(false);

	const commit = useCallback(() => {
		setMessages(messagesRef.current.slice());
	}, []);

	const resetStreamRefs = useCallback(() => {
		currentAssistantIdRef.current = null;
		currentTextPartIdRef.current = null;
		swallowClearAckRef.current = false;
		pendingClearAckRef.current = false;
	}, []);

	const getCurrentAssistant = useCallback((): AssistantMessage => {
		const id = currentAssistantIdRef.current;
		if (id) {
			const existing = messagesRef.current.find((m) => m.id === id);
			if (existing && existing.role === "assistant") {
				return existing;
			}
		}
		const created: AssistantMessage = { id: genId(), role: "assistant", parts: [] };
		currentAssistantIdRef.current = created.id;
		currentTextPartIdRef.current = null;
		messagesRef.current.push(created);
		return created;
	}, []);

	const finalizeTextPart = useCallback(() => {
		const partId = currentTextPartIdRef.current;
		currentTextPartIdRef.current = null;
		if (!partId) return;
		const assistant = messagesRef.current.find((m) => m.id === currentAssistantIdRef.current);
		if (assistant?.role !== "assistant") return;
		const part = assistant.parts.find((p) => p.id === partId);
		if (part && part.kind === "text" && isDisposableText(part.content)) {
			assistant.parts = assistant.parts.filter((p) => p.id !== partId);
		}
	}, []);

	const handleServerMessage = useCallback(
		(event: MessageEvent<string>) => {
			let payload: Record<string, unknown>;
			try {
				payload = JSON.parse(event.data) as Record<string, unknown>;
			} catch (error) {
				console.error("AI chat parse error", error);
				return;
			}
			const type = typeof payload.event === "string" ? payload.event : "";

			switch (type) {
				case "connected": {
					const raw = payload.ai_uses_left_today;
					if (typeof raw === "number" && Number.isFinite(raw)) {
						setUsesLeft(raw);
					}
					setIsSending(false);
					return;
				}
				case "memory_data": {
					const conv = payload.conversation;
					if (typeof conv === "number" && Number.isFinite(conv)) {
						setCurrentConversation(conv);
					}
					setIsSending(false);
					return;
				}
				case "user_index": {
					// The server reports the memory index of the just-sent user turn
					// (always the latest user bubble). Stash it so a later fork is exact.
					// Metadata only — no commit needed; the state array shares this object.
					const idx = payload.index;
					if (typeof idx !== "number" || !Number.isFinite(idx)) return;
					for (let i = messagesRef.current.length - 1; i >= 0; i--) {
						const m = messagesRef.current[i];
						if (m.role === "user") {
							m.memoryIndex = idx;
							break;
						}
					}
					return;
				}
				case "conversations": {
					const list = Array.isArray(payload.conversations)
						? payload.conversations.filter((n): n is number => typeof n === "number")
						: [];
					setConversations(list);
					if (typeof payload.current === "number") {
						setCurrentConversation(payload.current);
					}
					return;
				}
				case "clear": {
					// `/clear` is followed by a "Memory clear..." notice we swallow;
					// new/switch/delete conversation actions also emit `clear` but are
					// followed by replayed history (or nothing), which must show.
					const swallowAck = pendingClearAckRef.current;
					pendingClearAckRef.current = false;
					messagesRef.current = [];
					currentAssistantIdRef.current = null;
					currentTextPartIdRef.current = null;
					swallowClearAckRef.current = swallowAck;
					setIsSending(false);
					commit();
					return;
				}
				case "start_text": {
					if (swallowClearAckRef.current) return;
					const role = payload.role === "user" ? "user" : "assistant";
					if (role === "user") {
						currentAssistantIdRef.current = null;
						currentTextPartIdRef.current = null;
						const memoryIndex =
							typeof payload.index === "number" && Number.isFinite(payload.index)
								? payload.index
								: undefined;
						messagesRef.current.push({ id: genId(), role: "user", content: "", memoryIndex });
						commit();
						return;
					}
					finalizeTextPart();
					const assistant = getCurrentAssistant();
					const part: TextPart = { kind: "text", id: genId(), content: "" };
					assistant.parts.push(part);
					currentTextPartIdRef.current = part.id;
					commit();
					return;
				}
				case "text": {
					if (swallowClearAckRef.current) return;
					const chunk = typeof payload.content === "string" ? payload.content : "";
					if (!chunk) return;
					// History replay reuses the trailing user bubble created above.
					const last = messagesRef.current[messagesRef.current.length - 1];
					if (
						last &&
						last.role === "user" &&
						last.content === "" &&
						currentAssistantIdRef.current === null
					) {
						last.content += chunk;
						commit();
						return;
					}
					const assistant = getCurrentAssistant();
					let partId = currentTextPartIdRef.current;
					let part = assistant.parts.find((p) => p.id === partId);
					if (part?.kind !== "text") {
						const created: TextPart = { kind: "text", id: genId(), content: "" };
						assistant.parts.push(created);
						partId = created.id;
						currentTextPartIdRef.current = created.id;
						part = created;
					}
					(part as TextPart).content += chunk;
					commit();
					return;
				}
				case "finish_text": {
					if (swallowClearAckRef.current) {
						swallowClearAckRef.current = false;
						return;
					}
					finalizeTextPart();
					commit();
					return;
				}
				case "tool_call": {
					finalizeTextPart();
					const assistant = getCurrentAssistant();
					assistant.parts.push({
						kind: "tool",
						id: genId(),
						name: typeof payload.name === "string" ? payload.name : "tool",
						command: typeof payload.command === "string" ? payload.command : undefined,
						args: payload.args,
						status: "running",
					});
					commit();
					return;
				}
				case "tool_result": {
					const assistant = getCurrentAssistant();
					const name = typeof payload.name === "string" ? payload.name : "tool";
					const output = asText(payload.output);
					const match = [...assistant.parts]
						.reverse()
						.find((p) => p.kind === "tool" && p.name === name && p.status === "running") as
						| ToolPart
						| undefined;
					if (match) {
						match.output = output;
						match.status = "done";
					} else {
						assistant.parts.push({
							kind: "tool",
							id: genId(),
							name,
							output,
							status: "done",
						});
					}
					commit();
					return;
				}
				case "todos": {
					const assistant = getCurrentAssistant();
					const todos = Array.isArray(payload.todos)
						? (payload.todos as { content: string; status: string }[])
						: [];
					const existing = assistant.parts.find((p) => p.kind === "todos") as TodosPart | undefined;
					if (existing) {
						existing.todos = todos;
					} else {
						assistant.parts.push({ kind: "todos", id: genId(), todos });
					}
					commit();
					return;
				}
				case "subagent_started": {
					const assistant = getCurrentAssistant();
					assistant.parts.push({
						kind: "subagent",
						id: genId(),
						agentType: typeof payload.agent_type === "string" ? payload.agent_type : "agent",
						status: "started",
						prompt: typeof payload.prompt === "string" ? payload.prompt : undefined,
					});
					commit();
					return;
				}
				case "subagent_finished": {
					const assistant = getCurrentAssistant();
					const agentType = typeof payload.agent_type === "string" ? payload.agent_type : "agent";
					const match = [...assistant.parts]
						.reverse()
						.find(
							(p) => p.kind === "subagent" && p.agentType === agentType && p.status === "started",
						) as SubagentPart | undefined;
					if (match) {
						match.status = "finished";
					} else {
						assistant.parts.push({
							kind: "subagent",
							id: genId(),
							agentType,
							status: "finished",
						});
					}
					commit();
					return;
				}
				case "info":
				case "error": {
					const message = typeof payload.message === "string" ? payload.message : "";
					if (!message) return;
					const assistant = getCurrentAssistant();
					assistant.parts.push({ kind: type, id: genId(), message });
					commit();
					return;
				}
				default:
					// `usage` and any unknown event types are ignored for rendering.
					return;
			}
		},
		[commit, finalizeTextPart, getCurrentAssistant],
	);

	const connect = useCallback(() => {
		if (!containerId) return;
		try {
			wsRef.current?.close();
		} catch {
			/* ignore */
		}
		const proto = window.location.protocol === "https:" ? "wss" : "ws";
		const url = `${proto}://${window.location.host}/ws/ai/${containerId}/`;
		setConnectionState("connecting");
		const ws = new WebSocket(url);
		wsRef.current = ws;

		ws.onopen = () => {
			setConnectionState("connected");
		};
		ws.onmessage = (event) => {
			handleServerMessage(event);
		};
		ws.onerror = (error) => {
			console.error("AI chat websocket error", error);
			setConnectionState("error");
		};
		ws.onclose = (event) => {
			setConnectionState(event.wasClean ? "idle" : "error");
			wsRef.current = null;
			resetStreamRefs();
			setIsSending(false);
		};
	}, [containerId, handleServerMessage, resetStreamRefs]);

	const sendMessage = useCallback(
		(text: string): boolean => {
			const trimmed = text.trim();
			if (!trimmed) return false;
			const ws = wsRef.current;
			if (!ws || ws.readyState !== WebSocket.OPEN) {
				alertStore.push({ message: "AI assistant is disconnected.", variant: "warning" });
				return false;
			}
			messagesRef.current.push({ id: genId(), role: "user", content: trimmed });
			currentAssistantIdRef.current = null;
			currentTextPartIdRef.current = null;
			commit();
			setIsSending(true);
			// `/clear` is still a valid backend command (empties the active
			// conversation); flag it so its "Memory clear..." ack is swallowed.
			if (trimmed === "/clear") {
				pendingClearAckRef.current = true;
			}
			try {
				ws.send(JSON.stringify({ text: trimmed }));
				return true;
			} catch (error) {
				setIsSending(false);
				alertStore.push({
					message: error instanceof Error ? error.message : "Failed to send message",
					variant: "error",
				});
				return false;
			}
		},
		[commit],
	);

	// Conversation management — fire-and-forget WS actions. The backend replies
	// with `clear` (+ replayed history) and a fresh `conversations` event, which
	// the reducer above turns into UI state. None of these cost AI quota.
	const sendAction = useCallback((action: string, extra?: Record<string, unknown>) => {
		const ws = wsRef.current;
		if (!ws || ws.readyState !== WebSocket.OPEN) {
			alertStore.push({ message: "AI assistant is disconnected.", variant: "warning" });
			return;
		}
		try {
			ws.send(JSON.stringify({ action, ...extra }));
		} catch (error) {
			console.error(`AI chat ${action} error`, error);
		}
	}, []);

	const newConversation = useCallback(() => sendAction("new_conversation"), [sendAction]);
	const switchConversation = useCallback(
		(id: number) => sendAction("switch_conversation", { id }),
		[sendAction],
	);
	const deleteConversation = useCallback(
		(id: number) => sendAction("delete_conversation", { id }),
		[sendAction],
	);
	// Branch the current conversation just before a user message. The backend
	// resolves the fork point from the server-supplied memory `index` when known,
	// otherwise from `userOrdinal` (which user bubble it is), then creates a new
	// conversation with the prior context and switches to it. We always send the
	// ordinal so editing works even for messages rendered before an index arrived.
	const forkConversation = useCallback(
		(opts: { index?: number; userOrdinal: number }) => {
			const payload: Record<string, number> = { user_ordinal: opts.userOrdinal };
			if (typeof opts.index === "number" && Number.isFinite(opts.index)) {
				payload.index = opts.index;
			}
			return sendAction("fork_conversation", payload);
		},
		[sendAction],
	);

	useEffect(() => {
		messagesRef.current = [];
		resetStreamRefs();
		setMessages([]);
		setUsesLeft(null);
		setIsSending(false);
		setConversations([]);
		setCurrentConversation(null);
		connect();
		return () => {
			try {
				wsRef.current?.close();
			} catch {
				/* ignore */
			}
			wsRef.current = null;
		};
	}, [connect, resetStreamRefs]);

	return {
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
		reconnect: connect,
	};
};
