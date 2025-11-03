import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";

type ResizablePanelProps = {
	children: React.ReactNode;
	storageKey: string;
	defaultWidth?: number;
	minWidth?: number;
	maxWidth?: number;
	side: "left" | "right";
	isCollapsed: boolean;
	onResize?: (width: number) => void;
};

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));

const readInitialWidth = (storageKey: string, fallback: number) => {
	if (typeof window === "undefined") return fallback;
	const savedWidth = window.localStorage.getItem(storageKey);
	return savedWidth ? parseInt(savedWidth, 10) : fallback;
};

const ResizablePanel: React.FC<ResizablePanelProps> = ({
	children,
	storageKey,
	defaultWidth = 240,
	minWidth = 200,
	maxWidth = 520,
	side,
	isCollapsed,
	onResize,
}) => {
	const [width, setWidth] = useState(() => readInitialWidth(storageKey, defaultWidth));
	const [isResizing, setIsResizing] = useState(false);
	const panelRef = useRef<HTMLDivElement>(null);
	const dragSnapshot = useRef<{ startX: number; startWidth: number }>({
		startX: 0,
		startWidth: width,
	});

	const handleMouseMove = useCallback(
		(event: MouseEvent) => {
			if (!isResizing) return;
			const { startX, startWidth } = dragSnapshot.current;
			const delta = side === "left" ? event.clientX - startX : startX - event.clientX;
			const newWidth = clamp(startWidth + delta, minWidth, maxWidth);
			setWidth(newWidth);
			onResize?.(newWidth);
		},
		[isResizing, maxWidth, minWidth, onResize, side],
	);

	const handleMouseUp = useCallback(() => {
		if (!isResizing) return;
		setIsResizing(false);
		if (typeof window !== "undefined") {
			window.localStorage.setItem(storageKey, String(width));
		}
	}, [isResizing, storageKey, width]);

	useEffect(() => {
		if (!isResizing) return;
		document.addEventListener("mousemove", handleMouseMove);
		document.addEventListener("mouseup", handleMouseUp);
		return () => {
			document.removeEventListener("mousemove", handleMouseMove);
			document.removeEventListener("mouseup", handleMouseUp);
		};
	}, [handleMouseMove, handleMouseUp, isResizing]);

	useEffect(() => {
		if (isCollapsed || !panelRef.current) return;
		panelRef.current.style.width = `${width}px`;
	}, [isCollapsed, width]);

	if (isCollapsed) {
		return null;
	}

	return (
		<div
			ref={panelRef}
			className="relative h-full"
			style={{
				width: `${width}px`,
				backgroundColor: "var(--color-surface)",
				color: "var(--color-text)",
				borderRight: side === "left" ? "1px solid var(--color-border)" : undefined,
				borderLeft: side === "right" ? "1px solid var(--color-border)" : undefined,
			}}
		>
			{children}
			<button
				type="button"
				aria-label="Resize panel"
				className={`absolute top-0 ${side === "left" ? "right-0" : "left-0"} bottom-0 w-1 cursor-col-resize bg-transparent hover:bg-indigo-500 transition-colors`}
				onMouseDown={(event) => {
					event.preventDefault();
					dragSnapshot.current = {
						startX: event.clientX,
						startWidth: panelRef.current?.getBoundingClientRect().width ?? width,
					};
					setIsResizing(true);
				}}
				onDoubleClick={() => {
					setWidth(defaultWidth);
					onResize?.(defaultWidth);
					if (typeof window !== "undefined") {
						window.localStorage.setItem(storageKey, String(defaultWidth));
					}
				}}
				onKeyDown={(event) => {
					const step = 16;
					if (event.key === "Enter") {
						setWidth(defaultWidth);
						onResize?.(defaultWidth);
						if (typeof window !== "undefined") {
							window.localStorage.setItem(storageKey, String(defaultWidth));
						}
						event.preventDefault();
						return;
					}
					if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
						const direction =
							event.key === "ArrowLeft"
								? side === "left"
									? -step
									: step
								: side === "left"
									? step
									: -step;
						const nextWidth = clamp(width + direction, minWidth, maxWidth);
						setWidth(nextWidth);
						onResize?.(nextWidth);
						if (typeof window !== "undefined") {
							window.localStorage.setItem(storageKey, String(nextWidth));
						}
						event.preventDefault();
					}
				}}
			></button>
		</div>
	);
};

export default ResizablePanel;
