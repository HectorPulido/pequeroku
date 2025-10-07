import { makeApi } from "../core/api.js";
import { $ } from "../core/dom.js";
import { installGlobalLoader } from "../core/loader.js";
import { ideStore } from "../core/store.js";
import {
	applyTheme,
	getCurrentTheme,
	setupThemeToggle,
	toggleTheme,
} from "../core/themes.js";
import { hideHeader } from "../core/utils.js";
import { setupConsole } from "./console.js";
import { createDirtyTracker } from "./dirtyTracker.js";
import {
	changeTheme,
	clearEditor,
	discardPathModel,
	getEditor,
	getEditorValue,
	loadMonaco,
	mobileConfig,
	openFile as openFileIntoEditor,
} from "./editor.js";
import { setupFileActions } from "./fileActions.js";
import { setupFileTree } from "./files.js";
import { createFSWS } from "./fs-ws.js";
import { createReadFileApi } from "./fsAdapter.js";
import { setupGithubModal } from "./githubModal.js";
import { setupHiddableDragabble } from "./hiddableDraggable.js";
import { setupRunButton } from "./runButton.js";
import { loadRunConfig } from "./runConfig.js";
import { setupSearchUI } from "./search.js";
import { createSlashCommandHandler } from "./slashCommands.js";
import { setupConsoleTabs, setupFileTabs } from "./tabs.js";
import { setupTemplates } from "./templates.js";
import { setupUploads } from "./uploads.js";
import { setupWSController } from "./wsController.js";

installGlobalLoader();
applyTheme();
loadMonaco(getCurrentTheme() === "dark");
hideHeader();

// ====== CONFIG ======
const urlParams = new URLSearchParams(window.location.search);
const containerId = urlParams.get("containerId");
const containerPk = parseInt(containerId, 10);
const api = makeApi(`/api/containers/${containerId}`);
ideStore.actions.setContainer(containerId);

// ====== DOM refs ======
const themeToggleBtn = $("#theme-toggle");
const pathLabel = $("#current_path_label");
const refreshTreeBtn = $("#refresh-tree");
const fileTreeEl = $("#file-tree");
const restartContainerBtn = $("#restart-container");
const runCodeBtn = $("#run-code");
const btnOpenSession = $("#btn-open-session");
const btnCloseSession = $("#btn-close-session");
const btnTogglePreview = $("#toggle-preview");

const btnOpenAiModal = $("#btn-open-ai-modal");

await setupHiddableDragabble(containerId, async (arg) => {
	if (typeof arg === "boolean") {
		await mobileConfig(arg);
	}
});

if (themeToggleBtn) setupThemeToggle(themeToggleBtn);

let apiReadFileWrapper = null;
let consoleApi = null;

let wsCtrl = null;
let slash = null;

const dirty = createDirtyTracker({ onChange: () => fileTabs.update?.() });

const consoleTabs = setupConsoleTabs({
	onFocus: (sid) => {
		wsCtrl?.focusSession?.(sid);
		try {
			consoleApi?.focusSession?.(sid);
		} catch {}
		try {
			ideStore.actions.console.focus(sid);
		} catch {}
		try {
			consoleTabs.update?.();
		} catch {}
	},
	onClose: (sid) => {
		wsCtrl?.closeSession?.(sid);
		try {
			consoleApi?.closeSession?.(sid);
		} catch {}
		try {
			ideStore.actions.console.close(sid);
		} catch {}
		try {
			consoleTabs.update?.();
		} catch {}
	},
});

const fileTabs = setupFileTabs({
	isDirty: (p) => dirty.isDirty(p),
	openFile: (path) => openFileIntoEditor(apiReadFileWrapper, path, setPath),
	clearEditor: () => {
		try {
			clearEditor();
		} catch {}
		pathLabel.innerText = "";
		localStorage.removeItem(`last:${containerId}`);
	},
	discardIfDirty: async (p) => {
		try {
			discardPathModel?.(p);
		} catch {}
	},
});

dirty.attach();

ideStore.select(
	(s) => s.files.active,
	(active) => {
		pathLabel.innerText = active || "";
		if (active) localStorage.setItem(`last:${containerId}`, active);
		else localStorage.removeItem(`last:${containerId}`);
	},
);
let ft;

const fsws = createFSWS({
	containerPk,
	onOpen: async () => {},
	onBroadcast: async (evt) => {
		try {
			const dirs = new Set();
			const t = evt?.event || evt?.type;
			const p1 = typeof evt?.path === "string" ? evt.path : null;
			const p2 = typeof evt?.dst === "string" ? evt.dst : null;
			const parentOf = (p) => (p ? p.replace(/\/[^/]+$/, "") || "/app" : null);

			if (
				t === "path_deleted" ||
				t === "path_moved" ||
				t === "path_created" ||
				t === "path_added" ||
				t === "dir_created" ||
				t === "file_created"
			) {
				const d1 = parentOf(p1);
				const d2 = parentOf(p2);
				if (d1) dirs.add(d1);
				if (d2) dirs.add(d2);
			} else if (t === "file_changed" || t === "changed") {
				// content change: no tree refresh
			} else {
				// Unknown: conservative refresh root
				dirs.add("/app");
			}

			if (dirs.size > 0) {
				await Promise.all(Array.from(dirs).map((d) => ft.refreshPath(d)));
			}
			fileTabs.update?.();
		} catch {}
	},
});

// === "API-like" wrapper so editor.js remains unchanged but reads via WS ===
apiReadFileWrapper = createReadFileApi(fsws);

// === Search UI (extracted module) ===
setupSearchUI({
	fsws,
	openFile: (path) => openFileIntoEditor(apiReadFileWrapper, path, setPath),
	getEditor: () => getEditor?.(),
});

function setPath(p) {
	try {
		ideStore.actions.files.open(p);
	} catch {}
}

const fileActions = setupFileActions({
	fsws,
	getActivePath: () => ideStore.get().files?.active || null,
	getEditor,
	getEditorValue,
	openEditorPath: (path) =>
		openFileIntoEditor(apiReadFileWrapper, path, setPath),
	runHydrate: () => runCtrl?.hydrate?.(),
	onAfterSave: () => {
		try {
			fileTabs.update?.();
		} catch {}
	},
});

function connectWs() {
	wsCtrl = setupWSController({
		containerId,
		consoleApi,
		onTabsChange: () => {
			try {
				consoleTabs.update?.();
			} catch {}
		},
	});
	wsCtrl.connect();
}

const runCtrl = setupRunButton({
	runButtonEl: runCodeBtn,
	browserButtonEl: btnTogglePreview,
	loadRunConfig: () => loadRunConfig(apiReadFileWrapper),
	saveCurrentFile: fileActions.saveCurrentFile,
	wsSend: (payload) => wsCtrl?.sendInput?.(payload?.data ?? payload),
	autoOpenUrl: true,
	readFileApi: apiReadFileWrapper,
});

(async () => {
	consoleApi = setupConsole({
		onSend: (data) => {
			const active = consoleApi.getActive?.() || null;

			// Slash commands: handled locally, do not send to backend
			const raw = String(data || "").trim();
			if (slash?.handle(raw)) return;

			if (!wsCtrl?.hasConnection?.()) return;
			if (data === "clear") {
				consoleApi.clear(active);
				return;
			}
			if (data === "ctrlc") data = "\u0003";
			else if (data === "ctrld") data = "\u0004";
			wsCtrl?.sendInput?.(data);
		},
	});
	try {
		window.dispatchEvent(
			new CustomEvent("terminal-resize", { detail: { target: "console" } }),
		);
		consoleApi?.fit?.();
	} catch {}
	slash = createSlashCommandHandler({
		addLine: (text, sid) => consoleApi.addLine?.(text, sid),
		getActiveSid: () => consoleApi.getActive?.() || null,
		clear: (sid) => consoleApi.clear?.(sid),
		openAi: () => btnOpenAiModal?.click(),
		openGithub: () => github?.open?.(),
		toggleTheme: () => {
			try {
				toggleTheme();
			} catch {
				themeToggleBtn?.click();
			}
		},
		listSessions: () => consoleApi.listSessions?.() || [],
		openSession: (sid) => wsCtrl?.openSession?.(sid),
		closeSession: (sid) => wsCtrl?.closeSession?.(sid),
		focusSession: (sid) => wsCtrl?.focusSession?.(sid),
		run: () => runCodeBtn?.click?.(),
		openFile: (path) => openFileIntoEditor(apiReadFileWrapper, path, setPath),
		saveFile: () => fileActions.saveCurrentFile?.(),
	});
	// Hook to sync tabs with console sessions lifecycle
	const __open = consoleApi.openSession?.bind(consoleApi);
	if (__open) {
		setTimeout(() => {
			consoleApi.setTheme(getCurrentTheme() === "dark");
		}, 1000);
		consoleApi.openSession = (sid, makeActive) => {
			__open(sid, makeActive);
			ideStore.actions.console.open(sid, !!makeActive);
			consoleTabs.update?.();
			setTimeout(() => {
				consoleApi.setTheme(getCurrentTheme() === "dark");
			}, 50);
		};
	}
	const __close = consoleApi.closeSession?.bind(consoleApi);
	if (__close) {
		consoleApi.closeSession = (sid) => {
			__close(sid);
			ideStore.actions.console.close(sid);
			consoleTabs.update?.();
		};
	}
	const __focus = consoleApi.focusSession?.bind(consoleApi);
	if (__focus) {
		consoleApi.focusSession = (sid) => {
			__focus(sid);
			ideStore.actions.console.focus(sid);
			consoleTabs.update?.();
		};
	}

	connectWs();

	// Wire up multi-console session controls
	if (btnOpenSession) {
		btnOpenSession.addEventListener("click", () => {
			const list = ideStore.get().console.sessions || [];
			let i = 1;
			while (list.includes(`s${i}`)) i++;
			const sid = `s${i}`;
			try {
				wsCtrl?.openSession?.(sid);
			} catch {}
			try {
				consoleApi?.openSession?.(sid, true);
			} catch {}
			try {
				ideStore.actions.console.open(sid, true);
			} catch {}
			try {
				consoleTabs.update?.();
			} catch {}
		});
	}
	if (btnCloseSession) {
		btnCloseSession.addEventListener("click", () => {
			const sid = ideStore.get().console.active || null;
			if (sid) {
				try {
					wsCtrl?.closeSession?.(sid);
				} catch {}
				try {
					consoleApi?.closeSession?.(sid);
				} catch {}
				try {
					ideStore.actions.console.close(sid);
				} catch {}
				try {
					consoleTabs.update?.();
				} catch {}
			}
		});
	}
	// Prev/Next session buttons removed in favor of tab UI (console tabs)

	restartContainerBtn.addEventListener("click", () => {
		try {
			wsCtrl?.close?.();
		} catch {}
		consoleApi.clear();
		connectWs();
		fileTabs.update?.();
	});

	ft = setupFileTree({
		fsws,
		fileTreeEl,
		containerId,
		onOpen: (p) => openFileIntoEditor(apiReadFileWrapper, p, setPath),
		onClearCurrent: () => {
			pathLabel.innerText = "";
			localStorage.removeItem(`last:${containerId}`);
			fileTabs.update?.();
		},
	});
	refreshTreeBtn.addEventListener("click", async () => {
		await ft.refresh();
		await hydrateRun();
		fileTabs.update?.();
	});

	setupUploads({
		api,
		onDone: async () => {
			await ft.refresh();
			await hydrateRun();
			fileTabs.update?.();
		},
		fileTreeEl: fileTreeEl,
	});

	setupTemplates({
		containerId,
		refreshIDE: async () => {
			await ft.refresh();
			await hydrateRun();
			fileTabs.update?.();
		},
	});

	$("#new-folder").addEventListener("click", async () => {
		ft.newFolder(null, "folder");
		fileTabs.update?.();
	});
	$("#new-file").addEventListener("click", async () => {
		ft.newFile(
			null,
			setPath,
			fileActions.saveCurrentFile,
			clearEditor,
			"folder",
		);
		fileTabs.update?.();
	});

	$("#btn-download").addEventListener("click", async () => {
		open(`/api/containers/${containerId}/download_folder/`);
	});

	$("#save-file").addEventListener("click", fileActions.saveCurrentFile);
	/* Run button wired by setupRunButton */

	window.addEventListener("keydown", (e) => {
		const mod = e.ctrlKey || e.metaKey;
		if (mod && e.key.toLowerCase() === "s") {
			e.preventDefault();
			fileActions.saveCurrentFile();
		}
		if (mod && e.key === "Enter") {
			e.preventDefault();
			runCodeBtn.click();
		}
		// Multi-console shortcuts:
		// - Ctrl/Cmd+Shift+N: open new session (sN)
		if (mod && e.shiftKey && e.key.toLowerCase() === "n") {
			e.preventDefault();
			const list = ideStore.get().console.sessions || [];
			let i = 1;
			while (list.includes(`s${i}`)) i++;
			const sid = `s${i}`;
			try {
				wsCtrl?.openSession?.(sid);
			} catch {}
			try {
				consoleApi?.openSession?.(sid, true);
			} catch {}
			try {
				ideStore.actions.console.open(sid, true);
			} catch {}
			try {
				consoleTabs.update?.();
			} catch {}
		}
		// - Ctrl/Cmd+Shift+W: close active session
		if (mod && e.shiftKey && e.key.toLowerCase() === "w") {
			e.preventDefault();
			const sid = ideStore.get().console.active || consoleApi.getActive?.();
			if (sid) {
				try {
					wsCtrl?.closeSession?.(sid);
				} catch {}
				try {
					consoleApi?.closeSession?.(sid);
				} catch {}
				try {
					ideStore.actions.console.close(sid);
				} catch {}
				try {
					consoleTabs.update?.();
				} catch {}
			}
		}
	});

	fileTreeEl.addEventListener("finder-action", async (e) =>
		ft.finderAction(
			e,
			async (path) => {
				await openFileIntoEditor(apiReadFileWrapper, path, setPath);
				fileTabs.update?.();
			},
			setPath,
			clearEditor,
			fileActions.saveCurrentFile,
			ideStore.get().files?.active,
		),
	);

	fileTreeEl.addEventListener("dragover", (e) => e.preventDefault());

	await hydrateRun();
	const lastPath = localStorage.getItem(`last:${containerId}`);
	if (lastPath) await tryOpen(lastPath);
	else await tryOpen("/app/readme.txt");
	fileTabs.update?.();
	refreshTreeBtn.click();

	async function tryOpen(p) {
		try {
			await openFileIntoEditor(apiReadFileWrapper, p, setPath);
		} catch (_error) {
			// no-op
		}
	}

	async function hydrateRun() {
		await runCtrl.hydrate();
	}

	// moved: apiReadFileWrapper initialized earlier to avoid race

	window.addEventListener("beforeunload", () => {
		try {
			ws.close(1000, "bye");
		} catch {}
	});

	window.addEventListener("themechange", (ev) => {
		const isDark = ev.detail?.theme === "dark";
		changeTheme(isDark, consoleApi);
		fileTabs.update?.();
		ideStore.actions.setTheme(isDark ? "dark" : "light");
	});

	const github = setupGithubModal({
		wsCtrl,
		refreshIDE: async () => {
			await ft.refresh();
			await hydrateRun();
		},
	});
})();
