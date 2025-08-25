// ====== CONFIG ======
const urlParams = new URLSearchParams(window.location.search);
const containerId = urlParams.get('containerId');
const apiBase = `/api/containers/${containerId}`;
const pathLabel = document.getElementById('current_path_label');
const editor = document.getElementById('editor');
const refreshTree = document.getElementById('refresh-tree');
const fileTree = document.getElementById('file-tree');
const sendCMD = document.getElementById('send-cmd');
const consoleCMD = document.getElementById('console-cmd');
const restartContainer = document.getElementById('restart-container');
const runCode = document.getElementById('run-code');
const saveFile = document.getElementById('save-file');
const consoleLogs = document.getElementById('console-log');
const newFolder = document.getElementById('new-folder');
const newFile = document.getElementById('new-file');
const btnUpload = document.getElementById("btn-upload");
const btnOpenUpload = document.getElementById("btn-open-upload-modal");
const uploadModal = document.getElementById("upload-modal");
const btnUploadClose = document.getElementById("btn-upload-close");
const input = document.getElementById("file-input");

const btnOpenTemplates = document.getElementById("btn-open-templates-modal");
const templatesModal = document.getElementById("templates-modal");
const btnTemplatesClose = document.getElementById("btn-templates-close");
let tplListEl, tplDestEl, tplCleanEl;

(() => {
    const overlay = document.getElementById('global-loader');
    if (!overlay) return;

    let active = 0;
    const show = () => overlay.classList.remove('hidden');
    const hide = () => overlay.classList.add('hidden');

    const baseFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
        active++;
        if (active === 1) show();
        try {
            return await baseFetch(...args);
        } finally {
            active = Math.max(0, active - 1);
            if (active === 0) hide();
        }
    };
})();

for (const btn of document.getElementsByClassName("btn-send")) {
    btn.addEventListener("click", (e) =>
        sendCommand(btn.getAttribute("param"))
    );
}


(async () => {
    await sleep(1 * 1000);
    await openFile("/app/readme.txt");
})();

let currentFilePath = null;
function changePath(newPath) {
    currentFilePath = newPath;
    pathLabel.innerText = currentFilePath;
}

function getCSRF() {
    const match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : "";
}
// ====== UTILS ======
async function api(path, opts = {}, headersOverride = true) {
    if (headersOverride)
        opts.headers = { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRF() }
    const res = await fetch(apiBase + path, opts);
    if (!res.ok) {
        parent.addAlert(await res.text(), "error");
    }
    return res.json();
}

// ====== UPLOADS
// 1) Abrir el modal de subida
btnOpenUpload.addEventListener("click", () => {
    uploadModal.classList.remove("hidden");
});

// 2) Cerrar el modal
btnUploadClose.addEventListener("click", () => {
    uploadModal.classList.add("hidden");
});

btnUpload.addEventListener("click", uploadFile);

async function uploadFile() {
    const file = input.files[0];
    if (!file) return alert("Selecciona un archivo primero.");

    const form = new FormData();
    form.append("file", file);
    form.append("dest_path", "/app");

    const j = await api(
        '/upload_file/',
        {
            headers: { 'X-CSRFToken': getCSRF() },
            credentials: "same-origin",
            method: 'POST',
            body: form
        },
        false
    );

    parent.addAlert(`Uploaded to: ${j.dest}`, "success");
    btnUploadClose.click();
    refreshTree.click();
}

// ====== FILE TREE ======
async function listDir(path = '/app') {
    return api(`/list_dir?path=${encodeURIComponent(path)}`);
}

async function loadDir(path, ul) {
    ul.innerHTML = '';
    const items = await listDir(path);
    const prefix = path.replace(/\/$/, '') + '/';
    const direct = items.filter(item => {
        if (!item.path.startsWith(prefix)) return false;
        const rel = item.path.slice(prefix.length);
        return rel && !rel.includes('/');
    });
    direct.sort((a, b) => a.type === b.type ? a.name.localeCompare(b.name) : a.type === 'directory' ? -1 : 1);
    direct.forEach(item => {
        const li = document.createElement('li');
        li.classList.add(item.type);
        li.textContent = item.name;
        li.dataset.path = item.path;
        if (item.type === 'directory') {
            li.addEventListener('click', async e => {
                e.stopPropagation();
                const isExp = li.classList.toggle('expanded');
                if (isExp) {
                    const subUl = document.createElement('ul');
                    li.appendChild(subUl);
                    await loadDir(item.path, subUl);
                } else {
                    const subUl = li.querySelector('ul');
                    if (subUl) li.removeChild(subUl);
                }
            });
        } else {
            li.addEventListener('click', e => {
                e.stopPropagation();
                openFile(item.path);
            });
        }
        ul.appendChild(li);
    });
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}
refreshTree.addEventListener('click', () => {
    loadDir('/app', fileTree);
});

saveFile.addEventListener('click', async () => {
    if (!currentFilePath) parent.addAlert('Open a file first', "error");
    const content = editor.value;
    await api('/write_file/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: currentFilePath, content })
    });
    parent.addAlert('File ' + currentFilePath + ' saved', "success");
});

// ====== CREATE FOLDER & FILE ======
newFolder.addEventListener('click', async () => {
    const name = prompt('Folder name:'); if (!name) return;
    const path = `/app/${name}`;
    await api('/create_dir/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) });
    refreshTree.click();
});
newFile.addEventListener('click', async () => {
    const name = prompt('File name:'); if (!name) return;
    changePath(`/app/${name}`)
    editor.value = '';
    saveFile.click();
    refreshTree.click();
});

async function openFile(path) {
    const ext = path.split('.').pop().toLowerCase();
    const lang = langMap[ext] || 'plaintext';
    monaco.editor.setModelLanguage(editor.editor.getModel(), lang)

    const { content } = await api(`/read_file/?path=${encodeURIComponent(path)}`);
    editor.value = content;
    changePath(path);
}

// ====== CONSOLE ======
async function sendCommand(cmd) {
    await api('/send_command/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command: cmd }) });
}

restartContainer.addEventListener('click', async () => {
    await api('/restart_container/', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
});


// INITIAL
refreshTree.click();


const wsUrl = (() => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${location.host}/ws/containers/${containerId}/`;
})();

let ws;

function connectWS() {
    ws = new WebSocket(wsUrl);
    ws.onopen = () => addToConsole("[connected]");
    ws.onmessage = (ev) => {
        try {
            const msg = JSON.parse(ev.data);
            if (msg.type === "log") {
                addToConsoleAnsi(msg.line);
            } else if (msg.type === "clear") {
                consoleLogs.innerHTML = "";
            } else if (msg.type === "info") {
                addToConsoleAnsi(`[info] ${msg.message}`);
            } else if (msg.type === "error") {
                parent.addAlert(msg.message, "error");
            }
        } catch {
            addToConsoleAnsi(String(ev.data || ""));
        }
    };
    ws.onclose = () => addToConsole("[disconnected]");
    ws.onerror = () => parent.addAlert("WebSocket error", "error");
}

function addToConsoleAnsi(raw) {
    // Si llega un "clear screen": \x1b[H\x1b[2J o \x1b[2J o \x1b[3J
    if (/\x1b\[[0-9;?]*[HJ]/.test(raw) || /\x1b\[[23]J/.test(raw)) {
        consoleLogs.innerHTML = "";
        // Sigue procesando el resto sin las secuencias de clear
        raw = raw.replace(/\x1b\[[0-9;?]*[HJ]/g, "").replace(/\x1b\[[23]J/g, "");
    }

    // Quitar bracketed paste mode on/off: \x1b[?2004h / \x1b[?2004l]
    raw = raw.replace(/\x1b\[\?2004[hl]/g, "");

    // Quitar OSC "set window title": ESC ] ... BEL
    raw = raw.replace(/\x1b\][^\x07]*\x07/g, "");

    // Quitar BELs sueltos
    raw = raw.replace(/\x07/g, "");

    // Interpretar SGR (colores/estilos). Dividimos por SGR, conservando tokens
    const parts = raw.split(/(\x1b\[[0-9;]*m)/g);

    // Estado de estilos
    let classes = new Set();
    let html = "";

    for (const token of parts) {
        const m = /^\x1b\[([0-9;]*)m$/.exec(token);
        if (m) {
            // Es una secuencia SGR
            const params = (m[1] === "" ? ["0"] : m[1].split(";"));
            for (const p of params) {
                const code = parseInt(p, 10);
                if (isNaN(code)) continue;

                if (code === 0) { // reset
                    classes.clear();
                } else if (code === 1) {
                    classes.add("ansi-bold");
                } else if (code === 4) {
                    classes.add("ansi-underline");
                } else if (30 <= code && code <= 37) {
                    // quitar fg anteriores
                    [...classes].forEach(c => /^ansi-fg-/.test(c) && classes.delete(c));
                    classes.add(`ansi-fg-${code}`);
                } else if (90 <= code && code <= 97) {
                    [...classes].forEach(c => /^ansi-fg-/.test(c) && classes.delete(c));
                    classes.add(`ansi-fg-${code}`);
                } else if (40 <= code && code <= 47) {
                    [...classes].forEach(c => /^ansi-bg-/.test(c) && classes.delete(c));
                    classes.add(`ansi-bg-${code}`);
                } else if (100 <= code && code <= 107) {
                    [...classes].forEach(c => /^ansi-bg-/.test(c) && classes.delete(c));
                    classes.add(`ansi-bg-${code}`);
                } else if (code === 22) {
                    classes.delete("ansi-bold");
                } else if (code === 24) {
                    classes.delete("ansi-underline");
                }
                // (Puedes ampliar aquí con más SGR si lo necesitas)
            }
        } else {
            // Texto normal: escapa HTML y envuélvelo con clases actuales (si hay)
            const safe = escapeHtml(token)
                // Maneja retornos de carro (carriage return) reemplazándolos por salto de línea
                .replace(/\r(?!\n)/g, "\n");
            if (safe.length === 0) continue;

            if (classes.size > 0) {
                html += `<span class="${[...classes].join(" ")}">${safe}</span>`;
            } else {
                html += safe;
            }
        }
    }

    // Rompe en líneas visuales (conserva formateo por span)
    // y agrega <div> por cada línea “completa”
    const lines = html.split(/\n/);
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        // evita <div> vacío al final por splits
        if (line === "" && i === lines.length - 1) break;
        consoleLogs.insertAdjacentHTML("beforeend", `<div>${line}</div>`);
    }
    consoleLogs.scrollTop = consoleLogs.scrollHeight;
}

function escapeHtml(s) {
    const d = document.createElement("div");
    d.innerText = s;
    return d.innerHTML;
}

// Enviar comandos por WS
async function sendCommandWS(actionOrCmd) {
    if (!ws || ws.readyState !== 1) connectWS();
    if (typeof actionOrCmd === "string") {
        ws.send(JSON.stringify({ action: "cmd", data: actionOrCmd }));
    } else {
        ws.send(JSON.stringify(actionOrCmd));
    }
}

// Reemplaza los uses de sendCommand(...)
sendCMD.addEventListener('click', () => {
    const v = consoleCMD.value;
    consoleCMD.value = '';
    sendCommandWS(v);
});

for (const btn of document.getElementsByClassName("btn-send")) {
    btn.addEventListener("click", (e) => {
        const p = btn.getAttribute("param");
        if (p === "ctrlc" || p === "ctrld" || p === "clear") {
            sendCommandWS({ action: p });
        }
    });
}

// "Run (Docker)" sigue como antes o puedes disparar comando:
runCode.addEventListener('click', async () => {
    saveFile.click();
    sendCommandWS("docker compose down ; docker compose up -d --build");
});

consoleCMD.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
        e.preventDefault();
        sendCMD.click();
    }
});

// Inicializa
connectWS();



// ====== Templates (mini-IDE) ======
btnOpenTemplates.addEventListener("click", async () => {
    try {
        openTemplatesModal();
        await loadTemplatesIntoModal();
    } catch (e) {
        parent.addAlert(e.message || String(e), "error");
    }
});
btnTemplatesClose.addEventListener("click", () => {
    templatesModal.classList.add("hidden");
});

function openTemplatesModal() {
    if (!tplListEl) {
        tplListEl = document.getElementById("tpl-list");
        tplDestEl = document.getElementById("tpl-dest");
        tplCleanEl = document.getElementById("tpl-clean");
    }
    templatesModal.classList.remove("hidden");
}

async function loadTemplatesIntoModal() {
    const res = await fetch("/api/templates/", { credentials: "same-origin" });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    renderTemplatesInModal(data);
}

function renderTemplatesInModal(templates) {
    tplListEl.innerHTML = "";
    if (!templates || templates.length === 0) {
        tplListEl.innerHTML = "<p>No templates available.</p>";
        return;
    }
    templates.forEach((t) => {
        const card = document.createElement("div");
        card.className = "container-card";
        const count = (t.items || []).length;
        card.innerHTML = `
            <h2>${escapeHtml(t.name)}</h2>
            <small>${new Date(t.updated_at).toLocaleString()}</small>
            <p>${escapeHtml(t.description || "")}</p>
            <p><em>${count} archivo(s)</em></p>
            <div style="display:flex; gap:8px; flex-wrap:wrap;">
                <button class="tpl-apply">Apply</button>
                <button class="tpl-preview">View files</button>
            </div>
            <div class="tpl-files hidden" style="margin-top:8px;"></div>
        `;
        card.querySelector(".tpl-apply").onclick = async () => {
            await applyTemplateFromModal(t.id);
        };
        card.querySelector(".tpl-preview").onclick = async () => {
            await toggleTemplatePreview(card, t.id);
        };
        tplListEl.appendChild(card);
    });
}

async function toggleTemplatePreview(card, templateId) {
    const box = card.querySelector(".tpl-files");
    if (!box.classList.contains("hidden")) {
        box.classList.add("hidden");
        box.innerHTML = "";
        return;
    }
    // carga detalle de un template
    const res = await fetch(`/api/templates/${templateId}/`, { credentials: "same-origin" });
    if (!res.ok) {
        parent.addAlert(await res.text(), "error");
        return;
    }
    const t = await res.json();
    const items = t.items || [];
    if (items.length === 0) {
        box.innerHTML = "<em>Sin archivos</em>";
    } else {
        const list = document.createElement("ul");
        list.style.marginLeft = "1rem";
        items.forEach(it => {
            const li = document.createElement("li");
            li.textContent = it.path;
            list.appendChild(li);
        });
        box.innerHTML = "";
        box.appendChild(list);
    }
    box.classList.remove("hidden");
}

async function applyTemplateFromModal(templateId) {
    const dest = (tplDestEl && tplDestEl.value) ? tplDestEl.value : "/app";
    const clean = !!(tplCleanEl && tplCleanEl.checked);
    try {
        const res = await fetch(`/api/templates/${templateId}/apply/`, {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json", "X-CSRFToken": getCSRF() },
            body: JSON.stringify({
                container_id: parseInt(containerId, 10),
                dest_path: dest,
                clean
            }),
        });
        const j = await res.json();
        if (!res.ok) throw new Error(j.error || "No se pudo aplicar el template");
        parent.addAlert(`Template aplicado (${j.files_count} archivo/s) en ${dest}`, "success");
        // refresca árbol del IDE si el destino es /app
        if (dest === "/app") {
            refreshTree.click();
        }
    } catch (e) {
        parent.addAlert(e.message || String(e), "error");
    }
}