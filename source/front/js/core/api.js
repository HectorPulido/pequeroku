import { notifyAlert } from "./alerts.js";
import { getCSRF } from "./csrf.js";

export function makeApi(base) {
	return async function api(path, opts = {}, overrideHeaders = true) {
		if (overrideHeaders)
			opts.headers = {
				"Content-Type": "application/json",
				"X-CSRFToken": getCSRF(),
				...(opts.headers || {}),
			};
		const res = await fetch(base + path, opts);
		const text = await res.text();

		if (res.status === 401 || res.status === 403) {
			notifyAlert("Sesión expirada", "warning");
			location.href = "/";
			return; // corta
		}
		if (!res.ok) {
			notifyAlert(text || res.statusText, "error");
			throw new Error(text || res.statusText);
		}
		try {
			return text ? JSON.parse(text) : {};
		} catch {
			return { raw: text };
		}
	};
}
