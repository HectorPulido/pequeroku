import { addAlert } from "../core/alerts.js";
import { getCSRF } from "../core/csrf.js";
import { escapeHtml } from "../core/dom.js";

export function setupTemplates({
	openBtn,
	modalEl,
	closeBtn,
	listEl,
	destInput,
	cleanInput,
	containerId,
	refreshIDE,
}) {
	openBtn.addEventListener("click", async () => {
		try {
			openModal();
			await load();
		} catch (e) {
			addAlert(e.message || String(e), "error");
		}
	});
	closeBtn.addEventListener("click", () => modalEl.classList.add("hidden"));

	function openModal() {
		modalEl.classList.remove("hidden");
	}

	async function load() {
		const res = await fetch("/api/templates/", { credentials: "same-origin" });
		if (!res.ok) throw new Error(await res.text());
		render(await res.json());
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
			const res = await fetch(`/api/templates/${templateId}/apply/`, {
				method: "POST",
				credentials: "same-origin",
				headers: {
					"Content-Type": "application/json",
					"X-CSRFToken": getCSRF(),
				},
				body: JSON.stringify({
					container_id: parseInt(containerId, 10),
					dest_path: dest,
					clean,
				}),
			});
			const j = await res.json();
			if (!res.ok) throw new Error(j.error || "Could not open the templates");
			addAlert(
				`Template applied on (${j.files_count} files/s) en ${dest}`,
				"success",
			);
			if (dest === "/app") await refreshIDE?.();
		} catch (e) {
			addAlert(e.message || String(e), "error");
		}
	}
}
