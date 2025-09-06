import { addAlert } from "../core/alerts.js";
import { $ } from "../core/dom.js";

export function setupLogin({ onSuccess }) {
	const loginContainer = $("#login-container");
	const loginForm = $("#login-form");
	const usernameEl = $("#username");
	const passwordEl = $("#password");
	const loginError = $("#login-error");

	function showLogin() {
		loginContainer.classList.remove("hidden");
		$("#app").classList.add("hidden");
	}
	function showApp() {
		loginContainer.classList.add("hidden");
		$("#app").classList.remove("hidden");
		onSuccess?.();
	}

	(async () => {
		try {
			const res = await fetch("/api/containers/", {
				credentials: "same-origin",
			});
			if (!res.ok) showLogin();
			else showApp();
		} catch {
			showLogin();
		}
	})();

	loginForm.addEventListener("submit", async (e) => {
		e.preventDefault();
		loginError.textContent = "";
		const username = usernameEl.value.trim();
		const password = passwordEl.value.trim();
		try {
			const res = await fetch("/api/login/", {
				method: "POST",
				credentials: "same-origin",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ username, password }),
			});
			if (!res.ok) {
				const err = await res.json();
				throw new Error(err.error || "Autenticación fallida");
			}
			showApp();
		} catch (err) {
			loginError.textContent = err.message;
			addAlert(err.message, "error");
		}
	});
}
