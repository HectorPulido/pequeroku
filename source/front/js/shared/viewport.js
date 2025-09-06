export function setVhVar() {
	const vh = window.innerHeight * 0.01;
	document.documentElement.style.setProperty("--vh", `${vh}px`);
}

export function attachViewportListeners() {
	const relayout = () => {
		setVhVar();
		relayoutEditorAndConsole?.();
	};
	window.addEventListener("resize", relayout);
	window.addEventListener("orientationchange", relayout);
	if (window.visualViewport) {
		window.visualViewport.addEventListener("resize", relayout);
		window.visualViewport.addEventListener("scroll", relayout);
	}
}
