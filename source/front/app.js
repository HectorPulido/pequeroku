function getCSRF() {
	const match = document.cookie.match(/csrftoken=([^;]+)/);
	return match ? match[1] : "";
}

document.addEventListener("DOMContentLoaded", () => {
	const loginContainer = document.getElementById("login-container");
	const loginForm = document.getElementById("login-form");
	const usernameEl = document.getElementById("username");
	const passwordEl = document.getElementById("password");
	const loginError = document.getElementById("login-error");
	const appDiv = document.getElementById("app");

	//
	(async () => {
		let shouldShowApp = false;
		try {
			const res = await fetch("/api/containers/", {
				credentials: "same-origin",
			});
			if (!res.ok) showLogin();
			else shouldShowApp = true;
		} catch {
			showLogin();
		}
		if (shouldShowApp) showApp();
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
let containersCache = [];
function initApp() {
	let current_id = "";

	const listEl = document.getElementById("container-list");
	const btnCreate = document.getElementById("btn-create");

	const btnClose = document.getElementById("btn-close");
	const btnFullscreen = document.getElementById("btn-fullscreen");
	const modal = document.getElementById("console-modal");
	const modalBody = document.getElementById("console-modal-body");
	const userData = document.getElementById("user_data");
	const quotaInfo = document.getElementById("quota_info");

	btnFullscreen.addEventListener("click", () => {
		if (current_id) {
			open("/ide/?containerId=" + current_id);
		}
	})
	btnClose.addEventListener("click", closeConsole);
	btnCreate.addEventListener("click", createContainer);
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
				const isRunning = c.status === "running";
				card.innerHTML = `
				<h2>${c.id} — ${c.container_id.slice(0, 12)}</h2>
				<small>${new Date(c.created_at).toLocaleString()}</small>
				<p>Status: <strong id="st-${c.id}">${c.status}</strong></p>
				<div>
					<button class="btn-edit" ${!isRunning ? "disabled" : ""}>✏️ Let's Play</button>
					${
						isRunning ? "<button class=\"btn-start\">▶️ Start</button>" : "<button class=\"btn-stop\">⏹️ Stop</button>"
					}
					<button class="btn-delete">🗑️ Delete</button>
				</div>`

				card.querySelector(".btn-edit").onclick = () =>
					openConsole(c.id);
				card.querySelector(".btn-delete").onclick = () => deleteContainer(c.id);
				card.querySelector(".btn-start").onclick = async () => {
					await fetch(`/api/containers/${c.id}/power_on/`, { method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": getCSRF() } });
					await fetchContainers();
				};
				card.querySelector(".btn-stop").onclick = async () => {
					await fetch(`/api/containers/${c.id}/power_off/`, { method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": getCSRF(), "Content-Type": "application/json" }, body: JSON.stringify({ force: false }) });
					await fetchContainers();
				};
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

	async function openConsole(id) {
		current_id = id;
		modal.classList.remove("hidden");
		modalBody.innerHTML = `<iframe src="/ide/?containerId=${id}" frameborder="0" style="width: 100%; height: 100%;"></iframe>`
	}

	function closeConsole() {
		modal.classList.add("hidden");
		modalBody.innerHTML = "";
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

function escapeHtml(s) {
	const d = document.createElement("div");
	d.innerText = String(s);
	return d.innerHTML;
}


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