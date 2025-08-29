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
<div class="tpl-files hidden" style="margin-top:8px;"></div>`;

			card.querySelector(".tpl-apply").onclick = async () => apply(t.id);
			card.querySelector(".tpl-preview").onclick = async () =>
				togglePreview(card, t.id);
			listEl.appendChild(card);
		});
	}

	async function togglePreview(card, templateId) {
		const box = card.querySelector(".tpl-files");
		if (!box.classList.contains("hidden")) {
			box.classList.add("hidden");
			box.innerHTML = "";
			return;
		}
		const res = await fetch(`/api/templates/${templateId}/`, {
			credentials: "same-origin",
		});
		if (!res.ok) {
			addAlert(await res.text(), "error");
			return;
		}
		const t = await res.json();
		const items = t.items || [];
		if (!items.length) box.innerHTML = "<em>Sin archivos</em>";
		else {
			const ul = document.createElement("ul");
			ul.style.marginLeft = "1rem";
			items.forEach((it) => {
				const li = document.createElement("li");
				li.textContent = it.path;
				ul.appendChild(li);
			});
			box.innerHTML = "";
			box.appendChild(ul);
		}
		box.classList.remove("hidden");
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
