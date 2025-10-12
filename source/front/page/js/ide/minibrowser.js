import { $ } from "../core/dom.js";

const box = $("#preview-box");
const toggleBtn = $("#toggle-preview");
const urlInput = $("#preview-url");
const goBtn = $("#btn-preview-go");
const refreshBtn = $("#btn-preview-refresh");
const popoutBtn = $("#btn-preview-popout");
const iframe = $("#preview-iframe");

toggleBtn?.addEventListener("click", () => {
	box?.classList.toggle("hidden");
});

goBtn?.addEventListener("click", () => {
	const raw = (urlInput?.value || "").trim();
	if (!raw) return;
	const base = /^https?:\/\//i.test(raw) ? raw : `http://${raw}`;
	let busted = base;
	try {
		const u = new URL(base, window.location.href);
		u.searchParams.set("_cb", String(Date.now()));
		busted = u.toString();
	} catch {
		busted = `${base + (base.includes("?") ? "&" : "?")}_cb=${Date.now()}`;
	}
	if (iframe) iframe.src = busted;
});

refreshBtn?.addEventListener("click", () => {
	if (!iframe) return;
	const current = iframe.src || "";
	if (!current) return;
	try {
		const u = new URL(current, window.location.href);
		u.searchParams.set("_cb", String(Date.now()));
		iframe.src = u.toString();
	} catch {
		const busted = `${current + (current.includes("?") ? "&" : "?")}_cb=${Date.now()}`;
		iframe.src = busted;
	}
});

popoutBtn?.addEventListener("click", () => {
	if (iframe?.src) window.open(iframe.src, "_blank", "noopener,noreferrer");
});
