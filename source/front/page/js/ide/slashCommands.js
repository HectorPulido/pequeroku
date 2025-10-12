/**
 * Reusable slash commands handler for the IDE console.
 *
 * Usage:
 *   import { createSlashCommandHandler } from "./slashCommands.js";
 *
 *   const slash = createSlashCommandHandler({
 *     // Required to print output in console:
 *     addLine: (text, sid) => consoleApi.addLine(text, sid),
 *     getActiveSid: () => consoleApi.getActive?.(),
 *
 *     // Optional actions (commands will be auto-registered only if provided):
 *     clear: (sid) => consoleApi.clear(sid),
 *     openAi: () => btnOpenAiModal?.click(),
 *     openGithub: () => btnCloneRepo?.click(),
 *     toggleTheme: () => toggleTheme(), // or themeToggleBtn?.click()
 *     listSessions: () => consoleApi.listSessions?.() ?? [],
 *     openSession: (sid) => ws?.send?.({ control: "open", sid }),
 *     closeSession: (sid) => ws?.send?.({ control: "close", sid }),
 *     focusSession: (sid) => ws?.send?.({ control: "focus", sid }),
 *     run: () => runCodeBtn?.click?.(),           // or ws.send({ data: runCommand })
 *     openFile: (path) => openFileIntoEditor(...), // needs to be wired by caller
 *     saveFile: () => saveCurrentFile?.(),
 *   });
 *
 *   // In the console onSend:
 *   onSend: (input) => {
 *     if (slash.handle(input)) return; // handled locally, do not send to backend
 *     // ... send to backend
 *   }
 */

/**
 * @typedef {Object} SlashDeps
 * @property {(text: string, sid?: string|null) => void} addLine
 * @property {() => (string|null|undefined)} getActiveSid
 * @property {(sid?: string|null) => void} [clear]
 * @property {() => void} [openAi]
 * @property {() => void} [openGithub]
 * @property {() => void} [toggleTheme]
 * @property {() => string[]} [listSessions]
 * @property {(sid: string) => void} [openSession]
 * @property {(sid: string) => void} [closeSession]
 * @property {(sid: string) => void} [focusSession]
 * @property {() => void|Promise<void>} [run]
 * @property {(path: string) => void|Promise<void>} [openFile]
 * @property {() => void|Promise<void>} [saveFile]
 */

/**
 * @typedef {{ run:(args:string[])=>void|Promise<void>, desc:string, usage?:string }} SlashCommand
 */

/**
 * Create a slash command handler
 * @param {SlashDeps} deps
 */
export function createSlashCommandHandler(deps) {
	const {
		addLine,
		getActiveSid,
		clear,
		openAi,
		openGithub,
		toggleTheme,
		listSessions,
		openSession,
		closeSession,
		focusSession,
		run,
		openFile,
		saveFile,
	} = deps;

	/** @type {Map<string, SlashCommand>} */
	const commands = new Map();

	// Helper to print to active console
	const print = (text) =>
		addLine?.(String(text ?? ""), getActiveSid?.() || null);

	const register = (name, def) => {
		commands.set(`/${name}`, def);
	};

	// Core requested commands
	if (typeof openAi === "function") {
		register("ai", {
			desc: "Open AI panel",
			run: () => {
				print("[local] Opening AI panel...");
				openAi();
			},
		});
	}

	if (typeof openGithub === "function") {
		register("github", {
			desc: "Open GitHub modal",
			run: () => {
				print("[local] Opening GitHub modal...");
				openGithub();
			},
		});
	}

	if (typeof toggleTheme === "function") {
		register("toggle-lights", {
			desc: "Toggle theme (light/dark)",
			run: () => {
				print("[local] Toggling theme...");
				toggleTheme();
			},
		});
	}

	if (typeof clear === "function") {
		register("clear", {
			desc: "Clear console",
			run: () => {
				print("[local] Clearing console...");
				clear(getActiveSid?.() || null);
			},
		});
	}

	// Optional quality-of-life commands (auto-registered only if deps exist)
	if (typeof listSessions === "function") {
		register("sessions", {
			desc: "List console sessions",
			run: () => {
				const list = listSessions() || [];
				print(`[local] Sessions: ${list.length ? list.join(", ") : "none"}`);
			},
		});
	}

	if (typeof openSession === "function") {
		register("new-session", {
			desc: "Open a new console session",
			usage: "/new-session [sid]",
			run: (args) => {
				let sid = args[0];
				if (!sid && typeof listSessions === "function") {
					const list = listSessions() || [];
					let i = 1;
					while (list.includes(`s${i}`)) i++;
					sid = `s${i}`;
				}
				sid = sid || "s1";
				print(`[local] Opening session ${sid}...`);
				openSession(sid);
			},
		});
	}

	if (typeof closeSession === "function") {
		register("close-session", {
			desc: "Close the active (or specified) console session",
			usage: "/close-session [sid]",
			run: (args) => {
				const sid = args[0] || getActiveSid?.();
				if (!sid) {
					print("[local] No active session to close");
					return;
				}
				print(`[local] Closing session ${sid}...`);
				closeSession(sid);
			},
		});
	}

	if (typeof focusSession === "function") {
		register("focus", {
			desc: "Focus a console session",
			usage: "/focus <sid>",
			run: (args) => {
				const sid = args[0];
				if (!sid) {
					print("[local] Usage: /focus <sid>");
					return;
				}
				print(`[local] Focusing session ${sid}...`);
				focusSession(sid);
			},
		});
	}

	if (typeof run === "function") {
		register("run", {
			desc: "Run configured command (if any)",
			run: async () => {
				print("[local] Running...");
				await run();
			},
		});
	}

	if (typeof openFile === "function") {
		register("open", {
			desc: "Open a file in the editor",
			usage: "/open <path>",
			run: async (args) => {
				const path = args.join(" ");
				if (!path) {
					print("[local] Usage: /open <path>");
					return;
				}
				print(`[local] Opening file ${path}...`);
				await openFile(path);
			},
		});
	}

	if (typeof saveFile === "function") {
		register("save", {
			desc: "Save the active file",
			run: async () => {
				print("[local] Saving file...");
				await saveFile();
			},
		});
	}

	// Help command is always available and reflects registered commands
	register("help", {
		desc: "Show available commands",
		run: () => {
			const lines = ["[local] Available commands:"];
			const keys = Array.from(commands.keys()).sort();
			for (const key of keys) {
				const c = commands.get(key);
				if (!c) continue;
				// fixed padding for nicer alignment
				lines.push(`  ${key.padEnd(16, " ")} - ${c.desc}`);
				if (c.usage) lines.push(`    ${c.usage}`);
			}
			print(lines.join("\n"));
		},
	});

	/**
	 * Parse a raw input into {cmd,args}
	 * Supports simple whitespace splitting. Keep minimal for robustness.
	 */
	function parse(raw) {
		const s = String(raw || "").trim();
		if (!s.startsWith("/")) return null;
		const parts = s.split(/\s+/);
		const cmd = parts[0].toLowerCase();
		const args = parts.slice(1);
		return { cmd, args };
	}

	/**
	 * Handle a user input, returning true if handled locally (do not send to backend)
	 * @param {string} input
	 * @returns {boolean}
	 */
	function handle(input) {
		const parsed = parse(input);
		if (!parsed) return false; // not a slash command
		const { cmd, args } = parsed;
		const entry = commands.get(cmd);
		if (!entry) {
			print("[local] Unknown command. Type /help");
			return true; // still handled locally
		}
		try {
			const out = entry.run(args);
			if (out && typeof out.then === "function") {
				// best effort: swallow async errors
				out.catch?.(() => {});
			}
		} catch {
			// no-op: keep console clean
		}
		return true;
	}

	/**
	 * Return the help text as a string (without printing)
	 * @returns {string}
	 */
	function getHelpText() {
		const lines = ["Available commands:"];
		const keys = Array.from(commands.keys()).sort();
		for (const key of keys) {
			const c = commands.get(key);
			if (!c) continue;
			lines.push(`  ${key} - ${c.desc}`);
			if (c.usage) lines.push(`    ${c.usage}`);
		}
		return lines.join("\n");
	}

	return { handle, getHelpText };
}
