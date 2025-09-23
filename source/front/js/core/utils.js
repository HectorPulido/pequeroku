export function signatureFrom(data) {
	const norm = (data || [])
		.map((c) => ({
			id: c.id,
			status: c.status,
			created_at: c.created_at,
			name: c.name,
		}))
		.sort((a, b) => String(a.id).localeCompare(String(b.id)));
	return JSON.stringify(norm);
}
export function isSmallScreen() {
	return matchMedia("(max-width: 768px)").matches;
}

export function hideHeader() {
	const queryString = window.location.search;
	const urlParams = new URLSearchParams(queryString);
	const showHeader = urlParams.get("showHeader");
	if (showHeader == null) {
		return;
	}

	const header = document.querySelector("body > header");
	header.classList.add("hidden");

	try {
		document.querySelector("main").classList.remove("calc");
	} catch {}
}

export function sleep(ms) {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function fetchWithTimeout(url, init = {}, timeoutMs = 8000) {
	const controller = new AbortController();
	const id = setTimeout(() => controller.abort(), timeoutMs);
	try {
		const res = await fetch(url, { ...init, signal: controller.signal });
		clearTimeout(id);
		return res;
	} catch (e) {
		clearTimeout(id);
		throw e;
	}
}
