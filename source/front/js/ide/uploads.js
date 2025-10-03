import { notifyAlert } from "../core/alerts.js";
import { getCSRF } from "../core/csrf.js";
import { $ } from "../core/dom.js";
import { bindModal } from "../core/modals.js";

export function setupUploads({ api, onDone, fileTreeEl }) {
	const openBtn = $("#btn-open-upload-modal");
	const modalEl = $("#upload-modal");
	const closeBtn = $("#btn-upload-close");
	const inputEl = $("#file-input");
	const uploadBtn = $("#btn-upload");

	async function upload(file) {
		if (!file) {
			notifyAlert("Select a file first.", "warning");
			return;
		}
		const form = new FormData();
		form.append("file", file);
		form.append("dest_path", "/app");
		try {
			const j = await api(
				"/upload_file/",
				{ headers: { "X-CSRFToken": getCSRF() }, method: "POST", body: form },
				false,
			);
			notifyAlert(`Uploaded to: ${j.dest || "/app"}`, "success");
			await onDone?.();
		} catch (e) {
			notifyAlert(e.message || String(e), "error");
		}
	}

	const modalCtrl = bindModal(modalEl, openBtn, closeBtn, {
		defaultTitle: "Upload file",
		initialFocus: () => inputEl,
		onOpen: () => {
			try {
				inputEl.value = "";
			} catch {}
		},
	});
	uploadBtn.addEventListener("click", async () => {
		const file = inputEl.files?.[0];
		if (!file) return notifyAlert("Select a file first.", "warning");
		await upload(file);
		modalCtrl.close();
	});
	fileTreeEl.addEventListener("drop", async (e) => {
		e.preventDefault();
		const file = e.dataTransfer.files?.[0];
		await upload(file);
	});
}
