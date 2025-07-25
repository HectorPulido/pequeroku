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
function initApp() {
	const listEl = document.getElementById("container-list");
	const btnCreate = document.getElementById("btn-create");
	// const btnOpenUpload = document.getElementById("btn-open-upload-modal");
	// const uploadModal = document.getElementById("upload-modal");
	// const btnUploadClose = document.getElementById("btn-upload-close");

	const btnClose = document.getElementById("btn-close");
	const modal = document.getElementById("console-modal");
	const modalBody = document.getElementById("console-modal-body");
	const userData = document.getElementById("user_data");
	const quotaInfo = document.getElementById("quota_info");


	// // 1) Abrir el modal de subida
	// btnOpenUpload.addEventListener("click", () => {
	// 	uploadModal.classList.remove("hidden");
	// });

	// // 2) Cerrar el modal
	// btnUploadClose.addEventListener("click", () => {
	// 	uploadModal.classList.add("hidden");
	// });

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
		<button class="btn-edit">✏️ Let's Play</button>
        <button class="btn-delete">⏹️ Stop</button>
		</div>
      `;
				card.querySelector(".btn-edit").onclick = () =>
					openConsole(c.id);
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

	async function openConsole(id) {
		modal.classList.remove("hidden");
		modalBody.innerHTML = `<iframe src="/ide/?containerId=${id}" frameborder="0" style="width: 100%; height: 100%;"></iframe>`
	}

	function closeConsole() {
		modal.classList.add("hidden");
		modalBody.innerHTML = "";
	}


	// function uploadFile() {
	// 	const input = document.getElementById("file-input");
	// 	const file = input.files[0];
	// 	if (!file) return alert("Selecciona un archivo primero.");

	// 	const form = new FormData();
	// 	form.append("file", file);
	// 	// form.append("dest_path", "/app/data"); // si quieres ruta custom

	// 	fetch(`/api/containers/${currentId}/upload_file/`, {
	// 		method: "POST",
	// 		body: form,
	// 		credentials: "same-origin",
	// 		headers: {
	// 			"X-CSRFToken": getCSRF(),
	// 		},
	// 	})
	// 		.then((r) => r.json())
	// 		.then((j) => {
	// 			if (j.error) {
	// 				addAlert(`Error: ${j.error}`, "error");
	// 			} else {
	// 				addAlert(`Uploaded to: ${j.dest}`, "success");
	// 			}
	// 		});
	// }
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
