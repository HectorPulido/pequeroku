import { Check, Copy } from "iconoir-react";
import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { copyToClipboard } from "@/lib/clipboard";

interface CopyButtonProps {
	/** Text placed on the clipboard when the button is pressed. */
	text: string;
	/** Extra classes appended to the button (e.g. hover-reveal helpers). */
	className?: string;
	label?: string;
}

/**
 * Small icon button that copies `text` to the clipboard and briefly swaps to a
 * check mark as confirmation. Rendered under chat messages in the AI studio.
 */
const CopyButton: React.FC<CopyButtonProps> = ({ text, className = "", label = "Copy" }) => {
	const [copied, setCopied] = useState(false);
	const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

	useEffect(
		() => () => {
			if (timeoutRef.current) clearTimeout(timeoutRef.current);
		},
		[],
	);

	const handleCopy = useCallback(async () => {
		if (!(await copyToClipboard(text))) return;
		setCopied(true);
		if (timeoutRef.current) clearTimeout(timeoutRef.current);
		timeoutRef.current = setTimeout(() => setCopied(false), 1500);
	}, [text]);

	return (
		<button
			type="button"
			onClick={handleCopy}
			title={copied ? "Copied" : label}
			aria-label={copied ? "Copied" : label}
			className={`inline-flex items-center gap-1 rounded p-1 text-gray-500 transition hover:text-gray-200 ${className}`}
		>
			{copied ? (
				<Check className="h-3.5 w-3.5 text-emerald-400" />
			) : (
				<Copy className="h-3.5 w-3.5" />
			)}
		</button>
	);
};

export default CopyButton;
