import type React from "react";
import { useEffect, useState } from "react";
import { loaderStore } from "@/lib/loaderStore";

export const LoaderOverlayView: React.FC<{ activeCount: number }> = ({ activeCount }) => {
	if (activeCount === 0) return null;
	return (
		<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
			<div className="h-12 w-12 animate-spin rounded-full border-4 border-indigo-400 border-t-transparent" />
		</div>
	);
};

const LoaderOverlay: React.FC = () => {
	const [active, setActive] = useState(0);

	useEffect(() => loaderStore.subscribe((event) => setActive(event.active)), []);

	return <LoaderOverlayView activeCount={active} />;
};

export default LoaderOverlay;
