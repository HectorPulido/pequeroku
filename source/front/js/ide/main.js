import { makeApi } from "../core/api.js";
import { getCSRF } from "../core/csrf.js";
import { $, $$ } from "../core/dom.js";
import { installGlobalLoader } from "../core/loader.js";
import { setupConsole } from "./console.js";
import { openFile as openFileIntoEditor } from "./editor.js";
import { setupFileTree } from "./files.js";
import { loadRunConfig } from "./runConfig.js";
import { setupUploads } from "./uploads.js";
import { createWS } from "./websockets.js";

installGlobalLoader();

// ====== CONFIG ======
const urlParams = new URLSearchParams(window.location.search);
const containerId = urlParams.get("containerId");
const api = makeApi(`/api/containers/${containerId}`);

// ====== DOM refs ======
const pathLabel = $("#current_path_label");
const editor = $("#editor");
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

// ====== State ======
let currentFilePath = null;
let runCommand = null;
function setPath(p) {
	currentFilePath = p;
	pathLabel.innerText = p;
	localStorage.setItem(`last:${containerId}`, p);
}

// ====== Initial ======
(async () => {
	// biome-ignore lint/suspicious/useIterableCallbackReturn: This is correct
	$$(".btn-send").forEach((btn) =>
		btn.addEventListener("click", () => {
			ws.send(btn.getAttribute("param"));
		}),
	);

	let wsRef = null;

	const consoleApi = setupConsole({
		consoleEl,
		sendBtn: sendCMDBtn,
		inputEl: consoleCMD,
		ctrlButtons: $$(".btn-send"),
		onSend: (data) => {
			if (!ws) return;
			const UMBRAL = 512 * 1024;
			const sendRaw = () => ws.send(data);
			if (ws.bufferedAmount > UMBRAL) {
				const t = setInterval(() => {
					if (ws.bufferedAmount <= UMBRAL) {
						clearInterval(t);
						sendRaw();
					}
				}, 10);
			} else {
				sendRaw();
			}
		},
		onResize: ({ cols, rows }) => {
			wsRef?.send(JSON.stringify({ type: "resize", cols, rows }));
		},
	});

	const ws = createWS(containerId, {
		onOpen: () => {
			wsRef = ws;
			consoleApi.addLine("[connected]");
			setTimeout(() => {
				try {
					consoleApi.fit();
					consoleApi.resizeToServer();
				} catch {}
			}, 0);
		},
		onMessage: (ev) => {
			try {
				const msg = JSON.parse(ev.data);
				if (msg.type === "output") {
					consoleApi.write(msg.data);
				} else if (msg.type === "clear") {
					consoleApi.clear();
				} else if (msg.type === "info") {
					consoleApi.addLine(`[info] ${msg.message}`);
				} else if (msg.type === "error") {
					parent.addAlert(msg.message, "error");
				} else if (msg.type === "log") {
					consoleApi.addLine(msg.line);
				}
			} catch {
				if (ev.data instanceof ArrayBuffer) {
					consoleApi.write(new Uint8Array(ev.data));
				} else {
					consoleApi.write(String(ev.data || ""));
				}
			}
		},
		onClose: () => {
			consoleApi.addLine("[disconnected]");
			wsRef = null;
		},
		onError: () => parent.addAlert("WebSocket error", "error"),
	});

	consoleApi.onSend = Object.assign(() => {}, { ws });

	// restart container
	restartContainerBtn.addEventListener("click", async () => {
		await api("/restart_container/", { method: "POST" });
	});

	const ft = setupFileTree({
		api,
		fileTreeEl,
		onOpen: (p) => openFileIntoEditor(api, editor, p, setPath),
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
		editor.value = "";
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
	await waitMonaco();
	await hydrateRun();
	await tryOpen("/app/readme.txt");
	refreshTreeBtn.click();

	async function waitMonaco() {
		const m = await import("./editor.js");
		return await m.waitForMonacoReady(editor);
	}
	async function hydrateRun() {
		runCommand = await loadRunConfig(api);
		runCodeBtn.disabled = !runCommand;
	}
	async function tryOpen(p) {
		try {
			await api(`/read_file/?path=${encodeURIComponent(p)}`);
			await openFileIntoEditor(api, editor, p, setPath);
		} catch {
			/*noop*/
		}
	}

	async function saveCurrentFile() {
		if (!currentFilePath) {
			parent.addAlert("Open a file first", "error");
			return;
		}
		const content = editor.value;
		await api("/write_file/", {
			method: "POST",
			body: JSON.stringify({ path: currentFilePath, content }),
		});
		parent.addAlert(`File ${currentFilePath} saved`, "success");
		if (currentFilePath === "/app/config.json") await hydrateRun();
	}

	// Cerrar WS limpio
	window.addEventListener("beforeunload", () => {
		try {
			ws.close(1000, "bye");
		} catch {}
	});
})();
