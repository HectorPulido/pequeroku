import { makeApi } from "../core/api.js";
import { $, $$ } from "../core/dom.js";
import { installGlobalLoader } from "../core/loader.js";
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

const btnOpenAi = $("#btn-open-ai-modal");
const aiModal = $("#ai-chat");
const btnAiClose = $("#btn-ai-chat-close");

setupHiddableDragabble(containerId);

if (themeToggleBtn) setupThemeToggle(themeToggleBtn);

let consoleApi = null;
let currentFilePath = null;
let runCommand = null;
let ws = null;
let ft;

const fsws = createFSWS({
	containerPk,
	onOpen: async () => {},
	onBroadcast: async (_evt) => {
		try {
			await ft.refresh();
		} catch {}
	},
});

function setPath(p) {
	currentFilePath = p;
	pathLabel.innerText = p;
	localStorage.setItem(`last:${containerId}`, p);
}

function connectWs() {
	ws = createWS(containerId, {
		onOpen: () => {
			consoleApi.write("[connected]\n");
		},
		onMessage: (ev) => {
			try {
				const msg = JSON.parse(ev.data);
				if (msg.type === "output") {
					consoleApi.write(msg.data);
				} else if (msg.type === "clear") {
					consoleApi.clear();
				} else if (msg.type === "info") {
					consoleApi.write(`[info] ${msg.message}`);
				} else if (msg.type === "error") {
					parent.addAlert(msg.message, "error");
				} else if (msg.type === "log") {
					let chunk = String(msg.line ?? "");
					chunk = chunk.replace(/\r(?!\n)/g, "\r\n");
					consoleApi.write(chunk);
				}
			} catch {
				if (ev.data instanceof ArrayBuffer) {
					consoleApi.write(new Uint8Array(ev.data));
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
		onError: () => parent.addAlert("WebSocket error", "error"),
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
			ws.send(data);
		},
	});
	consoleApi.setTheme(getCurrentTheme() === "dark");

	connectWs();

	restartContainerBtn.addEventListener("click", () => {
		try {
			ws?.close();
		} catch {}
		consoleApi.clear();
		connectWs();
	});

	ft = setupFileTree({
		fsws,
		fileTreeEl,
		containerId,
		onOpen: (p) => openFileIntoEditor(apiReadFileWrapper, p, setPath),
	});
	refreshTreeBtn.addEventListener("click", async () => {
		await ft.refresh();
		await hydrateRun();
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

	btnOpenAi.addEventListener("click", () => {
		aiModal.classList.remove("hidden");
	});
	btnAiClose.addEventListener("click", () => aiModal.classList.add("hidden"));

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
		if (runCommand) ws.send(runCommand);
		else
			parent.addAlert(
				"There is no 'run' command in config.json. The button is disabled.",
				"warning",
			);
	});

	window.addEventListener("keydown", (e) => {
		if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
			e.preventDefault();
			saveCurrentFile();
		}
		if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
			e.preventDefault();
			runCodeBtn.click();
		}
	});

	fileTreeEl.addEventListener("finder-action", async (e) =>
		ft.finderAction(
			e,
			async (path) => openFileIntoEditor(apiReadFileWrapper, path, setPath),
			setPath,
			clearEditor,
			saveCurrentFile,
			currentFilePath,
		),
	);

	fileTreeEl.addEventListener("dragover", (e) => e.preventDefault());

	await hydrateRun();
	await tryOpen("/app/readme.txt");
	refreshTreeBtn.click();

	async function tryOpen(p) {
		try {
			// await api(`/read_file/?path=${encodeURIComponent(p)}`);
			await openFileIntoEditor(apiReadFileWrapper, p, setPath);
		} catch (error) {
			console.log(error);
		}
	}

	// await tryOpen("/app/readme.txt");

	async function hydrateRun() {
		runCommand = await loadRunConfig(apiReadFileWrapper);
		runCodeBtn.disabled = !runCommand;
	}

	// === "API-like" wrapper so editor.js remains unchanged but reads via WS ===
	async function apiReadFileWrapper(url) {
		const qs = new URLSearchParams(url.split("?")[1] || "");
		const path = qs.get("path");
		const data = await fsws.call("read_file", { path });
		if (typeof data.rev === "number") fsws.revs.set(path, data.rev);
		return { content: data.content ?? "" };
	}

	async function saveCurrentFile() {
		if (!currentFilePath) {
			parent.addAlert("Open a file first", "error");
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
			parent.addAlert(`File ${currentFilePath} saved`, "success");
			if (currentFilePath === "/app/config.json") await hydrateRun();
		} catch (e) {
			if (String(e.message).includes("conflict")) {
				const cur = fsws.revs.get(currentFilePath) || 0;
				parent.addAlert(
					`Conflict saving saving current Rev ${cur}. Reload...`,
					"error",
				);
				await openFileIntoEditor(apiReadFileWrapper, currentFilePath, setPath);
			} else {
				parent.addAlert(e.message || String(e), "error");
			}
		}

		// try {
		//   console.log("A")
		//   await openFileIntoEditor(apiReadFileWrapper, "/app/readme.txt", setPath);
		// 	console.log("B")
		// }catch (error ) {
		//   console.log(error)
		// }
	}

	window.addEventListener("beforeunload", () => {
		try {
			ws.close(1000, "bye");
		} catch {}
	});

	window.addEventListener("themechange", (ev) => {
		const isDark = ev.detail?.theme === "dark";
		changeTheme(isDark, consoleApi);
	});

	btnCloneRepo.addEventListener("click", () => {
		$("#github-modal").classList.remove("hidden");
	});
	btnCloseCloneRepo.addEventListener("click", () => {
		$("#github-modal").classList.add("hidden");
	});
	btnSubmitCloneRepo.addEventListener("click", async () => {
		const repo = $("#url_git").value;
		const base_path = $("#base_path").value;
		const cmd = `bash -lc 'set -euo pipefail; REPO="${repo}"; X="${base_path}"; TMP="$(mktemp -d)"; git clone "$REPO" "$TMP/repo"; sudo mkdir -p /app; find /app -mindepth 1 -not -name "readme.txt" -not -name "config.json" -exec rm -rf {} +; SRC="$TMP/repo"; [ "\${X:-/}" != "/" ] && SRC="$TMP/repo/\${X#/}"; shopt -s dotglob nullglob; mv "$SRC"/* /app/; rm -rf "$TMP"'`;

		if (ws != null) {
			ws.send(cmd);
			await sleep(5000);
			await ft.refresh();
			await hydrateRun();
			btnCloseCloneRepo.click();
		}
	});
})();
