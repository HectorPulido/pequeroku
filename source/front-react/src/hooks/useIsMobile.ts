import { useEffect, useMemo, useState } from "react";

const DEFAULT_QUERY = "(max-width: 900px)";

export function useIsMobile(query: string = DEFAULT_QUERY): boolean {
	const memoizedQuery = useMemo(() => query, [query]);
	const [isMobile, setIsMobile] = useState<boolean>(() => {
		if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
			return false;
		}
		return window.matchMedia(memoizedQuery).matches;
	});

	useEffect(() => {
		if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
			return;
		}
		const mediaQuery = window.matchMedia(memoizedQuery);
		const handleChange = () => {
			setIsMobile(mediaQuery.matches);
		};
		handleChange();
		if (typeof mediaQuery.addEventListener === "function") {
			mediaQuery.addEventListener("change", handleChange);
			return () => mediaQuery.removeEventListener("change", handleChange);
		}
		// Safari < 14
		mediaQuery.addListener(handleChange);
		return () => mediaQuery.removeListener(handleChange);
	}, [memoizedQuery]);

	return isMobile;
}
