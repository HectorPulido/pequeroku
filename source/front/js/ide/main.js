import { notifyAlert } from "../core/alerts.js";
import { makeApi } from "../core/api.js";
import { $, $$ } from "../core/dom.js";
import { installGlobalLoader } from "../core/loader.js";
import { bindModal } from "../core/modals.js";
import {
	applyTheme,
	getCurrentTheme,
	setupThemeToggle,
} from "../core/themes.js";
import { hideHeader, sleep } from "../core/utils.js";
import { setupConsole } from "./console.js";
import {
	changeTheme,
	clearEditor,
	getEditorValue,
	loadMonaco,
	mobileConfig,
	openFile as openFileIntoEditor,
} from "./editor.js";
import { setupFileTree } from "./files.js";
import { createFSWS } from "./fs-ws.js";
import { setupHiddableDragabble } from "./hiddableDraggable.js";
import { loadRunConfig } from "./runConfig.js";
import { setupUploads } from "./uploads.js";
import { createWS } from "./websockets.js";

installGlobalLoader();
applyTheme();
loadMonaco(getCurrentTheme() === "dark");
hideHeader();

// ====== CONFIG ======
const urlParams = new URLSearchParams(window.location.search);
const containerId = urlParams.get("containerId");
const containerPk = parseInt(containerId, 10);
const api = makeApi(`/api/containers/${containerId}`);

// ====== DOM refs ======
const themeToggleBtn = $("#theme-toggle");
const pathLabel = $("#current_path_label");
const refreshTreeBtn = $("#refresh-tree");
const fileTreeEl = $("#file-tree");
const sendCMDBtn = $("#send-cmd");
const consoleCMD = $("#console-cmd");
const restartContainerBtn = $("#restart-container");
const runCodeBtn = $("#run-code");
const saveFileBtn = $("#save-file");
const consoleEl = $("#console-log");
const newFolderBtn = $("#new-folder");
const newFileBtn = $("#new-file");
const btnDownloadBtn = $("#btn-download");
const btnOpenSession = $("#btn-open-session");
const btnCloseSession = $("#btn-close-session");
const consoleTabsEl = $("#console-tabs");
const fileTabsEl = $("#file-tabs");

const btnOpenUpload = $("#btn-open-upload-modal");
const uploadModal = $("#upload-modal");
const btnUploadClose = $("#btn-upload-close");
const input = $("#file-input");
const btnUpload = $("#btn-upload");

const btnOpenTemplates = $("#btn-open-templates-modal");
const templatesModal = $("#templates-modal");
const btnTemplatesClose = $("#btn-templates-close");
const tplListEl = $("#tpl-list");
const tplDestEl = $("#tpl-dest");
const tplCleanEl = $("#tpl-clean");

const btnCloneRepo = $("#btn-clone-repo");
const btnCloseCloneRepo = $("#btn-github-close");
const btnSubmitCloneRepo = $("#btn-github");

await setupHiddableDragabble(containerId, async (isMobile) => {
	await mobileConfig(isMobile);
});

if (themeToggleBtn) setupThemeToggle(themeToggleBtn);

let apiReadFileWrapper = null;
let consoleApi = null;
let currentFilePath = null;
let runCommand = null;
let ws = null;
window._sessionList = [];
window._activeSid = null;
window._openFiles = [];
window._activeFile = null;

function updateTabs() {
	const el = consoleTabsEl;
	if (!el) return;
	const list = window._sessionList || [];
	const active = window._activeSid || null;
	if (!list.length) {
		el.innerHTML = "";
		return;
	}
	el.innerHTML = list
		.map(
			(sid) =>
				`<button class="console-tab" role="tab" aria-selected="${
					sid === active
				}" data-sid="${sid}" title="${sid}">${sid}<span class="icon" data-close="${sid}">×</span></button>`,
		)
		.join("");
}

if (consoleTabsEl) {
	consoleTabsEl.addEventListener("click", (e) => {
		const closeEl = e.target.closest("[data-close]");
		if (closeEl) {
			const sid = closeEl.getAttribute("data-close");
			try {
				ws?.send({ control: "close", sid });
			} catch {}
			e.stopPropagation();
			return;
		}
		const tab = e.target.closest("[data-sid]");
		if (tab) {
			const sid = tab.getAttribute("data-sid");
			if (sid && sid !== window._activeSid) {
				try {
					ws?.send({ control: "focus", sid });
				} catch {}
			}
		}
	});
}
function updateFileTabs() {
	const el = fileTabsEl;
	if (!el) return;
	const files = window._openFiles || [];
	const active = window._activeFile || currentFilePath || null;
	if (!files.length) {
		el.innerHTML = "";
		return;
	}
	el.innerHTML = files
		.map((fp) => {
			const name = fp.replace("/app/", "");
			return `<button class="file-tab" role="tab" aria-selected="${
				fp === active
			}" data-path="${fp}" title="${fp}">${name}<span class="icon" data-close-file="${fp}">×</span></button>`;
		})
		.join("");
}
if (fileTabsEl) {
	fileTabsEl.addEventListener("click", async (e) => {
		const closeEl = e.target.closest("[data-close-file]");
		if (closeEl) {
			const path = closeEl.getAttribute("data-close-file");
			const files = window._openFiles || [];
			const idx = Math.max(0, files.indexOf(path));
			window._openFiles = files.filter((x) => x !== path);
			if ((window._activeFile || currentFilePath) === path) {
				window._activeFile = null;
				const remaining = window._openFiles || [];
				const nextIdx = idx < remaining.length ? idx : idx - 1;
				const next = nextIdx >= 0 ? remaining[nextIdx] : null;
				if (next) {
					try {
						await openFileIntoEditor(apiReadFileWrapper, next, setPath);
					} catch {}
				} else {
					try {
						clearEditor();
					} catch {}
					currentFilePath = null;
					pathLabel.innerText = "";
					localStorage.removeItem(`last:${containerId}`);
					updateFileTabs();
				}
			} else {
				updateFileTabs();
			}
			e.stopPropagation();
			return;
		}
		const tab = e.target.closest("[data-path]");
		if (tab) {
			const path = tab.getAttribute("data-path");
			if (path) {
				await openFileIntoEditor(apiReadFileWrapper, path, setPath);
			}
		}
	});
}
let lastBytesSid = null;
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
			updateFileTabs();
		} catch {}
	},
});

// === "API-like" wrapper so editor.js remains unchanged but reads via WS ===
apiReadFileWrapper = async (url) => {
	const qs = new URLSearchParams(url.split("?")[1] || "");
	const path = qs.get("path");
	const data = await fsws.call("read_file", { path });
	if (typeof data.rev === "number") fsws.revs.set(path, data.rev);
	return { content: data.content ?? "" };
};

function setPath(p) {
	currentFilePath = p;
	pathLabel.innerText = p;
	localStorage.setItem(`last:${containerId}`, p);
	// Update file tabs (stable order: append only when new)
	try {
		const cur = window._openFiles || [];
		if (!cur.includes(p)) {
			window._openFiles = [...cur, p];
		}
		window._activeFile = p;
		updateFileTabs();
	} catch {}
}

function connectWs() {
	ws = createWS(containerId, {
		onOpen: () => {
			// Reset local sessions; the server will resend session list
			const sids = consoleApi.listSessions?.() || [];
			// biome-ignore lint/suspicious/useIterableCallbackReturn: This is correct
			sids.forEach((sid) => consoleApi.closeSession?.(sid));
			window._sessionList = [];
			window._activeSid = null;
			updateTabs();
			consoleApi.addLine?.("[connected]");
		},
		onMessage: (ev) => {
			// Multi-console protocol:
			// - JSON: {type:"stream"| "stream-bytes" | "info" | "error", sid?, ...}
			// - After "stream-bytes", a binary frame follows for that sid
			try {
				const msg = JSON.parse(ev.data);
				if (msg && typeof msg === "object") {
					if (msg.type === "stream") {
						const sid = msg.sid || consoleApi.getActive?.();
						const payload = typeof msg.payload === "string" ? msg.payload : "";
						consoleApi.write(payload, sid);
						return;
					}
					if (msg.type === "stream-bytes") {
						lastBytesSid = msg.sid || consoleApi.getActive?.();
						return;
					}
					if (msg.type === "info") {
						// Bootstrap connected info or session events
						if (msg.message === "Connected") {
							const sessions = Array.isArray(msg.sessions) ? msg.sessions : [];
							const active = msg.active || sessions[0] || "s1";
							// biome-ignore lint/suspicious/useIterableCallbackReturn: This is correct
							sessions.forEach((sid) => consoleApi.openSession?.(sid, false));
							consoleApi.focusSession?.(active);
							window._sessionList = sessions.slice();
							window._activeSid = active;
							consoleApi.addLine?.(
								`[info] Connected. Sessions: ${sessions.join(", ") || "none"}, active: ${active}`,
								active,
							);
							updateTabs();
							return;
						}
						if (msg.message === "session-opened") {
							const makeActive = msg.active ? msg.active === msg.sid : true;
							consoleApi.openSession?.(msg.sid, !!makeActive);
							window._sessionList = Array.from(
								new Set([...(window._sessionList || []), msg.sid]),
							);
							if (makeActive) {
								window._activeSid = msg.sid;
								consoleApi.focusSession?.(msg.sid);
							}
							updateTabs();
							return;
						}
						if (msg.message === "session-closed") {
							consoleApi.closeSession?.(msg.sid);
							window._sessionList = (window._sessionList || []).filter(
								(x) => x !== msg.sid,
							);
							if (window._activeSid === msg.sid) {
								window._activeSid = window._sessionList[0] || null;
							}
							return;
						}
						if (msg.message === "session-focused") {
							consoleApi.focusSession?.(msg.sid);
							window._activeSid = msg.sid;
							return;
						}
						// Generic info, route to sid if provided
						const sid = msg.sid || consoleApi.getActive?.();
						consoleApi.addLine?.(`[info] ${msg.message ?? ""}`, sid);
						return;
					}
					if (msg.type === "error") {
						notifyAlert(msg.message || "Unknown error", "error");
						return;
					}
				}
				// Fallback: treat as text line
				let text = String(ev.data || "");
				text = text.replace(/\r(?!\n)/g, "\r\n");
				consoleApi.write(text);
			} catch {
				if (ev.data instanceof ArrayBuffer) {
					const targetSid = lastBytesSid || consoleApi.getActive?.();
					lastBytesSid = null;
					consoleApi.write(new Uint8Array(ev.data), targetSid);
				} else {
					let text = String(ev.data || "");
					text = text.replace(/\r(?!\n)/g, "\r\n");
					consoleApi.write(text);
				}
			}
		},
		onClose: () => {
			consoleApi.write("[disconnected]\n");
		},
		onError: () => notifyAlert("WebSocket error", "error"),
	});
}

(async () => {
	consoleApi = setupConsole({
		consoleEl,
		sendBtn: sendCMDBtn,
		inputEl: consoleCMD,
		ctrlButtons: $$(".btn-send"),
		onSend: (data) => {
			if (!ws) return;
			const active = consoleApi.getActive?.() || null;
			if (data === "clear") {
				consoleApi.clear(active);
				return;
			}
			if (data === "ctrlc") data = "\u0003";
			else if (data === "ctrld") data = "\u0004";
			const payload = active ? { sid: active, data } : { data };
			ws.send(payload);
		},
	});
	// Hook to sync tabs with console sessions lifecycle
	const __open = consoleApi.openSession?.bind(consoleApi);
	if (__open) {
		consoleApi.openSession = (sid, makeActive) => {
			__open(sid, makeActive);
			if (sid && !(window._sessionList || []).includes(sid)) {
				window._sessionList = Array.from(
					new Set([...(window._sessionList || []), sid]),
				);
			}
			if (makeActive) window._activeSid = sid;
			updateTabs();

			setTimeout(() => {
				consoleApi.setTheme(getCurrentTheme() === "dark");
			}, 50);
		};
	}
	const __close = consoleApi.closeSession?.bind(consoleApi);
	if (__close) {
		consoleApi.closeSession = (sid) => {
			__close(sid);
			window._sessionList = (window._sessionList || []).filter(
				(x) => x !== sid,
			);
			if (window._activeSid === sid)
				window._activeSid = (window._sessionList || [])[0] || null;
			updateTabs();
		};
	}
	const __focus = consoleApi.focusSession?.bind(consoleApi);
	if (__focus) {
		consoleApi.focusSession = (sid) => {
			__focus(sid);
			window._activeSid = sid;
			updateTabs();
		};
	}

	connectWs();

	// Wire up multi-console session controls
	if (btnOpenSession) {
		btnOpenSession.addEventListener("click", () => {
			const list = window._sessionList || [];
			let i = 1;
			while (list.includes(`s${i}`)) i++;
			const sid = `s${i}`;
			try {
				ws?.send({ control: "open", sid });
			} catch {}
			// Optimistically update local state
			window._sessionList = Array.from(
				new Set([...(window._sessionList || []), sid]),
			);
			window._activeSid = sid;
			updateTabs();
		});
	}
	if (btnCloseSession) {
		btnCloseSession.addEventListener("click", () => {
			const sid = window._activeSid || null;
			if (sid) {
				try {
					ws?.send({ control: "close", sid });
				} catch {}
				// Optimistically update local state
				window._sessionList = (window._sessionList || []).filter(
					(x) => x !== sid,
				);
				if (window._activeSid === sid)
					window._activeSid = (window._sessionList || [])[0] || null;
				updateTabs();
			}
		});
	}
	// Prev/Next session buttons removed in favor of tab UI (console tabs)

	restartContainerBtn.addEventListener("click", () => {
		try {
			ws?.close();
		} catch {}
		consoleApi.clear();
		connectWs();
		updateFileTabs();
	});

	ft = setupFileTree({
		fsws,
		fileTreeEl,
		containerId,
		onOpen: (p) => openFileIntoEditor(apiReadFileWrapper, p, setPath),
		onClearCurrent: () => {
			pathLabel.innerText = "";
			localStorage.removeItem(`last:${containerId}`);
			updateFileTabs();
		},
	});
	refreshTreeBtn.addEventListener("click", async () => {
		await ft.refresh();
		await hydrateRun();
		updateFileTabs();
	});

	setupUploads({
		api,
		openBtn: btnOpenUpload,
		modalEl: uploadModal,
		closeBtn: btnUploadClose,
		inputEl: input,
		uploadBtn: btnUpload,
		onDone: async () => {
			await ft.refresh();
			await hydrateRun();
		},
		fileTreeEl: fileTreeEl,
	});

	const { setupTemplates } = await import("./templates.js");
	setupTemplates({
		openBtn: btnOpenTemplates,
		modalEl: templatesModal,
		closeBtn: btnTemplatesClose,
		listEl: tplListEl,
		destInput: tplDestEl,
		cleanInput: tplCleanEl,
		containerId,
		refreshIDE: async () => {
			await ft.refresh();
			await hydrateRun();
		},
	});

	newFolderBtn.addEventListener("click", async () => {
		ft.newFolder(null, "folder");
	});
	newFileBtn.addEventListener("click", async () => {
		ft.newFile(null, setPath, saveCurrentFile, clearEditor, "folder");
	});

	btnDownloadBtn.addEventListener("click", async () => {
		open(`/api/containers/${containerId}/download_folder/`);
	});

	saveFileBtn.addEventListener("click", saveCurrentFile);
	runCodeBtn.addEventListener("click", async () => {
		await saveCurrentFile();
		if (runCommand) ws.send({ data: runCommand });
		else
			notifyAlert(
				"There is no 'run' command in config.json. The button is disabled.",
				"warning",
			);
	});

	window.addEventListener("keydown", (e) => {
		const mod = e.ctrlKey || e.metaKey;
		if (mod && e.key.toLowerCase() === "s") {
			e.preventDefault();
			saveCurrentFile();
		}
		if (mod && e.key === "Enter") {
			e.preventDefault();
			runCodeBtn.click();
		}
		// Multi-console shortcuts:
		// - Ctrl/Cmd+Shift+N: open new session (sN)
		if (mod && e.shiftKey && e.key.toLowerCase() === "n") {
			e.preventDefault();
			const list = consoleApi.listSessions?.() || [];
			let i = 1;
			while (list.includes(`s${i}`)) i++;
			const sid = `s${i}`;
			ws?.send({ control: "open", sid });
		}
		// - Ctrl/Cmd+Shift+W: close active session
		if (mod && e.shiftKey && e.key.toLowerCase() === "w") {
			e.preventDefault();
			const sid = consoleApi.getActive?.();
			if (sid) ws?.send({ control: "close", sid });
		}
	});

	fileTreeEl.addEventListener("finder-action", async (e) =>
		ft.finderAction(
			e,
			async (path) => {
				await openFileIntoEditor(apiReadFileWrapper, path, setPath);
				updateFileTabs();
			},
			setPath,
			clearEditor,
			saveCurrentFile,
			currentFilePath,
		),
	);

	fileTreeEl.addEventListener("dragover", (e) => e.preventDefault());

	await hydrateRun();
	const lastPath = localStorage.getItem(`last:${containerId}`);
	if (lastPath) await tryOpen(lastPath);
	else await tryOpen("/app/readme.txt");
	updateFileTabs();
	refreshTreeBtn.click();

	async function tryOpen(p) {
		try {
			await openFileIntoEditor(apiReadFileWrapper, p, setPath);
		} catch (error) {
			console.log(error);
		}
	}

	async function hydrateRun() {
		runCommand = await loadRunConfig(apiReadFileWrapper);
		runCodeBtn.disabled = !runCommand;
	}

	// moved: apiReadFileWrapper initialized earlier to avoid race

	async function saveCurrentFile() {
		if (!currentFilePath) {
			notifyAlert("Open a file first", "error");
			return;
		}
		const content = getEditorValue();
		const prev = fsws.revs.get(currentFilePath) || 0;
		try {
			const res = await fsws.call("write_file", {
				path: currentFilePath,
				prev_rev: prev,
				content,
			});
			const nextRev = typeof res?.rev === "number" ? res.rev : prev + 1;
			fsws.revs.set(currentFilePath, nextRev);
			notifyAlert(`File ${currentFilePath} saved`, "success");
			if (currentFilePath === "/app/config.json") await hydrateRun();
		} catch (e) {
			if (String(e.message).includes("conflict")) {
				const cur = fsws.revs.get(currentFilePath) || 0;
				notifyAlert(
					`Conflict saving saving current Rev ${cur}. Reload...`,
					"error",
				);
				await openFileIntoEditor(apiReadFileWrapper, currentFilePath, setPath);
			} else {
				notifyAlert(e.message || String(e), "error");
			}
		}
	}

	window.addEventListener("beforeunload", () => {
		try {
			ws.close(1000, "bye");
		} catch {}
	});

	window.addEventListener("themechange", (ev) => {
		const isDark = ev.detail?.theme === "dark";
		changeTheme(isDark, consoleApi);
		updateFileTabs();
	});

	const githubModal = $("#github-modal");
	const githubTitleEl = githubModal?.querySelector(".upload-header > span");
	const githubModalCtrl = bindModal(
		githubModal,
		btnCloneRepo,
		btnCloseCloneRepo,
		{
			titleEl: githubTitleEl,
			defaultTitle: githubTitleEl?.textContent || "Clone from Github",
			initialFocus: () => $("#url_git"),
		},
	);
	btnSubmitCloneRepo.addEventListener("click", async () => {
		const repo = $("#url_git").value;
		const base_path = $("#base_path").value;
		const cmd = `bash -lc 'set -euo pipefail; REPO="${repo}"; X="${base_path}"; TMP="$(mktemp -d)"; git clone "$REPO" "$TMP/repo"; sudo mkdir -p /app; find /app -mindepth 1 -not -name "readme.txt" -not -name "config.json" -exec rm -rf {} +; SRC="$TMP/repo"; [ "\${X:-/}" != "/" ] && SRC="$TMP/repo/\${X#/}"; shopt -s dotglob nullglob; mv "$SRC"/* /app/; rm -rf "$TMP"'`;

		if (ws != null) {
			ws.send({ data: cmd });
			await sleep(5000);
			await ft.refresh();
			await hydrateRun();
			githubModalCtrl.close();
		}
	});
})();
