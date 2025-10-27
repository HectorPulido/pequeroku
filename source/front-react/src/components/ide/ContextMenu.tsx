import type React from "react";
import { useEffect, useMemo, useRef, useState } from "react";

interface ContextMenuProps {
	x: number;
	y: number;
	onClose: () => void;
	onAction: (action: string) => void;
}

const PADDING = 8;
const MENU_WIDTH = 200;
const MENU_HEIGHT = 208;

const ContextMenu: React.FC<ContextMenuProps> = ({ x, y, onClose, onAction }) => {
	const containerRef = useRef<HTMLDivElement>(null);
	const [position, setPosition] = useState<{ top: number; left: number }>({ top: y, left: x });

	const computePosition = useMemo(() => {
		if (typeof window === "undefined") {
			return { top: y, left: x };
		}
		const maxLeft = Math.max(PADDING, window.innerWidth - MENU_WIDTH - PADDING);
		const maxTop = Math.max(PADDING, window.innerHeight - MENU_HEIGHT - PADDING);
		const left = Math.min(Math.max(x, PADDING), maxLeft);
		const top = Math.min(Math.max(y, PADDING), maxTop);
		return { top, left };
	}, [x, y]);

	useEffect(() => {
		setPosition(computePosition);
	}, [computePosition]);

	useEffect(() => {
		const handlePointer = (event: MouseEvent) => {
			const target = event.target as Node | null;
			if (!containerRef.current || containerRef.current.contains(target)) {
				return;
			}
			onClose();
		};
		const handleKey = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				onClose();
			}
		};
		document.addEventListener("mousedown", handlePointer, true);
		document.addEventListener("contextmenu", handlePointer, true);
		document.addEventListener("keydown", handleKey);
		window.addEventListener("blur", onClose);
		window.addEventListener("resize", onClose);
		document.addEventListener("scroll", onClose, true);
		return () => {
			document.removeEventListener("mousedown", handlePointer, true);
			document.removeEventListener("contextmenu", handlePointer, true);
			document.removeEventListener("keydown", handleKey);
			window.removeEventListener("blur", onClose);
			window.removeEventListener("resize", onClose);
			document.removeEventListener("scroll", onClose, true);
		};
	}, [onClose]);

	const handleAction = (action: string) => {
		onAction(action);
		onClose();
	};

	return (
		<div
			ref={containerRef}
			className="fixed z-50 min-w-[12rem] rounded-md border border-slate-200 bg-white shadow-lg dark:border-gray-800 dark:bg-[#111827]"
			style={{ top: position.top, left: position.left }}
		>
			<ul className="py-1">
				<li
					className="cursor-pointer px-4 py-2 text-sm text-slate-700 hover:bg-slate-100 dark:text-gray-300 dark:hover:bg-gray-700"
					onClick={() => handleAction("open")}
				>
					Open
				</li>
				<li
					className="cursor-pointer px-4 py-2 text-sm text-slate-700 hover:bg-slate-100 dark:text-gray-300 dark:hover:bg-gray-700"
					onClick={() => handleAction("rename")}
				>
					Rename
				</li>
				<li
					className="cursor-pointer px-4 py-2 text-sm text-slate-700 hover:bg-slate-100 dark:text-gray-300 dark:hover:bg-gray-700"
					onClick={() => handleAction("delete")}
				>
					Delete
				</li>
				<li
					className="cursor-pointer px-4 py-2 text-sm text-slate-700 hover:bg-slate-100 dark:text-gray-300 dark:hover:bg-gray-700"
					onClick={() => handleAction("new-file")}
				>
					New File
				</li>
				<li
					className="cursor-pointer px-4 py-2 text-sm text-slate-700 hover:bg-slate-100 dark:text-gray-300 dark:hover:bg-gray-700"
					onClick={() => handleAction("new-folder")}
				>
					New Folder
				</li>
				<li
					className="cursor-pointer px-4 py-2 text-sm text-slate-700 hover:bg-slate-100 dark:text-gray-300 dark:hover:bg-gray-700"
					onClick={() => handleAction("download")}
				>
					Download
				</li>
			</ul>
		</div>
	);
};

export default ContextMenu;
