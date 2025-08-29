import { addAlert } from "../core/alerts.js";
import { getCSRF } from "../core/csrf.js";

export function setupUploads({
	api,
	openBtn,
	modalEl,
	closeBtn,
	inputEl,
	uploadBtn,
	onDone,
}) {
	openBtn.addEventListener("click", () => modalEl.classList.remove("hidden"));
	closeBtn.addEventListener("click", () => modalEl.classList.add("hidden"));
	uploadBtn.addEventListener("click", async () => {
		const file = inputEl.files?.[0];
		if (!file) return alert("Select a file first.");
		const form = new FormData();
		form.append("file", file);
		form.append("dest_path", "/app");
		const j = await api(
			"/upload_file/",
			{
				headers: { "X-CSRFToken": getCSRF() },
				credentials: "same-origin",
				method: "POST",
				body: form,
			},
			false,
		);
		addAlert(`Uploaded to: ${j.dest}`, "success");
		closeBtn.click();
		await onDone?.();
	});
}
