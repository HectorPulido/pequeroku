import { Terminal } from "https://esm.sh/xterm@5.3.0";
import { FitAddon } from "https://esm.sh/xterm-addon-fit@0.8.0";

export function setupConsole({
	consoleEl,
	sendBtn,
	inputEl,
	ctrlButtons = [],
	onSend,
}) {
	const history = [];
	let hIdx = -1;

	const term = new Terminal({
		cursorBlink: true,
		scrollback: 5000,
		convertEol: false,
		fontFamily:
			'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
		fontSize: 13,
		theme: { background: "#111111" },
	});
	const fitAddon = new FitAddon();
	term.loadAddon(fitAddon);
	term.open(consoleEl);
	fitAddon.fit();

	if (sendBtn && inputEl) {
		sendBtn.addEventListener("click", () => {
			const v = inputEl.value;
			inputEl.value = "";
			history.push(v);
			hIdx = history.length;
			onSend?.(v + "\n");
		});

		inputEl.addEventListener("keydown", (e) => {
			if (e.key === "Enter") {
				e.preventDefault();
				sendBtn.click();
			}
			if (e.key === "ArrowUp") {
				e.preventDefault();
				if (hIdx > 0) inputEl.value = history[--hIdx] || "";
			}
			if (e.key === "ArrowDown") {
				e.preventDefault();
				if (hIdx < history.length - 1) inputEl.value = history[++hIdx] || "";
				else {
					hIdx = history.length;
					inputEl.value = "";
				}
			}
			if (e.ctrlKey) {
				// Ctrl + C
				if (e.key === "c" || e.key === "C") {
					e.preventDefault();
					onSend?.({ action: 'ctrlc' });
				}
				// Ctrl + D
				if (e.key === "d" || e.key === "D") {
					e.preventDefault();
					onSend?.({ action: 'ctrld' });
				}
			}
		});
	}

	// biome-ignore lint/suspicious/useIterableCallbackReturn: This is correct
	ctrlButtons.forEach((btn) =>
		btn.addEventListener("click", () => {
			const p = btn.getAttribute("param");
			onSend?.({ action: p });
			console.log("executing:", { action: p })
		}),
	);

	function addLine(text) {
		if (text == null) return;
		let t = String(text).replace(/\r(?!\n)/g, "\n");
		if (!/\n$/.test(t)) t += "\n";
		term.write(t);
	}

	function write(data) {
		term.write(typeof data === "string" ? data : new Uint8Array(data));
	}

	function fit() {
		fitAddon.fit();
	}

	return {
		term,
		addLine,
		write,
		clear: () => term.clear(),
		fit,
	};
}
