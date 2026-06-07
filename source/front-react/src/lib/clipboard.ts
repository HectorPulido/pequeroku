/**
 * Copy `text` to the clipboard. Prefers the async Clipboard API (available on
 * HTTPS / localhost) and falls back to a hidden <textarea> + execCommand for
 * insecure origins where `navigator.clipboard` is missing. Returns whether the
 * copy succeeded so callers can decide whether to show confirmation.
 */
export const copyToClipboard = async (text: string): Promise<boolean> => {
	try {
		if (navigator.clipboard?.writeText) {
			await navigator.clipboard.writeText(text);
			return true;
		}
	} catch {
		/* fall through to the legacy path below */
	}

	try {
		const textarea = document.createElement("textarea");
		textarea.value = text;
		textarea.setAttribute("readonly", "");
		textarea.style.position = "fixed";
		textarea.style.opacity = "0";
		textarea.style.pointerEvents = "none";
		document.body.appendChild(textarea);
		textarea.select();
		const ok = document.execCommand("copy");
		document.body.removeChild(textarea);
		return ok;
	} catch {
		return false;
	}
};
