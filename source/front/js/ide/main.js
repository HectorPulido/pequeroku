import { makeApi } from "../core/api.js";
import { getCSRF } from "../core/csrf.js";
import { $, $$ } from "../core/dom.js";
import { installGlobalLoader } from "../core/loader.js";
import {
	applyTheme,
	getCurrentTheme,
	setupThemeToggle,
} from "../core/themes.js";
import { setupConsole } from "./console.js";
import {
	openFile as openFileIntoEditor,
	clearEditor,
	getEditorValue,
	changeTheme,
	loadMonaco,
} from "./editor.js";
import { setupFileTree } from "./files.js";
import { loadRunConfig } from "./runConfig.js";
import { setupUploads } from "./uploads.js";
import { createWS } from "./websockets.js";
import { hideHeader } from "../core/utils.js";
import { setupHiddableDragabble } from "./hiddableDraggable.js";

installGlobalLoader();
applyTheme();
loadMonaco(getCurrentTheme() === "dark");
hideHeader();

// ====== CONFIG ======
const urlParams = new URLSearchParams(window.location.search);
const containerId = urlParams.get("containerId");
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

const btnOpenAi = $("#btn-open-ai-modal");
const aiModal = $("#ai-modal");
const btnAiClose = $("#btn-ai-close");
const aiInput = $("#ai-input");
const btnAiGenerate = $("#btn-ai-generate");
const aiCredits = $("#ai-credits");

setupHiddableDragabble(containerId);

if (themeToggleBtn) setupThemeToggle(themeToggleBtn);

// ====== State ======
let consoleApi = null;
let currentFilePath = null;
let runCommand = null;
function setPath(p) {
	currentFilePath = p;
	pathLabel.innerText = p;
	localStorage.setItem(`last:${containerId}`, p);
}

let ws = null;

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

// ====== Initial ======
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

	const ft = setupFileTree({
		api,
		fileTreeEl,
		onOpen: (p) => openFileIntoEditor(api, p, setPath),
	});
	refreshTreeBtn.addEventListener("click", async () => {
		await ft.refresh();
		await hydrateRun();
	});

	// Uploads
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

	// Setup AI
	const { setupAi } = await import("./ai.js");
	setupAi({
		openBtn: btnOpenAi,
		modalEl: aiModal,
		closeBtn: btnAiClose,
		inputEl: aiInput,
		generateBtn: btnAiGenerate,
		creditsEl: aiCredits,
		containerId,
		onApplied: async () => {
			await ft.refresh();
			await hydrateRun();
		},
	});

	// Templates
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
		ft.newFolder(null);
	});
	newFileBtn.addEventListener("click", async () => {
		ft.newFile(null, setPath, saveCurrentFile, clearEditor);
	});

	// Guardar / Run
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

	// Atajos
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
			openFileIntoEditor,
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

	async function hydrateRun() {
		runCommand = await loadRunConfig(api);
		runCodeBtn.disabled = !runCommand;
	}
	async function tryOpen(p) {
		try {
			await api(`/read_file/?path=${encodeURIComponent(p)}`);
			await openFileIntoEditor(api, p, setPath);
		} catch {

		}
	}

	async function saveCurrentFile() {
		if (!currentFilePath) {
			parent.addAlert("Open a file first", "error");
			return;
		}
		const content = getEditorValue();
		await api("/write_file/", {
			method: "POST",
			body: JSON.stringify({ path: currentFilePath, content: content }),
		});
		parent.addAlert(`File ${currentFilePath} saved`, "success");
		if (currentFilePath === "/app/config.json") await hydrateRun();
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
})();
