import type React from "react";
import { useCallback, useMemo, useState } from "react";
import type { FileNode } from "@/types/ide";
import ContextMenu from "./ContextMenu";
import FileTreeItem from "./FileTreeItem";

type ContextMenuState = {
	x: number;
	y: number;
	path: string;
	type: string;
} | null;

interface FileTreeProps {
	fileTree: FileNode[];
	selectedFile: string | null;
	onSelect: (path: string) => void;
	onToggle: (path: string) => void;
	onAction: (action: string, path: string, type: string) => void;
	onDropFile?: (destination: string, file: File) => Promise<void> | void;
}

const FileTree: React.FC<FileTreeProps> = ({
	fileTree,
	selectedFile,
	onSelect,
	onToggle,
	onAction,
	onDropFile,
}) => {
	const [contextMenu, setContextMenu] = useState<ContextMenuState>(null);

	const handleRootDragOver = (event: React.DragEvent<HTMLDivElement>) => {
		if (event.dataTransfer?.types.includes("Files")) {
			event.preventDefault();
		}
	};

	const handleRootDrop = async (event: React.DragEvent<HTMLDivElement>) => {
		event.preventDefault();
		if (!onDropFile) return;
		const file = event.dataTransfer?.files?.[0];
		if (!file) return;
		await onDropFile("/app", file);
	};

	const nodesToDisplay = useMemo(() => {
		if (fileTree.length === 1 && fileTree[0]?.path === "/app") {
			return fileTree[0].children ?? [];
		}
		return fileTree;
	}, [fileTree]);

	const handleContextMenuOpen = useCallback(
		(event: React.MouseEvent<HTMLDivElement>, node: FileNode) => {
			onSelect(node.path);
			setContextMenu({
				x: event.clientX,
				y: event.clientY,
				path: node.path,
				type: node.type,
			});
		},
		[onSelect],
	);

	const handleContextMenuClose = useCallback(() => {
		setContextMenu(null);
	}, []);

	const handleContextMenuAction = useCallback(
		(action: string) => {
			if (!contextMenu) return;
			onAction(action, contextMenu.path, contextMenu.type);
			setContextMenu(null);
		},
		[contextMenu, onAction],
	);

	return (
		<div
			className="flex h-full flex-col overflow-hidden"
			onDragOver={handleRootDragOver}
			onDrop={handleRootDrop}
			role="tree"
		>
			<div className="flex-1 overflow-auto py-2">
				{nodesToDisplay.length === 0 ? (
					<div className="px-3 text-xs text-slate-500 dark:text-gray-400">Loading Workspace...</div>
				) : (
					nodesToDisplay.map((node) => (
						<FileTreeItem
							key={node.path}
							node={node}
							level={0}
							onSelect={onSelect}
							onToggle={onToggle}
							selectedPath={selectedFile}
							onAction={onAction}
							onDropFile={onDropFile}
							onContextMenuOpen={handleContextMenuOpen}
						/>
					))
				)}
			</div>
			{contextMenu && (
				<ContextMenu
					x={contextMenu.x}
					y={contextMenu.y}
					onClose={handleContextMenuClose}
					onAction={handleContextMenuAction}
				/>
			)}
		</div>
	);
};

export default FileTree;
