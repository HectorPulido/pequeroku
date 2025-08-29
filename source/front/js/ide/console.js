import { ansiToHtml } from "../shared/ansi.js";

export function setupConsole({
	consoleEl,
	sendBtn,
	inputEl,
	ctrlButtons = [],
	onSend,
}) {
	const history = [];
	let hIdx = -1;

	function addLine(raw) {
		const html = ansiToHtml(raw);
		const lines = html.split(/\n/);
		for (let i = 0; i < lines.length; i++) {
			const line = lines[i];
			if (line === "" && i === lines.length - 1) break;
			consoleEl.insertAdjacentHTML("beforeend", `<div>${line}</div>`);
		}
		consoleEl.scrollTop = consoleEl.scrollHeight;
	}

	sendBtn.addEventListener("click", () => {
		const v = inputEl.value;
		inputEl.value = "";
		history.push(v);
		hIdx = history.length;
		onSend?.(v);
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
	});

	// biome-ignore lint/suspicious/useIterableCallbackReturn: This is correct
	ctrlButtons.forEach((btn) =>
		btn.addEventListener("click", () => {
			const p = btn.getAttribute("param");
			if (p === "ctrlc" || p === "ctrld" || p === "clear")
				onSend?.({ action: p });
		}),
	);

	return { addLine };
}
