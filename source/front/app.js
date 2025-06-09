document.addEventListener("DOMContentLoaded", () => {
	const loginContainer = document.getElementById("login-container");
	const loginForm = document.getElementById("login-form");
	const usernameEl = document.getElementById("username");
	const passwordEl = document.getElementById("password");
	const loginError = document.getElementById("login-error");
	const appDiv = document.getElementById("app");

	// Check session al cargar
	(async function checkAuth() {
		try {
			const res = await fetch("/api/containers/", {
				credentials: "same-origin",
			});
			if (res.ok) showApp();
			else showLogin();
		} catch {
			showLogin();
		}
	})();

	// Mostrar login
	function showLogin() {
		loginContainer.classList.remove("hidden");
		appDiv.classList.add("hidden");
	}

	// Mostrar SPA
	function showApp() {
		loginContainer.classList.add("hidden");
		appDiv.classList.remove("hidden");
		initApp();
	}

	// Manejar submit del login
	loginForm.addEventListener("submit", async (e) => {
		e.preventDefault();
		loginError.textContent = "";
		const username = usernameEl.value.trim();
		const password = passwordEl.value.trim();
		try {
			const res = await fetch("/api/login/", {
				method: "POST",
				credentials: "same-origin",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ username, password }),
			});
			if (!res.ok) {
				const err = await res.json();
				throw new Error(err.error || "Autenticación fallida");
			}
			showApp();
		} catch (err) {
			loginError.textContent = err.message;
		}
	});
});

// Lógica SPA
function initApp() {
	let currentId;
	let poller;
	const listEl = document.getElementById("container-list");
	const btnCreate = document.getElementById("btn-create");
	const modal = document.getElementById("console-modal");
	const titleEl = document.getElementById("console-title");
	const logsEl = document.getElementById("console-logs");
	const inputEl = document.getElementById("cmd-input");
	const btnSend = document.getElementById("btn-send");
	const btnClose = document.getElementById("btn-close");
	const btnRestart = document.getElementById("btn-restart");
	const btnUpload = document.getElementById("btn-upload");
	const btnOpenUpload = document.getElementById("btn-open-upload-modal");
	const uploadModal = document.getElementById("upload-modal");
	const btnUploadClose = document.getElementById("btn-upload-close");

	const userData = document.getElementById("user_data");
	const quotaInfo = document.getElementById("quota_info");

	// 1) Abrir el modal de subida
	btnOpenUpload.addEventListener("click", () => {
		uploadModal.classList.remove("hidden");
	});

	// 2) Cerrar el modal
	btnUploadClose.addEventListener("click", () => {
		uploadModal.classList.add("hidden");
	});

	btnUpload.addEventListener("click", uploadFile);
	btnCreate.addEventListener("click", createContainer);
	btnClose.addEventListener("click", closeConsole);
	btnSend.addEventListener("click", sendCommand);
	btnRestart.addEventListener("click", restartContainer);
	inputEl.addEventListener(
		"keydown",
		// biome-ignore lint/style/noCommaOperator: <explanation>
		(e) => e.key === "Enter" && (e.preventDefault(), sendCommand()),
	);
	for (const btn of document.getElementsByClassName("btn-send")) {
		btn.addEventListener("click", (e) =>
			sendCommandData(btn.getAttribute("param")),
		);
	}

	fetchContainers();

	async function fetchUserData() {
		try {
			const res = await fetch("/api/user_data/", {
				credentials: "same-origin",
			});
			if (!res.ok) {
				const err = await res.text();
				throw new Error(`Error al obtener contenedores: ${err}`);
			}
			const data = await res.json();
			console.log(data);

			userData.innerText = `Hello ${capitalizeFirstLetter(data.username)}!`;
			quotaInfo.innerHTML = JSON.stringify(data, null, "\t");
			if (data.has_quota) {
				btnCreate.innerText = `➕ New container (${data.quota.max_containers - data.active_containers})`;
				btnCreate.disabled =
					data.active_containers >= data.quota.max_containers;
			} else {
				btnCreate.innerText = "No quota";
				btnCreate.disabled = true;
			}
		} catch (error) {
			addAlert(error.message, "error");
		}
	}

	function getCSRF() {
		const match = document.cookie.match(/csrftoken=([^;]+)/);
		return match ? match[1] : "";
	}

	async function fetchContainers() {
		try {
			const res = await fetch("/api/containers/", {
				credentials: "same-origin",
			});
			if (!res.ok) {
				const err = await res.text();
				throw new Error(`Error al obtener contenedores: ${err}`);
			}
			const data = await res.json();
			listEl.innerHTML = "";
			// biome-ignore lint/complexity/noForEach: <explanation>
			data.forEach((c) => {
				const card = document.createElement("div");
				card.className = "container-card";
				card.innerHTML = `
        <h2>${c.id} — ${c.container_id.slice(0, 12)}</h2>
        <small>${new Date(c.created_at).toLocaleString()}</small>
        <p>Status: ${c.status}</p>
		<div>
        <button class="btn-console">Console</button>
        <button class="btn-delete">Stop ⏹️</button>
		</div>
      `;
				card.querySelector(".btn-console").onclick = () =>
					openConsole(c.id, c.container_id);
				card.querySelector(".btn-delete").onclick = () => deleteContainer(c.id);
				listEl.appendChild(card);
			});

			fetchUserData();
		} catch (error) {
			addAlert(error.message, "error");
		}
	}

	async function createContainer() {
		try {
			const res = await fetch("/api/containers/", {
				method: "POST",
				credentials: "same-origin",
				headers: { "X-CSRFToken": getCSRF() },
			});
			if (!res.ok) {
				const err = await res.text();
				throw new Error(`Error al crear contenedor: ${err}`);
			}
			await fetchContainers();
		} catch (error) {
			addAlert(error.message, "error");
		}
	}

	async function deleteContainer(id) {
		try {
			const res = await fetch(`/api/containers/${id}/`, {
				method: "DELETE",
				credentials: "same-origin",
				headers: { "X-CSRFToken": getCSRF() },
			});
			if (!res.ok) {
				const err = await res.text();
				throw new Error(`Error al eliminar contenedor: ${err}`);
			}
			await fetchContainers();
		} catch (error) {
			addAlert(error.message, "error");
		}
	}

	function openConsole(id, name) {
		currentId = id;
		titleEl.textContent = `Container ${name.substring(0, 10)}`;
		logsEl.innerHTML = "";
		modal.classList.remove("hidden");
		poller = setInterval(loadLogs, 1000);
	}

	function closeConsole() {
		clearInterval(poller);
		modal.classList.add("hidden");
		inputEl.value = "";
	}

	async function loadLogs() {
		try {
			const res = await fetch(`/api/containers/${currentId}/read_logs/`, {
				credentials: "same-origin",
			});
			if (!res.ok) {
				const err = await res.text();
				throw new Error(`Error al cargar logs: ${err}`);
			}
			const json = await res.json();
			logsEl.innerHTML = json.logs.map((l) => `<div>${l}</div>`).join("");
			logsEl.scrollTop = logsEl.scrollHeight;
		} catch (error) {
			addAlert(error.message, "error");
		}
	}

	async function restartContainer() {
		try {
			const res = await fetch(
				`/api/containers/${currentId}/restart_container/`,
				{
					method: "POST",
					credentials: "same-origin",
					headers: {
						"Content-Type": "application/json",
						"X-CSRFToken": getCSRF(),
					},
				},
			);
			if (!res.ok) {
				const err = await res.text();
				throw new Error(`Error al reiniciar contenedor: ${err}`);
			}
			inputEl.value = "";
			await loadLogs();
		} catch (error) {
			addAlert(error.message, "error");
		}
	}

	async function sendCommandData(cmd) {
		if (!cmd) return;
		try {
			const res = await fetch(`/api/containers/${currentId}/send_command/`, {
				method: "POST",
				credentials: "same-origin",
				headers: {
					"Content-Type": "application/json",
					"X-CSRFToken": getCSRF(),
				},
				body: JSON.stringify({ command: cmd }),
			});
			if (!res.ok) {
				const err = await res.text();
				throw new Error(`Error al enviar comando: ${err}`);
			}
			await loadLogs();
		} catch (error) {
			addAlert(error.message, "error");
		}
	}

	function sendCommand() {
		const cmd = inputEl.value.trim();
		sendCommandData(cmd);
		inputEl.value = "";
	}

	function uploadFile() {
		const input = document.getElementById("file-input");
		const file = input.files[0];
		if (!file) return alert("Selecciona un archivo primero.");

		const form = new FormData();
		form.append("file", file);
		// form.append("dest_path", "/app/data"); // si quieres ruta custom

		fetch(`/api/containers/${currentId}/upload_file/`, {
			method: "POST",
			body: form,
			credentials: "same-origin",
			headers: {
				"X-CSRFToken": getCSRF(),
			},
		})
			.then((r) => r.json())
			.then((j) => {
				if (j.error) {
					addAlert(`Error: ${j.error}`, "error");
				} else {
					addAlert(`Uploaded to: ${j.dest}`, "success");
				}
			});
	}
}

function addAlert(message, type) {
	const randomId = Math.floor(Math.random() * 1000000);
	const alertBox = document.getElementById("alert-box");
	alertBox.innerHTML += `
    <div class="alert ${type}" style="opacity:0" id="alert-${randomId}">
		${message}
      <span class="closebtn" id="alert-button-${randomId}">&times;</span>
    </div>
  `;

	if (type === "error") {
		console.error(message);
	} else {
		console.log(message);
	}

	const alertElem = document.getElementById(`alert-${randomId}`);
	setTimeout(() => {
		alertElem.style.opacity = "1";
	}, 100);

	const closeButtons = document.getElementsByClassName("closebtn");
	for (let i = 0; i < closeButtons.length; i++) {
		closeButtons[i].addEventListener("click", (event) => {
			const div = event.currentTarget.parentElement;
			if (div) {
				div.style.opacity = "0";
				setTimeout(() => {
					div.remove();
				}, 600);
			}
		});
	}
}

function capitalizeFirstLetter(str) {
	return str.charAt(0).toUpperCase() + str.slice(1);
}
