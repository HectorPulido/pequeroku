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

	term.onData((data) => onSend?.(data));
	term.onResize((size) => onResize?.(size));

	if (sendBtn && inputEl) {
		sendBtn.addEventListener("click", () => {
			const v = inputEl.value;
			inputEl.value = "";
			if (v) onSend?.(`${v}\n`);
		});

		inputEl.addEventListener("keydown", (e) => {
			if (e.key === "Enter") {
				e.preventDefault();
				sendBtn.click();
			}
		});
	}

	inputEl.addEventListener("keydown", (e) => {
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
	});

	// biome-ignore lint/suspicious/useIterableCallbackReturn: This is correct
	ctrlButtons.forEach((btn) =>
		btn.addEventListener("click", () => {
			const p = btn.getAttribute("param");
			onSend?.({ action: p });
		}),
	);

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
