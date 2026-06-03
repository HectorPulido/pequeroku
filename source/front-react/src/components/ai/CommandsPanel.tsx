import { MultiBubble, NavArrowLeft, PlusCircle, RefreshDouble, Trash } from "iconoir-react";
import type React from "react";
import type { ConnectionState } from "@/hooks/useAiChat";

interface CommandsPanelProps {
	onNewChat: () => void;
	onCollapse: () => void;
	onReconnect: () => void;
	onSwitchConversation: (id: number) => void;
	onDeleteConversation: (id: number) => void;
	conversations: number[];
	currentConversation: number | null;
	connectionState: ConnectionState;
	usesLeft: number | null;
}

const STATUS_LABEL: Record<ConnectionState, string> = {
	connected: "Connected",
	connecting: "Connecting...",
	error: "Disconnected",
	idle: "Idle",
};

const CommandsPanel: React.FC<CommandsPanelProps> = ({
	onNewChat,
	onCollapse,
	onReconnect,
	onSwitchConversation,
	onDeleteConversation,
	conversations,
	currentConversation,
	connectionState,
	usesLeft,
}) => (
	<div className="flex h-full flex-col bg-[#0B1220]">
		<div className="flex items-center justify-between border-b border-gray-800 px-3 py-2.5">
			<span className="text-sm font-semibold text-white">Chat</span>
			<button
				type="button"
				onClick={onCollapse}
				title="Collapse panel"
				aria-label="Collapse panel"
				className="rounded border border-gray-800 p-1 text-gray-400 transition hover:border-indigo-500 hover:text-white"
			>
				<NavArrowLeft className="h-4 w-4" />
			</button>
		</div>

		<div className="flex flex-col gap-2 p-3">
			<button
				type="button"
				onClick={onNewChat}
				className="flex items-center gap-2 rounded-lg border border-gray-800 bg-[#111827] px-4 py-2.5 text-sm font-medium text-gray-100 transition hover:border-indigo-600 hover:bg-[#151d2e]"
			>
				<PlusCircle className="h-4 w-4 text-indigo-300" />
				New chat
			</button>
		</div>

		<div className="flex min-h-0 flex-1 flex-col px-3">
			<div className="px-1 pb-1 text-[11px] uppercase tracking-wide text-gray-500">
				Conversations
			</div>
			<div className="-mx-1 flex-1 overflow-y-auto px-1">
				{conversations.length === 0 ? (
					<div className="px-1 py-2 text-xs text-gray-600">No conversations yet.</div>
				) : (
					<ul className="space-y-1">
						{conversations.map((id) => {
							const active = id === currentConversation;
							return (
								<li key={id}>
									<div
										className={`group flex items-center gap-2 rounded-md border px-2.5 py-2 text-sm transition ${
											active
												? "border-indigo-600 bg-indigo-600/10 text-white"
												: "border-transparent text-gray-300 hover:border-gray-800 hover:bg-[#111827]"
										}`}
									>
										<button
											type="button"
											onClick={() => onSwitchConversation(id)}
											className="flex min-w-0 flex-1 items-center gap-2 text-left"
										>
											<MultiBubble
												className={`h-4 w-4 shrink-0 ${active ? "text-indigo-300" : "text-gray-500"}`}
											/>
											<span className="truncate">Chat {id}</span>
										</button>
										<button
											type="button"
											onClick={() => onDeleteConversation(id)}
											title="Delete conversation"
											aria-label={`Delete conversation ${id}`}
											className="shrink-0 rounded p-1 text-gray-500 opacity-0 transition hover:text-rose-400 group-hover:opacity-100"
										>
											<Trash className="h-3.5 w-3.5" />
										</button>
									</div>
								</li>
							);
						})}
					</ul>
				)}
			</div>
		</div>

		<div className="border-t border-gray-800 px-3 py-3 text-xs text-gray-400">
			<div className="flex items-center gap-2">
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
			</div>
			{typeof usesLeft === "number" ? (
				<div className="mt-1 text-gray-500">Uses left today: {usesLeft}</div>
			) : null}
			{connectionState === "error" ? (
				<button
					type="button"
					onClick={onReconnect}
					className="mt-2 inline-flex items-center gap-1 text-indigo-400 transition hover:text-indigo-200"
				>
					<RefreshDouble className="h-3.5 w-3.5" />
					Reconnect
				</button>
			) : null}
		</div>
	</div>
);

export default CommandsPanel;
