import { HalfMoon, SunLight } from "iconoir-react";
import type React from "react";
import { useEffect, useState } from "react";
import { type Theme, themeManager } from "@/lib/theme";

const ThemeToggle: React.FC = () => {
	const [theme, setTheme] = useState<Theme>(themeManager.get());

	useEffect(() => themeManager.subscribe(setTheme), []);

	const nextTheme = theme === "dark" ? "light" : "dark";

	return (
		<button
			onClick={() => themeManager.toggle()}
			className="inline-flex h-9 w-9 items-center justify-center rounded border border-gray-700 text-gray-300 transition hover:border-indigo-500 hover:text-white"
			title="Toggle theme"
			type="button"
		>
			{nextTheme === "light" ? <SunLight className="h-4 w-4" /> : <HalfMoon className="h-4 w-4" />}
		</button>
	);
};

export default ThemeToggle;
