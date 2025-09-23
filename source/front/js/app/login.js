import { addAlert } from "../core/alerts.js";
import { makeApi } from "../core/api.js";
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
			const api = makeApi("/api/containers");
			await api("/", { credentials: "same-origin" });
			showApp();
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
			await makeApi("/api")("/user/login/", {
				method: "POST",
				credentials: "same-origin",
				body: JSON.stringify({ username, password }),
			});
			showApp();
		} catch (err) {
			loginError.textContent = err.message;
			addAlert(err.message, "error");
		}
	});
}
