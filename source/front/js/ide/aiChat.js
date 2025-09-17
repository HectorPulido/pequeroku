import { $ } from "../core/dom.js";

let mdParse = (t) => t;
(async () => {
	try {
		if (globalThis.marked?.parse) {
			mdParse = globalThis.marked.parse;
		} else {
			const mod = await import(
				"https://cdn.jsdelivr.net/npm/marked/lib/marked.esm.js"
			);
			mdParse = mod.marked.parse;
		}
	} catch (e) {
		console.error("Could not load marked:", e);
	}
})();

const messagesEl = $("#messages");
const form = $("#ai-composer");
const input = $("#chat-input");
const sendBtn = $("#ai-send");
const aiDot = $("#ai-dot");
const aiUsesLeft = $("#ai-left");
const btnReconnectDiv = $("#reconnect");
const btnReconnect = $("#ai-reconect");

let bubble = null;
let buffer = "";

const urlParams = new URLSearchParams(window.location.search);
const containerId = urlParams.get("containerId");

let ws = null;

function connect() {
	ws = new WebSocket(`/ws/ai/${containerId}/`);

	ws.onopen = () => {
		console.log("WS Open");
		aiDot.classList.remove("red-dot");
		aiDot.classList.add("dot");

		form.classList.remove("hidden");
		btnReconnect.classList.add("hidden");
	};
	ws.onmessage = (e) => {
		try {
			const data = JSON.parse(e.data);
			if (data.event === "start_text") {
				if (data.role === "user") {
					bubble = addMessage("user", "...");
				} else {
					bubble = addMessage("bot", "...");
				}
			} else if (data.event === "text" && bubble != null) {
				buffer += data.content;
				bubble.innerHTML = mdParse(buffer);
			} else if (data.event === "finish_text") {
				bubble = null;
				buffer = "";
				sendBtn.disabled = false;
			} else if (data.event === "connected") {
				if (data.ai_uses_left_today < 5) {
					aiUsesLeft.innerText = `AI uses left: ${data.ai_uses_left_today}`;
				} else {
					aiUsesLeft.innerText = `Welcome, enjoy your conversation!`;
				}
			}
		} catch (error) {
			console.error(error);
			console.log("RX (Text):", e.data);
		}
	};
	ws.onclose = () => {
		console.log("WS Closed");
		aiDot.classList.add("red-dot");
		aiDot.classList.remove("dot");
		btnReconnectDiv.classList.remove("hidden");
		form.classList.add("hidden");
	};
	ws.onerror = (e) => {
		console.log("WS Error", e);
		aiDot.classList.add("red-dot");
		aiDot.classList.remove("dot");
		btnReconnectDiv.classList.remove("hidden");
		form.classList.add("hidden");
	};
}

function addMessage(role, text) {
	const row = document.createElement("div");
	row.className = `msg ${role}`;
	const avatar = document.createElement("div");
	avatar.className = `avatar ${role}`;
	avatar.textContent = role === "user" ? "You" : "Bot";
	const bubble = document.createElement("div");
	bubble.className = `bubble ${role}`;
	bubble.innerHTML = mdParse(text);
	row.appendChild(avatar);
	row.appendChild(bubble);
	messagesEl.appendChild(row);
	messagesEl.scrollTop = messagesEl.scrollHeight;
	return bubble;
}

btnReconnect.onclick = () => {
	connect();
};

sendBtn.onclick = () => {
	const text = input.value.replace(/\s+$/, "");
	if (!text) return;

	addMessage("user", text);
	input.value = "";
	input.style.height = "46px";
	sendBtn.disabled = true;

	if (ws.readyState === WebSocket.OPEN) {
		ws.send(JSON.stringify({ text: text }));
	}
};

form.addEventListener("submit", async (e) => {
	e.preventDefault();
});

input.addEventListener("keydown", (e) => {
	if (e.key === "Enter" && !e.shiftKey) {
		e.preventDefault();
		sendBtn.click();
	}
});

input.addEventListener("input", () => {
	input.style.height = "46px";
	input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
});

connect();
addMessage("bot", "Hello, how can I help you today?");
