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
			const suppressRedirect = !!(
				opts &&
				(opts.noAuthRedirect || opts.suppressAuthRedirect)
			);
			const suppressAlert = !!(opts && (opts.noAuthAlert || suppressRedirect));
			if (!suppressAlert) notifyAlert("Sesión expirada", "warning");
			if (suppressRedirect) {
				// Dispatch a global event to let the app react (e.g., show login and hide app)
				window.dispatchEvent(
					new CustomEvent("auth:unauthorized", {
						detail: { status: res.status },
					}),
				);
				const err = new Error(text || res.statusText || "Unauthorized");
				err.status = res.status;
				throw err;
			}
			location.href = "/";
			return;
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
