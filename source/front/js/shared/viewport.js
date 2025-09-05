// ===== Altura real del viewport (fallback y ajustes dinámicos) =====
export function setVhVar() {
	// Fallback para navegadores sin svh/dvh fiables
	const vh = window.innerHeight * 0.01;
	document.documentElement.style.setProperty("--vh", `${vh}px`);
}
// Ajustes para teclado/orientación en iOS/Android
export function attachViewportListeners() {
	const relayout = () => {
		setVhVar();
		relayoutEditorAndConsole?.();
	};
	window.addEventListener("resize", relayout);
	window.addEventListener("orientationchange", relayout);
	if (window.visualViewport) {
		window.visualViewport.addEventListener("resize", relayout);
		window.visualViewport.addEventListener("scroll", relayout); // iOS mueve viewport con teclado
	}
}
