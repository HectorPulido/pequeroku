import { alertStore } from "@/lib/alertStore";
import { buildAppUrl, resolveAppBase } from "@/lib/appBase";
import { getCsrfToken } from "@/lib/csrf";
import { loaderStore } from "@/lib/loaderStore";

type ExtendedRequestInit = RequestInit & {
	noLoader?: boolean;
	noAuthRedirect?: boolean;
	noAuthAlert?: boolean;
	suppressAuthRedirect?: boolean;
};

type Fetcher = <T = unknown>(path: string, opts?: ExtendedRequestInit) => Promise<T>;

const DEFAULT_HEADERS: HeadersInit = {
	"Content-Type": "application/json",
};

const APP_BASE = resolveAppBase();
const LOGIN_REDIRECT = buildAppUrl("", APP_BASE);

function notifyAlert(message: string, variant: "error" | "warning" | "info" | "success" = "info") {
	alertStore.push({ message, variant, dismissible: true });
}

export function makeApi(base: string): Fetcher {
	return async function api<T = unknown>(path: string, opts: ExtendedRequestInit = {}): Promise<T> {
		const { noLoader, suppressAuthRedirect, noAuthRedirect, noAuthAlert, headers, ...rest } = opts;

		const finalHeaders: Record<string, string> = {};

		const mergeHeaders = (source?: HeadersInit) => {
			if (!source) return;
			if (source instanceof Headers) {
				source.forEach((value, key) => {
					finalHeaders[key] = value;
				});
				return;
			}
			if (Array.isArray(source)) {
				source.forEach(([key, value]) => {
					finalHeaders[key] = value;
				});
				return;
			}
			Object.assign(finalHeaders, source);
		};

		mergeHeaders(DEFAULT_HEADERS);
		mergeHeaders(headers);

		const body = rest.body as BodyInit | null | undefined;
		if (!(body instanceof FormData)) {
			finalHeaders["Content-Type"] = finalHeaders["Content-Type"] ?? "application/json";
		} else {
			delete finalHeaders["Content-Type"];
		}
		finalHeaders["X-CSRFToken"] = getCsrfToken();

		const requestInit: RequestInit = {
			credentials: "same-origin",
			...rest,
			headers: finalHeaders,
		};

		if (!noLoader) loaderStore.start();
		try {
			const response = await fetch(`${base}${path}`, requestInit);
			const text = await response.text();

			if (response.status === 401 || response.status === 403) {
				const suppressRedirect = !!(noAuthRedirect || suppressAuthRedirect);
				const suppressAlert = !!(noAuthAlert || suppressRedirect);

				if (!suppressAlert) {
					notifyAlert("Session expired", "warning");
				}

				if (suppressRedirect) {
					window.dispatchEvent(
						new CustomEvent("auth:unauthorized", { detail: { status: response.status } }),
					);
					const error = new Error(text || response.statusText || "Unauthorized");
					(error as Error & { status?: number }).status = response.status;
					throw error;
				}

				window.location.href = LOGIN_REDIRECT;
				throw new Error("Redirecting to login");
			}

			if (!response.ok) {
				if (text) notifyAlert(text, "error");
				throw new Error(text || response.statusText || "Request error");
			}

			if (!text) return {} as T;

			try {
				return JSON.parse(text) as T;
			} catch {
				return { raw: text } as T;
			}
		} finally {
			if (!noLoader) loaderStore.stop();
		}
	};
}
