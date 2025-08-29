import { addAlert } from "../core/alerts.js";

export function setupLogin({ onSuccess }) {
	const loginContainer = document.getElementById("login-container");
	const loginForm = document.getElementById("login-form");
	const usernameEl = document.getElementById("username");
	const passwordEl = document.getElementById("password");
	const loginError = document.getElementById("login-error");

	function showLogin() {
		loginContainer.classList.remove("hidden");
		document.getElementById("app").classList.add("hidden");
	}
	function showApp() {
		loginContainer.classList.add("hidden");
		document.getElementById("app").classList.remove("hidden");
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
