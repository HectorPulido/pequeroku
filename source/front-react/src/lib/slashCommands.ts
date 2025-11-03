type SlashDeps = {
	addLine: (text: string) => void;
	getActiveSession: () => string | null;
	clear?: (sid?: string | null) => void;
	openAi?: () => void;
	openGithub?: () => void;
	toggleTheme?: () => void;
	listSessions?: () => string[];
	openSession?: (sid?: string) => void;
	closeSession?: (sid: string) => void;
	focusSession?: (sid: string) => void;
	run?: () => Promise<void> | void;
	openFile?: (path: string) => Promise<void> | void;
	saveFile?: () => Promise<void> | void;
};

type SlashCommand = {
	run: (args: string[]) => Promise<void> | void;
	desc: string;
	usage?: string;
};

const parseArgs = (input: string) => input.trim().split(/\s+/).filter(Boolean);

export const createSlashCommandHandler = (deps: SlashDeps) => {
	const {
		addLine,
		getActiveSession,
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

	const commands = new Map<string, SlashCommand>();

	const print = (text: string) => {
		try {
			addLine(String(text ?? ""));
		} catch (error) {
			console.error("slash print failed", error);
		}
	};

	const register = (name: string, command: SlashCommand) => {
		commands.set(`/${name}`, command);
	};

	if (typeof openAi === "function") {
		register("ai", {
			desc: "Open AI assistant",
			run: () => {
				print("[local] Opening AI panel…");
				openAi();
			},
		});
	}

	if (typeof openGithub === "function") {
		register("github", {
			desc: "Open GitHub modal",
			run: () => {
				print("[local] Opening GitHub modal…");
				openGithub();
			},
		});
	}

	if (typeof toggleTheme === "function") {
		register("toggle-lights", {
			desc: "Toggle light/dark theme",
			run: () => {
				print("[local] Toggling theme…");
				toggleTheme();
			},
		});
	}

	if (typeof clear === "function") {
		register("clear", {
			desc: "Clear the active console",
			run: () => {
				const sid = getActiveSession();
				clear(sid);
				print("[local] Console cleared.");
			},
		});
	}

	if (typeof listSessions === "function") {
		register("sessions", {
			desc: "List console sessions",
			run: () => {
				const list = listSessions() ?? [];
				print(list.length ? `[local] Sessions: ${list.join(", ")}` : "[local] No sessions open.");
			},
		});
	}

	if (typeof openSession === "function") {
		register("new-session", {
			desc: "Open a new console session",
			usage: "/new-session [sid]",
			run: (args) => {
				const sid = args[0];
				openSession(sid);
				print(`[local] Opening session ${sid ?? "(auto)"}…`);
			},
		});
	}

	if (typeof closeSession === "function") {
		register("close-session", {
			desc: "Close the active (or specified) console session",
			usage: "/close-session [sid]",
			run: (args) => {
				const sid = args[0] || getActiveSession();
				if (!sid) {
					print("[local] No session to close.");
					return;
				}
				closeSession(sid);
				print(`[local] Closing session ${sid}…`);
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
				focusSession(sid);
				print(`[local] Focusing session ${sid}…`);
			},
		});
	}

	if (typeof run === "function") {
		register("run", {
			desc: "Run configured command",
			run: async () => {
				print("[local] Running…");
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
				print(`[local] Opening ${path}…`);
				await openFile(path);
			},
		});
	}

	if (typeof saveFile === "function") {
		register("save", {
			desc: "Save the active file",
			run: async () => {
				print("[local] Saving file…");
				await saveFile();
			},
		});
	}

	register("help", {
		desc: "Show available commands",
		run: () => {
			const lines: string[] = [];
			commands.forEach((command, key) => {
				lines.push(`${key} — ${command.desc}`);
				if (command.usage) {
					lines.push(`  usage: ${command.usage}`);
				}
			});
			print(lines.join("\r\n"));
		},
	});

	const handle = (inputRaw: string) => {
		const input = inputRaw.trim();
		if (!input.startsWith("/")) {
			return false;
		}

		const [commandToken, ...rest] = input.split(" ");
		const command = commands.get(commandToken.toLowerCase());
		if (!command) {
			print(`[local] Unknown command: ${commandToken}. Try /help.`);
			return true;
		}
		try {
			const args = parseArgs(rest.join(" "));
			const result = command.run(args);
			if (result instanceof Promise) {
				result.catch((error) => {
					console.error("Slash command failed", error);
					print(
						`[local] Command failed: ${error instanceof Error ? error.message : String(error)}`,
					);
				});
			}
		} catch (error) {
			console.error("Slash command failed", error);
			print(`[local] Command failed: ${error instanceof Error ? error.message : String(error)}`);
		}
		return true;
	};

	return {
		handle,
		list: () =>
			Array.from(commands.entries()).map(([name, command]) => ({
				name,
				desc: command.desc,
				usage: command.usage,
			})),
	};
};
