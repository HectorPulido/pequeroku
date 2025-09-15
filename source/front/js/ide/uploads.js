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
	fileTreeEl,
}) {
	async function upload(file) {
		if (!file) return;
		const form = new FormData();
		form.append("file", file);
		form.append("dest_path", "/app");
		await api(
			"/upload_file/",
			{ headers: { "X-CSRFToken": getCSRF() }, method: "POST", body: form },
			false,
		);
		addAlert(`Uploaded to: ${j.dest}`, "success");
		await onDone?.();
	}

	openBtn.addEventListener("click", () => modalEl.classList.remove("hidden"));
	closeBtn.addEventListener("click", () => modalEl.classList.add("hidden"));
	uploadBtn.addEventListener("click", async () => {
		const file = inputEl.files?.[0];
		if (!file) return alert("Select a file first.");
		upload(file);
		closeBtn.click();
	});
	fileTreeEl.addEventListener("drop", async (e) => {
		e.preventDefault();
		const file = e.dataTransfer.files?.[0];
		upload(file);
	});
}
