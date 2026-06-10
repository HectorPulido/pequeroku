import { EditPencil, Sparks, WarningTriangle } from "iconoir-react";
import type React from "react";
import type { AssistantPart, ChatMessage as ChatMessageType, ToolPart } from "@/hooks/useAiChat";
import CopyButton from "./CopyButton";
import Markdown from "./Markdown";
import ToolGroup from "./ToolGroup";

interface ChatMessageProps {
	message: ChatMessageType;
	streaming?: boolean;
	// Branch the conversation at this (user) message: keep everything before it in
	// a fresh conversation and pre-fill the composer with its text. Only wired for
	// user messages.
	onEdit?: () => void;
}

type RenderNode =
	| { kind: "part"; part: Exclude<AssistantPart, ToolPart> }
	| { kind: "tools"; id: string; tools: ToolPart[] };

// Collapse consecutive tool parts into a single group so every tool call in a
// turn renders inside one dropdown instead of one card each.
const toRenderNodes = (parts: AssistantPart[]): RenderNode[] => {
	const nodes: RenderNode[] = [];
	let bucket: ToolPart[] = [];
	const flush = () => {
		if (bucket.length > 0) {
			nodes.push({ kind: "tools", id: `tools:${bucket[0].id}`, tools: bucket });
			bucket = [];
		}
	};
	for (const part of parts) {
		if (part.kind === "tool") {
			bucket.push(part);
			continue;
		}
		flush();
		nodes.push({ kind: "part", part });
	}
	flush();
	return nodes;
};

const TypingDots: React.FC = () => (
	<span
		className="inline-flex items-center gap-1 py-1"
		role="status"
		aria-label="Assistant is typing"
	>
		<span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-500 [animation-delay:-0.2s]" />
		<span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-500 [animation-delay:-0.1s]" />
		<span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-500" />
	</span>
);

const ChatMessage: React.FC<ChatMessageProps> = ({ message, streaming = false, onEdit }) => {
	if (message.role === "user") {
		const hasContent = message.content.trim().length > 0;
		return (
			<div className="group flex flex-col items-end gap-0.5">
				<span className="px-1 text-xs uppercase tracking-wide text-gray-500">You</span>
				<div className="max-w-[85%] whitespace-pre-wrap wrap-break-word rounded-2xl rounded-tr-sm bg-indigo-600/15 px-4 py-2.5 text-sm text-indigo-50">
					{message.content}
				</div>
				{hasContent ? (
					<div className="flex items-center gap-0.5 opacity-0 transition group-hover:opacity-100 focus-within:opacity-100">
						{onEdit ? (
							<button
								type="button"
								onClick={onEdit}
								title="Edit in a new branch"
								aria-label="Edit message in a new branch"
								className="inline-flex items-center rounded p-1 text-gray-500 transition hover:text-gray-200"
							>
								<EditPencil className="h-3.5 w-3.5" />
							</button>
						) : null}
						<CopyButton text={message.content} />
					</div>
				) : null}
			</div>
		);
	}

	const hasRenderable = message.parts.length > 0;
	// Plain-text answer used by the copy button — tool/todo/notice parts are
	// internal trace and excluded so the clipboard holds only the reply prose.
	const copyText = message.parts
		.map((part) => (part.kind === "text" ? part.content : ""))
		.filter(Boolean)
		.join("\n\n")
		.trim();

	return (
		<div className="flex flex-col gap-1">
			<div className="flex items-center gap-2 px-1">
				<span className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-500/20 text-indigo-300">
					<Sparks className="h-3 w-3" />
				</span>
				<span className="text-xs font-semibold uppercase tracking-wide text-gray-400">AI</span>
			</div>
			<div className="flex flex-col gap-1 pl-7 text-sm text-gray-200">
				{toRenderNodes(message.parts).map((node) => {
					if (node.kind === "tools") {
						return <ToolGroup key={node.id} tools={node.tools} />;
					}
					const part = node.part;
					switch (part.kind) {
						case "text":
							return <Markdown key={part.id}>{part.content}</Markdown>;
						case "todos":
							return (
								<ul key={part.id} className="my-1 space-y-1">
									{part.todos.map((todo) => (
										<li
											key={`${part.id}:${todo.content}`}
											className="flex items-center gap-2 text-xs text-gray-300"
										>
											<span
												className={`inline-block h-3.5 w-3.5 shrink-0 rounded border ${
													todo.status === "completed" || todo.status === "done"
														? "border-emerald-500 bg-emerald-500/30"
														: todo.status === "in_progress"
															? "border-indigo-400 bg-indigo-400/20"
															: "border-gray-600"
												}`}
											/>
											<span
												className={
													todo.status === "completed" || todo.status === "done"
														? "line-through opacity-70"
														: ""
												}
											>
												{todo.content}
											</span>
										</li>
									))}
								</ul>
							);
						case "subagent":
							return (
								<div key={part.id} className="my-1 text-xs text-gray-400">
									<span className="font-mono text-indigo-300">↳ {part.agentType}</span> subagent{" "}
									{part.status === "finished" ? "finished" : "running…"}
								</div>
							);
						case "info":
							return (
								<div key={part.id} className="my-1 text-xs text-gray-500">
									{part.message}
								</div>
							);
						case "error":
							return (
								<div
									key={part.id}
									className="my-1 flex items-start gap-2 rounded-md border border-rose-800/60 bg-rose-950/30 px-3 py-2 text-xs text-rose-200"
								>
									<WarningTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
									<span className="whitespace-pre-wrap">{part.message}</span>
								</div>
							);
						default:
							return null;
					}
				})}
				{streaming ? <TypingDots /> : null}
				{!hasRenderable && !streaming ? <span className="text-gray-600">…</span> : null}
				{!streaming && copyText ? (
					<div className="mt-0.5 flex">
						<CopyButton text={copyText} label="Copy answer" />
					</div>
				) : null}
			</div>
		</div>
	);
};

export default ChatMessage;
