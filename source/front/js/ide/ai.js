import { addAlert } from "../core/alerts.js";
import { getCSRF } from "../core/csrf.js";

const DEFAULT_PROMPT = `1) Your main goal is to create an adventure game for consoles.
2) There must be a map and a character; the player can move the character on the map and, when facing something, can interact with that thing.
3) Each object has a short dialog that can sometimes change other objects; for example, a key that later lets you open a door.`;

function notify(message, type = "info") {
	// Prefer the parent app's alert if available (when IDE is embedded), otherwise local
	if (window.parent && typeof window.parent.addAlert === "function") {
		window.parent.addAlert(message, type);
	} else {
		addAlert(message, type);
	}
}

export function setupAi({
	openBtn,
	modalEl,
	closeBtn,
	inputEl,
	generateBtn,
	creditsEl,
	containerId,
	onApplied,
}) {
	// Open/close modal
	openBtn.addEventListener("click", () => {
		modalEl.classList.remove("hidden");
		if (!inputEl.value?.trim()) inputEl.value = DEFAULT_PROMPT;
		inputEl.focus();
	});
	closeBtn.addEventListener("click", () => modalEl.classList.add("hidden"));

	// Generate flow
	generateBtn.addEventListener("click", async () => {
		const prompt = (inputEl.value || "").trim();
		if (!prompt) {
			notify("Please write a prompt first.", "warning");
			return;
		}

		const restore = () => {
			generateBtn.disabled = false;
			generateBtn.textContent = "Generate";
		};

		try {
			generateBtn.disabled = true;
			generateBtn.textContent = "Generating…";
			creditsEl.textContent = "";

			// 1) Ask AI to generate a plan/code text
			const genRes = await fetch("/api/ai-generate/", {
				method: "POST",
				credentials: "same-origin",
				headers: {
					"Content-Type": "application/json",
					"X-CSRFToken": getCSRF(),
				},
				body: JSON.stringify({ prompt }),
			});

			const genJson = await genRes.json().catch(() => ({}));
			if (!genRes.ok) {
				throw new Error(genJson.error || "AI generation failed.");
			}

			const generatedText = genJson.text || "";
			const left = genJson.ai_uses_left_today;
			if (typeof left === "number") {
				creditsEl.textContent = `AI uses left today: ${left}`;
			}

			if (!generatedText.trim()) {
				throw new Error("The AI returned an empty result.");
			}

			generateBtn.textContent = "Applying…";

			// 2) Apply generated code as a template into the active container
			const applyRes = await fetch("/api/templates/apply_ai_generated_code/", {
				method: "POST",
				credentials: "same-origin",
				headers: {
					"Content-Type": "application/json",
					"X-CSRFToken": getCSRF(),
				},
				body: JSON.stringify({
					container_id: parseInt(containerId, 10),
					dest_path: "/app",
					clean: true,
					content: generatedText,
				}),
			});

			const applyJson = await applyRes.json().catch(() => ({}));
			if (!applyRes.ok) {
				throw new Error(
					applyJson.error || "Could not apply AI-generated code.",
				);
			}

			notify("AI code applied to /app.", "success");
			modalEl.classList.add("hidden");
			await onApplied?.();
		} catch (err) {
			notify(err.message || String(err), "error");
		} finally {
			restore();
		}
	});
}
