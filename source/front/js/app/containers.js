import { addAlert } from "../core/alerts.js";
import { getCSRF } from "../core/csrf.js";
import { signatureFrom } from "../core/utils.js";

export function setupContainers() {
	let current_id = "";
	const listEl = document.getElementById("container-list");
	const btnCreate = document.getElementById("btn-create");
	const btnClose = document.getElementById("btn-close");
	const btnFullscreen = document.getElementById("btn-fullscreen");
	const modal = document.getElementById("console-modal");
	const modalBody = document.getElementById("console-modal-body");
	const userData = document.getElementById("user_data");
	const quotaInfo = document.getElementById("quota_info");
	const btnRefresh = document.getElementById("btn-refresh");

	let lastSig = null;
	let pollId = null;

	btnRefresh.addEventListener("click", () => fetchContainers({ lazy: false }));
	btnFullscreen.addEventListener("click", () => {
		if (current_id) open(`/ide/?containerId=${current_id}`);
	});
	btnClose.addEventListener("click", closeConsole);
	btnCreate.addEventListener("click", createContainer);

	fetchContainers();

	async function fetchUserData() {
		try {
			const res = await fetch("/api/user_data/", {
				credentials: "same-origin",
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			userData.innerText = `Hello ${data.username?.[0]?.toUpperCase()}${data.username?.slice(1) || ""}!`;
			quotaInfo.textContent = JSON.stringify(data, null, "\t");
			if (data.has_quota) {
				btnCreate.innerText = `➕ New container (${data.quota.max_containers - data.active_containers})`;
				btnCreate.disabled =
					data.active_containers >= data.quota.max_containers;
			} else {
				btnCreate.innerText = "No quota";
				btnCreate.disabled = true;
			}
		} catch (e) {
			addAlert(e.message, "error");
		}
	}

	async function fetchContainers(opts = { lazy: false }) {
		try {
			const res = await fetch("/api/containers/", {
				credentials: "same-origin",
			});
			if (!res.ok) throw new Error(await res.text());
			const data = await res.json();
			const sig = signatureFrom(data);
			if (opts.lazy && sig === lastSig) return; // no repintar
			lastSig = sig;

			listEl.innerHTML = "";
			data.forEach((c) => {
				const card = document.createElement("div");
				card.className = "container-card";
				const isRunning = c.status === "running";
				card.innerHTML = `
<h2>${c.id} — ${c.container_id.slice(0, 12)}</h2>
<small>${c.username}</small> - <small>${new Date(c.created_at).toLocaleString()}</small>
<p>Status: <strong id="st-${c.id}">${c.status}</strong></p>
<div>
<button class="btn-edit" ${!isRunning ? "hidden" : ""}>✏️ Let's Play</button>
<button class="btn-start" ${isRunning ? "hidden" : ""}>▶️ Start</button>
<button class="btn-stop" ${!isRunning ? "hidden" : ""}>⏹️ Stop</button>
<button class="btn-delete">🗑️ Delete</button>
</div>`;

				card.querySelector(".btn-edit").onclick = () => openConsole(c.id);
				card.querySelector(".btn-delete").onclick = () => deleteContainer(c.id);
				card.querySelector(".btn-start").onclick = async () => {
					await fetch(`/api/containers/${c.id}/power_on/`, {
						method: "POST",
						credentials: "same-origin",
						headers: { "X-CSRFToken": getCSRF() },
					});
					await fetchContainers({ lazy: false });
				};
				card.querySelector(".btn-stop").onclick = async () => {
					await fetch(`/api/containers/${c.id}/power_off/`, {
						method: "POST",
						credentials: "same-origin",
						headers: {
							"X-CSRFToken": getCSRF(),
							"Content-Type": "application/json",
						},
						body: JSON.stringify({ force: false }),
					});
					await fetchContainers({ lazy: false });
				};

				listEl.appendChild(card);
			});

			fetchUserData();
			startPolling();
		} catch (e) {
			addAlert(e.message, "error");
		}
	}

	async function createContainer() {
		try {
			const res = await fetch("/api/containers/", {
				method: "POST",
				credentials: "same-origin",
				headers: { "X-CSRFToken": getCSRF() },
			});
			if (!res.ok) throw new Error(await res.text());
			await fetchContainers();
		} catch (e) {
			addAlert(e.message, "error");
		}
	}

	async function deleteContainer(id) {
		try {
			const res = await fetch(`/api/containers/${id}/`, {
				method: "DELETE",
				credentials: "same-origin",
				headers: { "X-CSRFToken": getCSRF() },
			});
			if (!res.ok) throw new Error(await res.text());
			await fetchContainers();
		} catch (e) {
			addAlert(e.message, "error");
		}
	}

	function openConsole(id) {
		current_id = id;
		modal.classList.remove("hidden");
		modalBody.innerHTML = `<iframe src="/ide/?containerId=${id}" frameborder="0" style="width: 100%; height: 100%;"></iframe>`;
	}
	function closeConsole() {
		modal.classList.add("hidden");
		modalBody.innerHTML = "";
	}

	function startPolling() {
		if (!pollId)
			pollId = setInterval(() => fetchContainers({ lazy: true }), 60_000);
	}
	function stopPolling() {
		if (pollId) {
			clearInterval(pollId);
			pollId = null;
		}
	}

	document.addEventListener("visibilitychange", () => {
		document.hidden ? stopPolling() : startPolling();
	});


	addAlert(`
		<div>
			<div>
				<div>📜 <strong>Aviso Importante (Pequeroku) – Español</strong></div>
				<div>1. Pequeroku no ofrece ningún tipo de garantía ni soporte oficial. Puedes pedir ayuda en el servidor de Discord, pero no se asegura respuesta ni solución.</div>
				<div>2. Está prohibido cualquier acto ilícito o que afecte la seguridad o estabilidad de la plataforma.</div>
				<div>3. Nada de lo que hagas en Pequeroku es privado. Todas las máquinas virtuales son accesibles y están monitoreadas por motivos de seguridad.</div>
				<div>4. El administrador se reserva el derecho de veto, tanto en la plataforma como en el servidor de Discord.</div>
				<div>5. El uso indebido de la plataforma es responsabilidad exclusiva del usuario. El administrador no se hace responsable por las acciones o consecuencias derivadas de dicho uso.</div>
				<div>6. Está prohibido el uso excesivo de recursos (ej. minería, spam, ataques). Dichas actividades pueden ser suspendidas sin previo aviso.</div>
				<div>7. El uso de Pequeroku implica la aceptación de estas condiciones. El incumplimiento puede resultar en la suspensión inmediata del acceso.</div>
			</div>
			<br/>
			<div>
				<div>📜 <strong>Important Notice (Pequeroku) – English</strong></div>
				<div>1. Pequeroku provides no warranty or official support. You may ask for help on the Discord server, but no response or solution is guaranteed.</div>
				<div>2. Any illegal activity or actions that compromise the security or stability of the platform are strictly prohibited.</div>
				<div>3. Nothing you do on Pequeroku is private. All virtual machines are accessible and monitored for security purposes.</div>
				<div>4. The administrator reserves the right to veto usage, both on the platform and on the Discord server.</div>
				<div>5. Misuse of the platform is the sole responsibility of the user. The administrator is not liable for the actions or consequences derived from such misuse.</div>
				<div>6. Excessive use of resources (e.g., mining, spam, attacks) is strictly prohibited and may be terminated without prior notice.</div>
				<div>7. Use of Pequeroku implies acceptance of these conditions. Any violation may result in immediate suspension of access.</div>
			</div>
		</div>
	`, "warning");
}
