import { Send } from "iconoir-react";
import type React from "react";
import { useCallback, useEffect, useRef } from "react";

interface ChatComposerProps {
	value: string;
	onChange: (value: string) => void;
	onSubmit: () => void;
	disabled?: boolean;
	canSend: boolean;
	placeholder?: string;
}

const ChatComposer: React.FC<ChatComposerProps> = ({
	value,
	onChange,
	onSubmit,
	disabled = false,
	canSend,
	placeholder = "Type a message...",
}) => {
	const textareaRef = useRef<HTMLTextAreaElement | null>(null);

	const autoResize = useCallback(() => {
		const el = textareaRef.current;
		if (!el) return;
		el.style.height = "auto";
		el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
	}, []);

	useEffect(() => {
		autoResize();
	}, [autoResize]);

	return (
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
				onChange={(event) => {
					onChange(event.target.value);
					requestAnimationFrame(autoResize);
				}}
				onKeyDown={(event) => {
					if (event.key === "Enter" && !event.shiftKey) {
						event.preventDefault();
						if (canSend) onSubmit();
					}
				}}
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
	);
};

export default ChatComposer;
