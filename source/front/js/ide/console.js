import { Terminal } from "https://esm.sh/xterm@5.3.0";
import { FitAddon } from "https://esm.sh/xterm-addon-fit@0.8.0";
import { $, $$ } from "../core/dom.js";

export function setupConsole({ onSend }) {
	const sendBtn = $("#send-cmd");
	const inputEl = $("#console-cmd");
	const consoleEl = $("#console-log");
	const ctrlButtons = $$(".btn-send");

	const history = [];
	let hIdx = -1;

	// Themes
	const light_theme = {
		background: "#2d2d2d",
		foreground: "#fff",
		cursor: "#fff",
		selectionBackground: "#111111",
	};
	const dark_theme = {
		background: "#0b0d10",
		foreground: "#d1d5db",
		cursor: "#d1d5db",
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
			cursorBlink: true,
			scrollback: 5000,
			termName: "xterm-256color",
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
		// Send initial and delayed resize to ensure PTY matches terminal size
		const __sendInitialResize = () => {
			try {
				const c = term.cols || 80;
				const r = term.rows || 24;
				onSend?.(`__RESIZE__ ${c}x${r}`);
			} catch {}
		};
		__sendInitialResize();
		setTimeout(__sendInitialResize, 1500);
		// Stream raw key input to backend (no newline auto-append)
		term.onData((data) => {
			onSend?.(data);
		});
		// Notify backend of terminal size changes so it can resize the PTY
		term.onResize(({ cols, rows }) => {
			onSend?.(`__RESIZE__ ${cols}x${rows}`);
		});

		sessions.set(sid, { term, fitAddon, el });
		try {
			window.dispatchEvent(
				new CustomEvent("console:session-opened", { detail: { sid } }),
			);
		} catch {}

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
		try {
			window.dispatchEvent(
				new CustomEvent("console:session-closed", { detail: { sid } }),
			);
		} catch {}

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
			try {
				s.term.focus();
			} catch {}
		}
	}

	function addLine(text, sid = activeSid) {
		if (text == null) return;
		const s = sid ? sessions.get(sid) : null;
		if (!s) return;
		let t = String(text);
		// Normalize all newlines to CRLF
		t = t.replace(/\r\n/g, "\n").replace(/\r/g, "\n").replace(/\n/g, "\r\n");
		// Prepend CRLF only if not at column 0 (avoid double-leading breaks)
		let atCol0 = false;
		try {
			atCol0 = s.term.buffer?.active?.cursorX === 0;
		} catch {}
		if (!atCol0) t = `\r\n${t}`;
		if (!/\r\n$/.test(t)) t += "\r\n";
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
		// Ensure terminal recalculates dimensions after theme change
		try {
			fit();
		} catch {}
	}

	// Initialize with a default session
	openSession("s1", true);
	// Ensure initial fit after layout settles
	setTimeout(() => {
		try {
			fit();
		} catch {}
	}, 50);

	// Fit xterm when the layout changes or a terminal-resize event is dispatched
	window.addEventListener("resize", () => {
		try {
			fit();
		} catch {}
	});
	window.addEventListener("terminal-resize", () => {
		try {
			fit();
		} catch {}
	});

	if (sendBtn && inputEl) {
		sendBtn.addEventListener("click", () => {
			const vRaw = inputEl.value;
			let v = vRaw;
			// Append newline so the shell executes the command
			if·(!v.endsWith("\n"));
			v = `${v}\n`;
			inputEl.value = "";
			history.push(vRaw);
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
		// get a terminal instance by session id
		getTerm: (sid) => (sid ? sessions.get(sid)?.term || null : null),
		// writing
		addLine: (text, sid) => addLine(text, sid),
		write: (data, sid) => write(data, sid),
		clear: (sid) => clear(sid),
		fit,
		setTheme,
		openSession,
		closeSession,
		focusSession,
		getActive: () => activeSid,
		listSessions: () => Array.from(sessions.keys()),
	};
}
