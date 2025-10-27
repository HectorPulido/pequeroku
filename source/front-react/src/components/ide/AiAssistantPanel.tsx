import { RefreshDouble, Xmark } from "iconoir-react";
import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { alertStore } from "@/lib/alertStore";

type Role = "user" | "assistant";
type ConnectionState = "idle" | "connecting" | "connected" | "error";

type ChatMessage = {
	id: string;
	role: Role;
	content: string;
};

interface AiAssistantPanelProps {
	isOpen: boolean;
	onClose: () => void;
	containerId: string;
}

const cleanBuffer = (buffer: string) => {
	if (/^\.{3}(?!$)/.test(buffer)) {
		return buffer.replace(/^\.{3}/, "").trimStart();
	}
	return buffer;
};

const AiAssistantPanel: React.FC<AiAssistantPanelProps> = ({ isOpen, onClose, containerId }) => {
	const [messages, setMessages] = useState<ChatMessage[]>([]);
	const messagesRef = useRef<ChatMessage[]>([]);
	const [input, setInput] = useState("");
	const [connectionState, setConnectionState] = useState<ConnectionState>("idle");
	const [usesLeft, setUsesLeft] = useState<number | null>(null);
	const [isSending, setIsSending] = useState(false);

	const wsRef = useRef<WebSocket | null>(null);
	const streamingRef = useRef<{ id: string; role: Role; buffer: string } | null>(null);
	const scrollerRef = useRef<HTMLDivElement | null>(null);
	const textareaRef = useRef<HTMLTextAreaElement | null>(null);
	const greetedRef = useRef(false);

	const appendMessage = useCallback((message: ChatMessage) => {
		setMessages((prev) => {
			const next = [...prev, message];
			messagesRef.current = next;
			return next;
		});
	}, []);

	const updateMessage = useCallback((id: string, content: string) => {
		setMessages((prev) => {
			const next = prev.map((message) => (message.id === id ? { ...message, content } : message));
			messagesRef.current = next;
			return next;
		});
	}, []);

	const resetConversation = useCallback(() => {
		setMessages([]);
		messagesRef.current = [];
		streamingRef.current = null;
		setUsesLeft(null);
	}, []);

	const handleServerMessage = useCallback(
		(event: MessageEvent<string>) => {
			try {
				const payload = JSON.parse(event.data) as Record<string, unknown>;
				const eventType = typeof payload.event === "string" ? payload.event : "";
				if (eventType === "start_text") {
					const role = payload.role === "user" ? "user" : "assistant";
					if (role === "user") {
						const last = messagesRef.current[messagesRef.current.length - 1];
						if (last?.role === "user") {
							streamingRef.current = { id: last.id, role, buffer: last.content };
							return;
						}
					}
					const id = crypto.randomUUID();
					const placeholder = role === "assistant" ? "..." : "...";
					streamingRef.current = { id, role, buffer: placeholder };
					appendMessage({ id, role, content: placeholder });
					return;
				}
				if (eventType === "text") {
					const chunk = typeof payload.content === "string" ? payload.content : "";
					const active = streamingRef.current;
					if (!active) return;
					const nextBuffer = `${active.buffer}${chunk}`;
					active.buffer = nextBuffer;
					updateMessage(active.id, cleanBuffer(nextBuffer));
					return;
				}
				if (eventType === "finish_text") {
					streamingRef.current = null;
					setIsSending(false);
					return;
				}
				if (eventType === "connected") {
					const raw = payload.ai_uses_left_today;
					if (typeof raw === "number" && Number.isFinite(raw)) {
						setUsesLeft(raw);
					}
					return;
				}
			} catch (error) {
				console.error("AI chat parse error", error);
			}
		},
		[appendMessage, updateMessage],
	);

	const connect = useCallback(() => {
		if (!containerId) return;
		try {
			wsRef.current?.close();
		} catch {}

		const proto = window.location.protocol === "https:" ? "wss" : "ws";
		const url = `${proto}://${window.location.host}/ws/ai/${containerId}/`;

		setConnectionState("connecting");
		const ws = new WebSocket(url);
		wsRef.current = ws;

		ws.onopen = () => {
			setConnectionState("connected");
			if (!greetedRef.current) {
				appendMessage({
					id: crypto.randomUUID(),
					role: "assistant",
					content: "Hello! How can I help you today?",
				});
				greetedRef.current = true;
			}
		};

		ws.onmessage = (event) => {
			handleServerMessage(event);
		};

		ws.onerror = (error) => {
			console.error("AI chat websocket error", error);
			setConnectionState("error");
		};

		ws.onclose = (event) => {
			if (event.wasClean) {
				setConnectionState("idle");
			} else {
				setConnectionState("error");
			}
			wsRef.current = null;
			streamingRef.current = null;
			setIsSending(false);
		};
	}, [appendMessage, containerId, handleServerMessage]);

	const disconnect = useCallback(() => {
		try {
			wsRef.current?.close();
		} catch {}
		wsRef.current = null;
		streamingRef.current = null;
		setConnectionState("idle");
	}, []);

	const handleSend = useCallback(async () => {
		const text = input.trim();
		if (!text) return;
		const ws = wsRef.current;
		if (!ws || ws.readyState !== WebSocket.OPEN) {
			alertStore.push({ message: "AI assistant is disconnected.", variant: "warning" });
			return;
		}
		const id = crypto.randomUUID();
		appendMessage({ id, role: "user", content: text });
		streamingRef.current = { id, role: "user", buffer: text };
		setInput("");
		setIsSending(true);
		try {
			ws.send(JSON.stringify({ text }));
		} catch (error) {
			setIsSending(false);
			alertStore.push({
				message: error instanceof Error ? error.message : "Failed to send message",
				variant: "error",
			});
		}
	}, [appendMessage, input]);

	useEffect(() => {
		if (!isOpen) return;
		if (!wsRef.current) {
			connect();
		}
	}, [connect, isOpen]);

	useEffect(() => {
		resetConversation();
		greetedRef.current = false;
		if (!containerId) {
			return;
		}
		if (wsRef.current) {
			connect();
		}
	}, [connect, containerId, resetConversation]);

	useEffect(() => {
		return () => {
			disconnect();
			resetConversation();
		};
	}, [disconnect, resetConversation]);

	useEffect(() => {
		if (!isOpen) return;
		const el = scrollerRef.current;
		if (!el) return;
		const messageCount = messages.length;
		if (messageCount === 0) {
			el.scrollTop = 0;
			return;
		}
		el.scrollTop = el.scrollHeight;
	}, [isOpen, messages]);

	const canSend = useMemo(
		() => connectionState === "connected" && input.trim().length > 0 && !isSending,
		[connectionState, input, isSending],
	);

	const statusLabel = useMemo(() => {
		switch (connectionState) {
			case "connected":
				return "Connected";
			case "connecting":
				return "Connecting...";
			case "error":
				return "Disconnected";
			default:
				return "Idle";
		}
	}, [connectionState]);

	const autoResizeTextarea = useCallback(() => {
		const el = textareaRef.current;
		if (!el) return;
		el.style.height = "auto";
		const next = Math.min(el.scrollHeight, 240);
		el.style.height = `${Math.max(next, 64)}px`;
	}, []);

	useEffect(() => {
		autoResizeTextarea();
	}, [autoResizeTextarea]);

	return (
		<div
			className={`fixed inset-y-0 right-0 z-40 flex w-full max-w-md transform flex-col border-l border-gray-800 bg-[#0B1220] shadow-2xl transition-transform duration-200 ${
				isOpen ? "translate-x-0" : "translate-x-full"
			}`}
		>
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
						<span>{statusLabel}</span>
						{typeof usesLeft === "number" ? (
							<span className="text-gray-500">· Uses left today: {usesLeft}</span>
						) : null}
					</div>
				</div>
				<div className="flex items-center gap-2">
					{connectionState === "error" ? (
						<button
							type="button"
							className="text-xs uppercase tracking-wide text-indigo-400 hover:text-indigo-200"
							onClick={() => {
								connect();
							}}
						>
							<RefreshDouble className="mr-1 inline-block h-4 w-4" />
							Reconnect
						</button>
					) : null}
					<button
						onClick={onClose}
						className="text-gray-400 transition-colors hover:text-white"
						aria-label="Close AI assistant"
					>
						<Xmark className="h-5 w-5" />
					</button>
				</div>
			</div>

			<div className="flex flex-1 flex-col justify-between px-4 py-4">
				<div
					ref={scrollerRef}
					className="flex-1 overflow-y-auto pr-1 text-sm text-gray-200 scroll-smooth"
				>
					{messages.length === 0 ? (
						<div className="rounded-md border border-indigo-700/50 bg-indigo-900/30 p-3 text-indigo-100">
							Ask about build errors, container status, or how to wire new services. Responses
							stream live once the AI backend replies.
						</div>
					) : (
						<div className="flex flex-col gap-3">
							{messages.map((message) => (
								<div
									key={message.id}
									className={`max-w-[90%] rounded-md border px-3 py-2 text-sm leading-relaxed ${
										message.role === "user"
											? "self-end border-indigo-600 bg-indigo-600/10 text-indigo-100"
											: "self-start border-gray-800 bg-[#111827] text-gray-200"
									}`}
								>
									<div className="mb-1 text-xs uppercase tracking-wide text-gray-500">
										{message.role === "user" ? "You" : "Assistant"}
									</div>
									<div className="whitespace-pre-wrap wrap-break-word text-sm">
										{message.content}
									</div>
								</div>
							))}
						</div>
					)}
				</div>

				<form
					className="mt-4 border-t border-gray-800 pt-4"
					onSubmit={(event) => {
						event.preventDefault();
						if (canSend) {
							void handleSend();
						}
					}}
				>
					<label className="sr-only" htmlFor="ai-assistant-input">
						Message for the AI assistant
					</label>
					<div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:gap-4">
						<textarea
							id="ai-assistant-input"
							rows={3}
							placeholder="Type a message..."
							ref={textareaRef}
							className="min-h-[64px] max-h-64 w-full flex-1 resize-none rounded-md border border-gray-800 bg-[#111827] px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:cursor-not-allowed disabled:opacity-70"
							value={input}
							disabled={connectionState !== "connected"}
							onChange={(event) => {
								setInput(event.target.value);
								requestAnimationFrame(autoResizeTextarea);
							}}
							onKeyDown={(event) => {
								if (event.key === "Enter" && !event.shiftKey) {
									event.preventDefault();
									if (canSend) {
										void handleSend();
									}
								}
							}}
						/>
						<div className="flex flex-row gap-2 sm:flex-col">
							<button
								type="submit"
								className="min-h-[40px] whitespace-nowrap rounded-md bg-indigo-600 px-4 py-2 text-xs uppercase tracking-wide text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-gray-700"
								disabled={!canSend}
							>
								{isSending ? "Sending..." : "Send"}
							</button>
						</div>
					</div>
				</form>
			</div>
		</div>
	);
};

export default AiAssistantPanel;
