import { addAlert } from "../core/alerts.js";
import { makeApi } from "../core/api.js";
import { $ } from "../core/dom.js";
import { bindModal } from "../core/modals.js";
import { isSmallScreen, signatureFrom } from "../core/utils.js";

function show_alert() {
	addAlert(
		`
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
	`,
		"warning",
		false,
	);
}

export function setupContainers() {
	let current_id = "";
	const listEl = $("#container-list");
	const listElOther = $("#other-container-list");
	const btnCreate = $("#btn-create");
	const btnClose = $("#btn-close");
	const btnCloseMetrics = $("#btn-close-metrics");
	const btnFullscreen = $("#btn-fullscreen");
	const modal = $("#console-modal");
	const modalBody = $("#console-modal-body");
	const userData = $("#user_data");
	const quotaInfo = $("#quota_info");
	const btnRefresh = $("#btn-refresh");
	const consoleTitle = $("#console-title");
	const metricsTitle = $("#metrics-title");
	const metricsModal = $("#metrics-modal");
	const metricsModalBody = $("#metrics-modal-body");
	const btnFullscreenMetrics = $("#btn-fullscreen-metrics");

	let containerTypes = null;
	let currentCredits = 0;
	let createModalEl = null;
	let createModalBody = null;
	let createTitleEl = null;
	let btnCloseCreate = null;
	let createCtrl = null;

	let lastSig = null;
	let pollId = null;
	let currentUsername = null;
	let alert_showed = false;

	btnRefresh.addEventListener("click", () => fetchContainers({ lazy: false }));
	btnFullscreen.addEventListener("click", () => {
		if (current_id)
			open(`/ide/?containerId=${current_id}`, "_blank", "noopener,noreferrer");
	});
	btnFullscreenMetrics.addEventListener("click", () => {
		if (current_id)
			open(
				`/metrics/?container=${current_id}`,
				"_blank",
				"noopener,noreferrer",
			);
	});
	btnCloseMetrics.addEventListener("click", closeMetrics);
	btnClose.addEventListener("click", closeConsole);
	btnCreate.addEventListener("click", createContainer);

	fetchContainers();

	async function fetchUserData() {
		try {
			const data = await makeApi("/api")("/user/me/", {
				credentials: "same-origin",
				noLoader: true,
				noAuthRedirect: true,
				noAuthAlert: true,
			});

			if (!data.is_superuser && !alert_showed) {
				alert_showed = true;
				show_alert();
			}

			currentUsername = data.username || null;
			userData.innerText = `Hello ${data.username?.[0]?.toUpperCase()}${data.username?.slice(1) || ""}!`;
			quotaInfo.textContent = JSON.stringify(data, null, "\t");
			if (data.has_quota) {
				currentCredits = Number(data?.quota?.credits_left ?? 0) || 0;
				btnCreate.innerHTML = `<i class="mod-iconoir iconoir-plus-circle"></i> New container (${currentCredits})`;
				btnCreate.disabled = currentCredits <= 0;
			} else {
				btnCreate.innerText = "No quota";
				btnCreate.disabled = true;
			}
		} catch (e) {
			addAlert(e.message, "error");
		}
	}

	function createCard(c) {
		const card = document.createElement("div");
		card.className = "container-card";
		const isRunning = c.status === "running";

		card.innerHTML = `
<h2>${c.id} — ${c.name}</h2>
<small>${c.username}</small> - <small>${new Date(c.created_at).toLocaleString()}</small>
<p>Status: <strong id="st-${c.id}" class="status-${c.status}">${c.status}</strong></p>
<div>
  <button class="btn-edit" ${!isRunning ? "hidden" : ""}><i class="mod-iconoir iconoir-edit-pencil"></i> Open</button>
  <button class="btn-start" ${isRunning ? "hidden" : ""}><i class="mod-iconoir iconoir-play"></i> Start</button>
  <button class="btn-stop" ${!isRunning ? "hidden" : ""}><i class="mod-iconoir iconoir-pause"></i>Stop</button>
  <button class="btn-metrics" ${!isRunning ? "hidden" : ""}><i class="mod-iconoir iconoir-graph-up"></i> Metrics</button>
  <button class="btn-delete"><i class="mod-iconoir iconoir-bin-minus-in"></i> Delete</button>
</div>`;

		card.querySelector(".btn-metrics").onclick = () =>
			openStats(`${c.id} — ${c.name} - Stats`, c.id);
		card.querySelector(".btn-edit").onclick = () =>
			openConsole(`${c.id} — ${c.name} - Editor`, c.id);
		card.querySelector(".btn-delete").onclick = () => {
			if (!confirm(`Delete VM "${c.id} — ${c.name}"?`)) return;
			deleteContainer(c.id);
		};
		card.querySelector(".btn-start").onclick = async () => {
			await makeApi(`/api/containers/${c.id}`)("/power_on/", {
				method: "POST",
				credentials: "same-origin",
			});
			await fetchContainers({ lazy: false });
		};
		card.querySelector(".btn-stop").onclick = async () => {
			await makeApi(`/api/containers/${c.id}`)("/power_off/", {
				method: "POST",
				credentials: "same-origin",
				body: JSON.stringify({ force: false }),
			});
			await fetchContainers({ lazy: false });
		};
		return card;
	}

	async function fetchContainers(opts = { lazy: false }) {
		try {
			if (!currentUsername) await fetchUserData();

			const data = await makeApi("/api/containers")("/", {
				credentials: "same-origin",
				noLoader: true,
				noAuthRedirect: true,
				noAuthAlert: true,
			});
			const sig = signatureFrom(data);

			if (opts.lazy && sig === lastSig) return;
			lastSig = sig;

			listEl.innerHTML = "";
			const mine = (data || []).filter((c) => c.username === currentUsername);
			// biome-ignore lint/suspicious/useIterableCallbackReturn: This is correct
			mine.forEach((c) => listEl.appendChild(createCard(c)));

			listElOther.innerHTML = "";
			const others = (data || []).filter((c) => c.username !== currentUsername);
			// biome-ignore lint/suspicious/useIterableCallbackReturn: This is correct
			others.forEach((c) => listElOther.appendChild(createCard(c)));

			if (others.length === 0) {
				$("#other-container-title").innerHTML = "";
			}

			startPolling();
		} catch (e) {
			addAlert(e.message, "error");
		}
	}

	async function createContainer() {
		try {
			// Refresh user data to get latest credits label/state (best-effort)
			try {
				await fetchUserData();
			} catch {}

			// Fetch container types (cache after first call)
			if (!Array.isArray(containerTypes)) {
				containerTypes = await makeApi("/api/container-types")("/", {
					credentials: "same-origin",
					noLoader: true,
					noAuthRedirect: true,
					noAuthAlert: true,
				});
			}

			// Lazy-build modal DOM
			if (!createModalEl) {
				createModalEl = document.createElement("div");
				createModalEl.id = "create-container-modal";
				createModalEl.className = "hidden";
				createModalEl.innerHTML = `
					<div id="create-modal-header" class="console-header console">
						<span id="create-title">Create container</span>
						<div>
							<button id="btn-close-create" class="top-btn">
								<i class="iconoir-xmark-circle"></i>
							</button>
						</div>
					</div>
					<div id="create-modal-body" class="console-body console"></div>
				`;
				document.body.appendChild(createModalEl);

				createTitleEl = createModalEl.querySelector("#create-title");
				btnCloseCreate = createModalEl.querySelector("#btn-close-create");
				createModalBody = createModalEl.querySelector("#create-modal-body");

				createCtrl = bindModal(createModalEl, null, btnCloseCreate, {
					titleEl: createTitleEl,
					defaultTitle: "Create container",
				});
			}

			// Render available types
			createModalBody.innerHTML = renderContainerTypes(
				containerTypes,
				currentCredits,
			);

			// Wire actions
			Array.from(createModalBody.querySelectorAll("[data-type-id]")).forEach(
				(btn) => {
					btn.onclick = async () => {
						const typeId = Number(btn.getAttribute("data-type-id"));
						try {
							await makeApi("/api/containers")("/", {
								method: "POST",
								credentials: "same-origin",
								body: JSON.stringify({ container_type: typeId }),
							});
							createCtrl?.close?.();
							await fetchContainers();
							// Update credits shown in header (best-effort)
							try {
								await fetchUserData();
							} catch {}
						} catch (e) {
							addAlert(e.message, "error");
						}
					};
				},
			);

			createCtrl.open({ title: "Create container" });
		} catch (e) {
			addAlert(e.message, "error");
		}

		function renderContainerTypes(types, credits_left) {
			if (!Array.isArray(types) || types.length === 0) {
				return `<div>No container types available</div>`;
			}
			const items = types
				.map((t) => {
					const canAfford =
						typeof t.credits_cost === "number"
							? credits_left >= t.credits_cost
							: true;
					const disabled = !canAfford ? "disabled" : "";
					const note =
						typeof t.credits_cost === "number"
							? `Cost: ${t.credits_cost} credits`
							: "";
					const name = t.container_type_name || t.name || `Type #${t.id}`;
					const mem = t.memory_mb ? `${t.memory_mb} MB` : "";
					const cpu = t.vcpus ? `${t.vcpus} vCPU` : "";
					const disk = t.disk_gib ? `${t.disk_gib} GiB` : "";
					const specs = [mem, cpu, disk].filter(Boolean).join(" • ");
					return `
<div class="container-card container-type-card">
  <h3>${name}</h3>
  <p>${specs || ""}</p>
  <button data-type-id="${t.id}" ${disabled}><i class="mod-iconoir iconoir-plus-circle"></i> Create (${note})</button>
</div>`;
				})
				.join("");
			return `<div class="container-grid">${items}</div>`;
		}
	}

	async function deleteContainer(id) {
		try {
			await makeApi(`/api/containers/${id}`)("/", {
				method: "DELETE",
				credentials: "same-origin",
			});
			await fetchContainers();
		} catch (e) {
			addAlert(e.message, "error");
		}
	}

	function openStats(name, id) {
		current_id = id;
		if (isSmallScreen()) {
			open(`/metrics/?container=${id}`, "_blank", "noopener,noreferrer");
			return;
		}
		if (!openStats._ctrl) {
			openStats._ctrl = bindModal(metricsModal, null, btnCloseMetrics, {
				titleEl: metricsTitle,
				defaultTitle: metricsTitle?.textContent || "Metrics",
			});
		}
		openStats._ctrl.open({ title: name });
		metricsModalBody.innerHTML = `<iframe src="/metrics/?container=${id}&showHeader" frameborder="0" style="width: 100%; height: 100%;"></iframe>`;
	}

	function openConsole(name, id) {
		current_id = id;
		if (isSmallScreen()) {
			open(`/ide/?containerId=${id}`, "_blank", "noopener,noreferrer");
			return;
		}
		if (!openConsole._ctrl) {
			openConsole._ctrl = bindModal(modal, null, btnClose, {
				titleEl: consoleTitle,
				defaultTitle: consoleTitle?.textContent || "Console",
			});
		}
		openConsole._ctrl.open({ title: name });
		modalBody.innerHTML = `<iframe src="/ide/?containerId=${id}&showHeader" frameborder="0" style="width: 100%; height: 100%;"></iframe>`;
	}

	function closeConsole() {
		if (openConsole._ctrl) openConsole._ctrl.close();
		modalBody.innerHTML = "";
	}

	function closeMetrics() {
		if (openStats._ctrl) openStats._ctrl.close();
		metricsModalBody.innerHTML = "";
	}

	function startPolling() {
		if (!pollId)
			pollId = setInterval(() => fetchContainers({ lazy: true }), 5_000);
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
