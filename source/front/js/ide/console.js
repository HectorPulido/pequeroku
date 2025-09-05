import "https://esm.sh/xterm@5.3.0/css/xterm.css";
import { Terminal } from "https://esm.sh/xterm@5.3.0";
import { FitAddon } from "https://esm.sh/xterm-addon-fit@0.8.0";

export function setupConsole({
	consoleEl,
	sendBtn,
	inputEl,
	ctrlButtons = [],
	onSend,
	onResize,
}) {
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

	const pending = [];
	let sending = false;
	const CHUNK = 64 * 1024; // 64KB

	async function sendBuffered(data) {
		if (!data) return;
		for (let i = 0; i < data.length; i += CHUNK) {
			pending.push(data.slice(i, i + CHUNK));
		}
		if (!sending) {
			sending = true;
			while (pending.length) {
				const chunk = pending.shift();
				onSend?.({ type: "input", data: chunk });
				const UMBRAL = 512 * 1024;
				while (
					typeof onSend.ws?.bufferedAmount === "number" &&
					onSend.ws.bufferedAmount > UMBRAL
				) {
					await new Promise((r) => setTimeout(r, 10));
				}
			}
			sending = false;
		}
	}

	term.onData((data) => sendBuffered(data));
	term.onResize((size) => onResize?.(size));

	if (sendBtn && inputEl) {
		sendBtn.addEventListener("click", () => {
			const v = inputEl.value;
			inputEl.value = "";
			if (v) sendBuffered(`v\n`);
		});
		inputEl.addEventListener("keydown", (e) => {
			if (e.key === "Enter") {
				e.preventDefault();
				sendBtn.click();
			}
		});
	}

	// Ctrl-buttons
	ctrlButtons.forEach((btn) => {
		btn.addEventListener("click", () => {
			const p = btn.getAttribute("param");
			if (p === "ctrlc")
				sendBuffered("\x03"); // ETX
			else if (p === "ctrld")
				sendBuffered("\x04"); // EOT
			else if (p === "clear") term.clear();
		});
	});

	let fitT;
	window.addEventListener("resize", () => {
		clearTimeout(fitT);
		fitT = setTimeout(() => {
			try {
				fitAddon.fit();
				const cols = term.cols,
					rows = term.rows;
				onResize?.({ cols, rows });
			} catch {}
		}, 100);
	});

	function addLine(text) {
		term.writeln(text ?? "");
	}

	function write(data) {
		term.write(typeof data === "string" ? data : new Uint8Array(data));
	}

	function fit() {
		fitAddon.fit();
	}

	function resizeToServer() {
		onResize?.({ cols: term.cols, rows: term.rows });
	}

	return {
		term,
		addLine,
		write,
		clear: () => term.clear(),
		fit,
		resizeToServer,
	};
}
