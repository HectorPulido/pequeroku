import { $ } from "../core/dom.js";

export function addAlert(message, type = "info", kill_automatically = true) {
	const randomId = Math.floor(Math.random() * 1_000_000);
	const alertBox = $("#alert-box") || document.body;
	const wrapper = document.createElement("div");
	wrapper.className = `alert ${type}`;
	wrapper.id = `alert-${randomId}`;
	wrapper.style.opacity = "0";
	wrapper.innerHTML = `
${message}
<span class="closebtn" id="alert-button-${randomId}">&times;</span>
`;
	alertBox.appendChild(wrapper);

	if (type === "error") console.error(message);
	else console.log(message);

	// biome-ignore lint/suspicious/noAssignInExpressions: I don't want to touch the CSS
	requestAnimationFrame(() => (wrapper.style.opacity = "1"));

	const closeAlert = () => {
		wrapper.style.opacity = "0";
		setTimeout(() => wrapper.remove(), 600);
	};
	wrapper.querySelector(".closebtn").addEventListener("click", closeAlert);

	if (!kill_automatically) {
		return;
	}

	let timeoutId;
	let remaining = 15 * 1000; // 15 segs
	let start = Date.now();

	const startTimer = () => {
		start = Date.now();
		timeoutId = setTimeout(closeAlert, remaining);
	};

	const pauseTimer = () => {
		clearTimeout(timeoutId);
		remaining -= Date.now() - start;
	};

	wrapper.addEventListener("mouseenter", pauseTimer);
	wrapper.addEventListener("mouseleave", startTimer);

	startTimer();
}

export function notifyAlert(message, type = "info", kill_automatically = true) {
	if (window.parent && typeof window.parent.addAlert === "function") {
		window.parent.addAlert(message, type, kill_automatically);
	} else {
		addAlert(message, type, kill_automatically);
	}
}

if (!window.addAlert) window.addAlert = addAlert;
if (!window.notifyAlert) window.notifyAlert = notifyAlert;
