import { Send } from "iconoir-react";
import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { type AiSlashCommand, matchSlashCommands } from "./aiSlashCommands";

interface ChatComposerProps {
	value: string;
	onChange: (value: string) => void;
	onSubmit: () => void;
	disabled?: boolean;
	canSend: boolean;
	placeholder?: string;
	// Bumping this number focuses the textarea and places the caret at the end —
	// used after a fork pre-fills the composer with the edited message.
	focusSignal?: number;
}

const ChatComposer: React.FC<ChatComposerProps> = ({
	value,
	onChange,
	onSubmit,
	disabled = false,
	canSend,
	placeholder = "Type a message...",
	focusSignal = 0,
}) => {
	const textareaRef = useRef<HTMLTextAreaElement | null>(null);
	const [activeIndex, setActiveIndex] = useState(0);
	// Set when the user presses Escape; cleared on the next keystroke so the menu
	// reopens as soon as they keep typing the command token.
	const [dismissed, setDismissed] = useState(false);

	const autoResize = useCallback(() => {
		const el = textareaRef.current;
		if (!el) return;
		el.style.height = "auto";
		el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
	}, []);

	// biome-ignore lint/correctness/useExhaustiveDependencies: re-measure on every value change so externally pre-filled text (e.g. a fork) expands the textarea, not just user keystrokes.
	useEffect(() => {
		autoResize();
	}, [autoResize, value]);

	// Focus + move the caret to the end whenever the focus signal changes.
	useEffect(() => {
		if (!focusSignal) return;
		const el = textareaRef.current;
		if (!el) return;
		el.focus();
		const end = el.value.length;
		el.setSelectionRange(end, end);
	}, [focusSignal]);

	// Slash-command autocomplete: matches while the user types a leading "/<token>".
	const matches = useMemo(() => matchSlashCommands(value), [value]);
	const showMenu = !disabled && matches.length > 0 && !dismissed;
	const active = Math.min(activeIndex, matches.length - 1);

	const handleChange = useCallback(
		(next: string) => {
			onChange(next);
			setActiveIndex(0);
			setDismissed(false);
		},
		[onChange],
	);

	// Fill the composer with `/name` and keep focus, leaving the menu open so the
	// now-complete command stays highlighted (the next Enter sends it).
	const acceptCommand = useCallback(
		(command: AiSlashCommand) => {
			onChange(`/${command.name}`);
			setActiveIndex(0);
			setDismissed(false);
			textareaRef.current?.focus();
		},
		[onChange],
	);

	const handleKeyDown = useCallback(
		(event: React.KeyboardEvent<HTMLTextAreaElement>) => {
			if (showMenu) {
				switch (event.key) {
					case "ArrowDown":
						event.preventDefault();
						setActiveIndex((i) => (i + 1) % matches.length);
						return;
					case "ArrowUp":
						event.preventDefault();
						setActiveIndex((i) => (i - 1 + matches.length) % matches.length);
						return;
					case "Escape":
						event.preventDefault();
						setDismissed(true);
						return;
					case "Tab":
						event.preventDefault();
						acceptCommand(matches[active]);
						return;
					case "Enter": {
						if (event.shiftKey) break; // let Shift+Enter insert a newline
						event.preventDefault();
						const command = matches[active];
						// Already typed in full → send it; otherwise complete the token.
						if (value.trim() === `/${command.name}`) {
							setDismissed(true);
							if (canSend) onSubmit();
						} else {
							acceptCommand(command);
						}
						return;
					}
					default:
						break;
				}
			}
			if (event.key === "Enter" && !event.shiftKey) {
				event.preventDefault();
				if (canSend) onSubmit();
			}
		},
		[showMenu, matches, active, value, canSend, onSubmit, acceptCommand],
	);

	return (
		<div className="relative">
			{showMenu ? (
				<ul className="absolute bottom-full left-0 z-20 mb-2 max-h-64 w-full overflow-y-auto rounded-xl border border-gray-800 bg-[#111827] py-1 shadow-lg shadow-black/30">
					<li className="px-3 py-1 text-[11px] uppercase tracking-wide text-gray-600">Commands</li>
					{matches.map((command, index) => (
						<li key={command.name}>
							<button
								type="button"
								// Keep the textarea focused when the item is clicked.
								onMouseDown={(event) => event.preventDefault()}
								onClick={() => acceptCommand(command)}
								className={`flex w-full items-baseline gap-2 px-3 py-2 text-left transition ${
									index === active
										? "bg-indigo-600/15 text-white"
										: "text-gray-300 hover:bg-[#151d2e]"
								}`}
							>
								<span className="font-mono text-sm text-indigo-300">/{command.name}</span>
								<span className="truncate text-xs text-gray-500">{command.description}</span>
							</button>
						</li>
					))}
				</ul>
			) : null}

			<form
				className="flex items-end gap-2 rounded-2xl border border-gray-800 bg-[#111827] px-3 py-2 focus-within:border-indigo-600"
				onSubmit={(event) => {
					event.preventDefault();
					if (canSend) onSubmit();
				}}
			>
				<textarea
					ref={textareaRef}
					rows={1}
					value={value}
					disabled={disabled}
					placeholder={placeholder}
					className="max-h-[200px] min-h-[24px] w-full flex-1 resize-none bg-transparent py-1.5 text-sm text-gray-200 placeholder:text-gray-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
					onChange={(event) => handleChange(event.target.value)}
					onKeyDown={handleKeyDown}
				/>
				<button
					type="submit"
					disabled={!canSend}
					aria-label="Send message"
					className="mb-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-gray-700"
				>
					<Send className="h-4 w-4" />
				</button>
			</form>
		</div>
	);
};

export default ChatComposer;
