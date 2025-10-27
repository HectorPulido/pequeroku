import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { resolveAppBase } from "@/lib/appBase";
import "./index.css";
import App from "./App.tsx";

const rootElement = document.getElementById("root");

if (!rootElement) {
	throw new Error("Unable to locate root element");
}

const appBase = resolveAppBase();
const routerBase = appBase === "/" ? undefined : appBase.replace(/\/$/, "");

createRoot(rootElement).render(
	<StrictMode>
		<BrowserRouter basename={routerBase}>
			<App />
		</BrowserRouter>
	</StrictMode>,
);
