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
<small>${new Date(c.created_at).toLocaleString()}</small>
<small>${c.username}</small>
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
}
