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

	// Themes
	const light_theme = {
		background: "#2d2d2d",
		foreground: "#fff",
		cursor: "#2d2d2d",
		selectionBackground: "#111111",
	};
	const dark_theme = {
		background: "#0b0d10",
		foreground: "#d1d5db",
		cursor: "#11161c",
		selectionBackground: "#374151",
	};

	// Multi-session state
	const sessions = new Map(); // sid -> { term, fitAddon, el }
	let activeSid = null;

	function createSessionElements(sid) {
		const el = document.createElement("div");
		el.className = "console-session";
		el.style.width = "100%";
		el.style.height = "100%";
		el.style.display = "none";
		el.dataset.sid = sid;
		consoleEl.appendChild(el);
		return el;
	}

	function openSession(sid, makeActive = true) {
		if (!sid || typeof sid !== "string") return;
		if (sessions.has(sid)) {
			if (makeActive) focusSession(sid);
			return;
		}
		const el = createSessionElements(sid);
		const term = new Terminal({
			cursorBlink: false,
			scrollback: 5000,
			convertEol: false,
			fontFamily:
				'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
			fontSize: 13,
			theme: light_theme,
		});
		const fitAddon = new FitAddon();
		term.loadAddon(fitAddon);
		term.open(el);
		fitAddon.fit();

		sessions.set(sid, { term, fitAddon, el });

		// Default focus to first session opened
		if (activeSid == null || makeActive) {
			focusSession(sid);
		}
	}

	function closeSession(sid) {
		const s = sessions.get(sid);
		if (!s) return;
		try {
			s.term.dispose();
		} catch {}
		try {
			s.el.remove();
		} catch {}
		sessions.delete(sid);

		if (activeSid === sid) {
			activeSid = null;
			// focus first available, if any
			const next = sessions.keys().next();
			if (!next.done) {
				focusSession(next.value);
			}
		}
	}

	function focusSession(sid) {
		if (!sessions.has(sid)) return;
		// hide current
		if (activeSid && sessions.has(activeSid)) {
			const cur = sessions.get(activeSid);
			if (cur) cur.el.style.display = "none";
		}
		// show new
		activeSid = sid;
		const s = sessions.get(sid);
		if (s) {
			s.el.style.display = "block";
			try {
				s.fitAddon.fit();
			} catch {}
		}
	}

	function addLine(text, sid = activeSid) {
		if (text == null) return;
		const s = sid ? sessions.get(sid) : null;
		if (!s) return;
		let t = String(text).replace(/\r(?!\n)/g, "\n");
		if (!/\n$/.test(t)) t += "\n";
		s.term.write(t);
	}

	function write(data, sid = activeSid) {
		const s = sid ? sessions.get(sid) : null;
		if (!s) return;
		s.term.write(typeof data === "string" ? data : new Uint8Array(data));
	}

	function clear(sid = activeSid) {
		const s = sid ? sessions.get(sid) : null;
		if (!s) return;
		s.term.clear();
	}

	function fit() {
		const s = activeSid ? sessions.get(activeSid) : null;
		if (!s) return;
		try {
			s.fitAddon.fit();
		} catch {}
	}

	function setTheme(isDark) {
		const theme = isDark ? dark_theme : light_theme;
		// apply to all sessions
		sessions.forEach(({ term }) => {
			try {
				term.options = { theme };
			} catch {}
		});
	}

	// Initialize with a default session
	openSession("s1", true);

	if (sendBtn && inputEl) {
		sendBtn.addEventListener("click", () => {
			const v = inputEl.value;
			inputEl.value = "";
			history.push(v);
			hIdx = history.length;
			// Do NOT auto-append newline; backend will handle it
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
			if (e.ctrlKey) {
				// Ctrl + C
				if (e.key === "c" || e.key === "C") {
					e.preventDefault();
					onSend?.("ctrlc");
				}
				// Ctrl + D
				if (e.key === "d" || e.key === "D") {
					e.preventDefault();
					onSend?.("ctrld");
				}
			}
		});

		inputEl.addEventListener("focus", () => {
			setTimeout(() => {
				try {
					consoleEl.scrollIntoView({ block: "nearest", behavior: "smooth" });
				} catch {}
			}, 50);
		});
	}

	// biome-ignore lint/suspicious/useIterableCallbackReturn: This is correct
	ctrlButtons.forEach((btn) =>
		btn.addEventListener("click", () => {
			const p = btn.getAttribute("param");
			onSend?.(p);
		}),
	);

	return {
		// current terminal (active)
		term: {
			get current() {
				return activeSid ? sessions.get(activeSid)?.term : null;
			},
		},
		// writing
		addLine: (text, sid) => addLine(text, sid),
		write: (data, sid) => write(data, sid),
		clear: (sid) => clear(sid),
		fit,
		setTheme,
		// sessions
		openSession,
		closeSession,
		focusSession,
		getActive: () => activeSid,
		listSessions: () => Array.from(sessions.keys()),
	};
}
