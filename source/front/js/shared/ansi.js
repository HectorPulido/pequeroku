/** biome-ignore-all lint/suspicious/noControlCharactersInRegex: Those came from the console */
/** biome-ignore-all lint/suspicious/useIterableCallbackReturn: This is correct */
import { escapeHtml } from "../core/dom.js";

export function ansiToHtml(raw) {
	if (/\x1b\[[0-9;?]*[HJ]/.test(raw) || /\x1b\[[23]J/.test(raw)) {
		raw = raw.replace(/\x1b\[[0-9;?]*[HJ]/g, "").replace(/\x1b\[[23]J/g, "");
	}
	raw = raw.replace(/\x1b\[\?2004[hl]/g, ""); // bracketed paste
	raw = raw.replace(/\x1b\][^\x07]*\x07/g, ""); // OSC title
	raw = raw.replace(/\x07/g, ""); // BEL

	const parts = raw.split(/(\x1b\[[0-9;]*m)/g);
	const classes = new Set();
	let html = "";

	for (const token of parts) {
		const m = /^\x1b\[([0-9;]*)m$/.exec(token);
		if (m) {
			const params = m[1] === "" ? ["0"] : m[1].split(";");
			for (const p of params) {
				const code = parseInt(p, 10);
				if (Number.isNaN(code)) continue;
				if (code === 0) classes.clear();
				else if (code === 1) classes.add("ansi-bold");
				else if (code === 4) classes.add("ansi-underline");
				else if ((30 <= code && code <= 37) || (90 <= code && code <= 97)) {
					[...classes].forEach((c) => /^ansi-fg-/.test(c) && classes.delete(c));
					classes.add(`ansi-fg-${code}`);
				} else if ((40 <= code && code <= 47) || (100 <= code && code <= 107)) {
					[...classes].forEach((c) => /^ansi-bg-/.test(c) && classes.delete(c));
					classes.add(`ansi-bg-${code}`);
				} else if (code === 22) classes.delete("ansi-bold");
				else if (code === 24) classes.delete("ansi-underline");
			}
		} else {
			const safe = escapeHtml(token).replace(/\r(?!\n)/g, "\n");
			if (!safe) continue;
			html += classes.size
				? `<span class="${[...classes].join(" ")}">${safe}</span>`
				: safe;
		}
	}
	return html;
}
