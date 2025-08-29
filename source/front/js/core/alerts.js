export function addAlert(message, type = "info") {
	const randomId = Math.floor(Math.random() * 1_000_000);
	const alertBox = document.getElementById("alert-box") || document.body;
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

	wrapper.querySelector(".closebtn").addEventListener("click", () => {
		wrapper.style.opacity = "0";
		setTimeout(() => wrapper.remove(), 600);
	});
}

if (!window.addAlert) window.addAlert = addAlert;
