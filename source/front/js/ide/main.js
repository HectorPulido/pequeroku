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

function clamp(n, min, max) {
	return Math.max(min, Math.min(max, n));
}

installGlobalLoader();
applyTheme();
loadMonaco(getCurrentTheme() === "dark");

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

const toggleSidebarBtn = $("#toggle-sidebar");
const toggleSidebarBtn2 = $("#toggle-sidebar-2");
const toggleConsoleBtn = $("#toggle-console");
const consoleArea = $("#console-area");
const editorModal = $("#editor-modal");

const sidebarEl = $("#sidebar");
const splitterV = $("#splitter-v");
const splitterH = $("#splitter-h");

const IS_MOBILE = matchMedia("(max-width: 768px)").matches;
const LS_SIDEBAR_KEY = `ide:${containerId}:sidebar`;
const LS_CONSOLE_KEY = `ide:${containerId}:console`;

// Drag and drop files and console
const LS_CONSOLE_SIZE_KEY = `ide:${containerId}:console:px`;
const LS_SIDEBAR_SIZE_KEY = `ide:${containerId}:sidebar:px`;

const savedW = parseInt(localStorage.getItem(LS_SIDEBAR_SIZE_KEY) || "280", 10);
const savedH = parseInt(localStorage.getItem(LS_CONSOLE_SIZE_KEY) || "260", 10);

editorModal.style.gridTemplateColumns = `${savedW}px 6px 1fr`;
consoleArea.style.height = `${savedH}px`;

// Vertical splitter (files)
splitterV.addEventListener("mousedown", (e) => {
	e.preventDefault();
	const startX = e.clientX;
	const startW = sidebarEl.getBoundingClientRect().width;
	const onMove = (ev) => {
		const w = Math.max(20, Math.min(600, startW + (ev.clientX - startX)));
		editorModal.style.gridTemplateColumns = `${w}px 6px 1fr`;
	};
	const onUp = () => {
		const w = sidebarEl.getBoundingClientRect().width;
		localStorage.setItem(LS_SIDEBAR_SIZE_KEY, String(w));
		window.removeEventListener("mousemove", onMove);
		window.removeEventListener("mouseup", onUp);
	};
	window.addEventListener("mousemove", onMove);
	window.addEventListener("mouseup", onUp);
});

// Horizontal splitter (console)
splitterH.addEventListener("mousedown", (e) => {
	e.preventDefault();
	const containerRect = editorModal.getBoundingClientRect();
	const containerBottom = containerRect.bottom; // ancla estable
	const resizerHeight = splitterH.getBoundingClientRect().height || 0;

	const onMove = (ev) => {
		const raw = containerBottom - ev.clientY - resizerHeight;
		const h = clamp(raw, 60, window.innerHeight);
		consoleArea.style.height = `${h}px`;
		try {
			consoleApi?.fit?.();
		} catch {}
	};
	const onUp = () => {
		const h = consoleArea.getBoundingClientRect().height;
		localStorage.setItem(LS_CONSOLE_SIZE_KEY, String(h));
		window.removeEventListener("mousemove", onMove);
		window.removeEventListener("mouseup", onUp);
	};
	window.addEventListener("mousemove", onMove);
	window.addEventListener("mouseup", onUp);
});

// Colapse files
function applySidebarState(state) {
	editorModal.classList.toggle("sidebar-collapsed", state !== "open");
	editorModal.classList.toggle("sidebar-open", state === "open");
}
function applyConsoleState(state) {
	consoleArea.classList.toggle("collapsed", state !== "open");
}

function getInitialSidebarState() {
	const saved = localStorage.getItem(LS_SIDEBAR_KEY);
	if (saved) return saved;
	return IS_MOBILE ? "collapsed" : "open";
}
function getInitialConsoleState() {
	const saved = localStorage.getItem(LS_CONSOLE_KEY);
	if (saved) return saved;
	return IS_MOBILE ? "collapsed" : "open";
}

function toggleSidebar() {
	const _collapsed =
		editorModal.classList.contains("sidebar-open") &&
		!editorModal.classList.contains("sidebar-collapsed");
	const next = _collapsed ? "collapsed" : "open";
	localStorage.setItem(LS_SIDEBAR_KEY, next);
	applySidebarState(next);
}

function toggleConsole() {
	const _collapsed = consoleArea.classList.contains("collapsed");
	const next = _collapsed ? "open" : "collapsed";
	localStorage.setItem(LS_CONSOLE_KEY, next);
	applyConsoleState(next);
	try {
		consoleApi?.fit?.();
	} catch {}
}

// ====== INIT ======
applySidebarState(getInitialSidebarState());
applyConsoleState(getInitialConsoleState());

// ====== Listeners ======
toggleSidebarBtn2.addEventListener("click", toggleSidebar);
toggleSidebarBtn.addEventListener("click", toggleSidebar);
toggleConsoleBtn.addEventListener("click", toggleConsole);
if (themeToggleBtn) setupThemeToggle(themeToggleBtn); // ⬅️

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
			consoleApi.addLine("[connected]");
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
			consoleApi.addLine("[disconnected]");
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

	// Crear carpeta/archivo
	newFolderBtn.addEventListener("click", async () => {
		const name = prompt("Folder name:");
		if (!name) return;
		await api("/create_dir/", {
			method: "POST",
			body: JSON.stringify({ path: `/app/${name}` }),
		});
		refreshTreeBtn.click();
	});
	newFileBtn.addEventListener("click", async () => {
		const name = prompt("File name:");
		if (!name) return;
		setPath(`/app/${name}`);
		clearEditor();
		await saveCurrentFile();
		refreshTreeBtn.click();
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

	fileTreeEl.addEventListener("finder-action", async (e) => {
		const { action, path, type } = e.detail || {};
		if (!action || !path) return;
		try {
			if (action === "open") {
				if (type === "directory") return; // opcional: expandir
				await openFileIntoEditor(api, path, setPath);
			}
			if (action === "delete") {
				if (!confirm(`Delete "${path}"?`)) return;
				await api("/delete_path/", {
					method: "POST",
					body: JSON.stringify({ path }),
				});
				parent.addAlert(`Deleted: ${path}`, "success");
				await ft.refresh();
				if (currentFilePath === path) {
					currentFilePath = null;
					clearEditor();
					pathLabel.innerText = "";
				}
			}
			if (action === "rename") {
				const base = path.split("/").pop();
				const name = prompt("New name:", base);
				if (!name || name === base) return;
				const new_path = path.replace(/\/[^/]+$/, `/${name}`);
				await api("/move_path/", {
					method: "POST",
					body: JSON.stringify({ src: path, dest: new_path }),
				});
				parent.addAlert(`Renamed to: ${new_path}`, "success");
				await ft.refresh();
				if (currentFilePath === path) {
					await openFileIntoEditor(api, new_path, setPath);
				}
			}
			if (action === "new-file") {
				const dir = type === "directory" ? path : path.replace(/\/[^/]+$/, "");
				const name = prompt("File name:");
				if (!name) return;
				const newp = `${dir.replace(/\/$/, "")}/${name}`;
				setPath(newp);
				clearEditor();
				await saveCurrentFile();
				await ft.refresh();
			}
			if (action === "new-folder") {
				const dir = type === "directory" ? path : path.replace(/\/[^/]+$/, "");
				const name = prompt("Folder name:");
				if (!name) return;
				await api("/create_dir/", {
					method: "POST",
					body: JSON.stringify({ path: `${dir.replace(/\/$/, "")}/${name}` }),
				});
				await ft.refresh();
			}
		} catch (err) {
			parent.addAlert(err.message || String(err), "error");
		}
	});

	// DnD directo al árbol
	fileTreeEl.addEventListener("dragover", (e) => e.preventDefault());
	fileTreeEl.addEventListener("drop", async (e) => {
		e.preventDefault();
		const f = e.dataTransfer.files?.[0];
		if (!f) return;
		const form = new FormData();
		form.append("file", f);
		form.append("dest_path", "/app");
		await api(
			"/upload_file/",
			{ headers: { "X-CSRFToken": getCSRF() }, method: "POST", body: form },
			false,
		);
		refreshTreeBtn.click();
	});

	// Carga inicial
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
			/*noop*/
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
