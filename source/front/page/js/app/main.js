import { installGlobalLoader } from "../core/loader.js";
import { applyTheme, setupThemeToggle } from "../core/themes.js";
import { setupContainers } from "./containers.js";
import { setupLogin } from "./login.js";

installGlobalLoader();
applyTheme();

setupLogin({ onSuccess: () => setupContainers() });

window.addEventListener("auth:unauthorized", () => {
	const loginContainer = document.getElementById("login-container");
	const appEl = document.getElementById("app");
	if (loginContainer && appEl) {
		loginContainer.classList.remove("hidden");
		appEl.classList.add("hidden");
	}
});

window.addEventListener("DOMContentLoaded", () => {
	const btn = document.getElementById("theme-toggle");
	if (btn) setupThemeToggle(btn);
});
