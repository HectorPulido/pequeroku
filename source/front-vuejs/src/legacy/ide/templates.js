import { notifyAlert } from "../core/alerts.js";
import { makeApi } from "../core/api.js";
import { $, escapeHtml } from "../core/dom.js";
import { bindModal } from "../core/modals.js";

export function setupTemplates({ containerId, refreshIDE }) {
	const openBtn = $("#btn-open-templates-modal");
	const modalEl = $("#templates-modal");
	const closeBtn = $("#btn-templates-close");
	const listEl = $("#tpl-list");
	const destInput = $("#tpl-dest");
	const cleanInput = $("#tpl-clean");

	const titleEl = modalEl.querySelector(".upload-header > span");
	bindModal(modalEl, openBtn, closeBtn, {
		titleEl,
		defaultTitle: titleEl?.textContent || "Templates",
		initialFocus: () => listEl,
		onOpen: async () => {
			try {
				await load();
			} catch (e) {
				notifyAlert(e.message || String(e), "error");
			}
		},
	});

	async function load() {
		const api = makeApi("/api");
		const templates = await api("/templates/", { credentials: "same-origin" });
		render(templates);
	}

	function render(templates) {
		listEl.innerHTML = "";
		if (!templates?.length) {
			listEl.innerHTML = "<p>No templates available.</p>";
			return;
		}
		templates.forEach((t) => {
			const card = document.createElement("div");
			card.className = "container-card";
			card.innerHTML = `
<h2>${escapeHtml(t.name)}</h2>
<p>${escapeHtml(t.description || "")}</p>
<div style="display:flex; gap:8px; flex-wrap:wrap;">
<button class="tpl-apply">Apply</button>
</div>
<div class="tpl-files hidden" style="margin-top:8px;"></div>`;

			card.querySelector(".tpl-apply").onclick = async () => apply(t.id);
			listEl.appendChild(card);
		});
	}

	async function apply(templateId) {
		const dest = destInput?.value || "/app";
		const clean = !!cleanInput?.checked;
		try {
			const j = await makeApi("/api/templates")(`/${templateId}/apply/`, {
				method: "POST",
				credentials: "same-origin",
				body: JSON.stringify({
					container_id: parseInt(containerId, 10),
					dest_path: dest,
					clean,
				}),
			});
			notifyAlert(
				`Template applied on (${j.files_count} files/s) en ${dest}`,
				"success",
			);
			if (dest === "/app") await refreshIDE?.();
		} catch (e) {
			notifyAlert(e.message || String(e), "error");
		}
	}
}
