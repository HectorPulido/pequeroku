import { NavArrowDown } from "iconoir-react";
import type React from "react";
import { useState } from "react";
import type { FileNode } from "@/types/ide";

const DEFAULT_ROOT = "/app";

interface FileTreeItemProps {
	node: FileNode;
	level: number;
	onSelect: (path: string) => void;
	onToggle: (path: string) => void;
	selectedPath: string | null;
	onAction: (action: string, path: string, type: string) => void;
	onDropFile?: (destination: string, file: File) => Promise<void> | void;
	onContextMenuOpen: (event: React.MouseEvent<HTMLDivElement>, node: FileNode) => void;
}

const INDENT_WIDTH = 16;

const FileTreeItem: React.FC<FileTreeItemProps> = ({
	node,
	level,
	onSelect,
	onToggle,
	selectedPath,
	onAction,
	onDropFile,
	onContextMenuOpen,
}) => {
	const [isDragOver, setIsDragOver] = useState(false);
	const isSelected = selectedPath === node.path;
	const indent = level * INDENT_WIDTH;
	const isFolder = node.type === "folder";

	const destinationPath =
		node.type === "folder"
			? node.path
			: node.path.substring(0, node.path.lastIndexOf("/")) || DEFAULT_ROOT;

	const handleContextMenu = (event: React.MouseEvent<HTMLDivElement>) => {
		event.preventDefault();
		event.stopPropagation();
		onContextMenuOpen(event, node);
	};

	const handleDrop = async (event: React.DragEvent<HTMLDivElement>) => {
		event.preventDefault();
		setIsDragOver(false);
		if (!onDropFile) return;
		const file = event.dataTransfer?.files?.[0];
		if (!file) return;
		await onDropFile(destinationPath, file);
	};

	return (
		<>
			<div
				role="treeitem"
				aria-expanded={isFolder ? node.isOpen : undefined}
				tabIndex={0}
				className={`relative flex cursor-pointer select-none items-center gap-1 px-2 py-1 text-xs transition-colors ${
					isSelected
						? "bg-indigo-500 text-white hover:bg-indigo-500 dark:bg-indigo-600 dark:hover:bg-indigo-600"
						: "text-slate-700 hover:bg-slate-200 dark:text-gray-200 dark:hover:bg-gray-700"
				}`}
				style={{
					paddingLeft: `${indent + (isFolder ? 4 : 20)}px`,
					outline: isDragOver ? "2px dashed rgba(99, 102, 241, 0.6)" : undefined,
				}}
				onClick={(event) => {
					event.stopPropagation();
					onSelect(node.path);
					if (isFolder && event.detail === 2) {
						onToggle(node.path);
					}
				}}
				onContextMenu={handleContextMenu}
				onDragOver={(event) => {
					if (event.dataTransfer?.types.includes("Files")) {
						event.preventDefault();
						setIsDragOver(true);
					}
				}}
				onDragLeave={(event) => {
					if (!event.currentTarget.contains(event.relatedTarget as Node)) {
						setIsDragOver(false);
					}
				}}
				onDrop={handleDrop}
			>
				{isFolder && (
					<button
						type="button"
						className="absolute left-0.5 flex h-4 w-4 items-center justify-center text-slate-500 hover:text-indigo-400 dark:text-gray-400"
						style={{ marginLeft: `${indent}px` }}
						onClick={(event) => {
							event.stopPropagation();
							onToggle(node.path);
						}}
						aria-label={node.isOpen ? "Collapse folder" : "Expand folder"}
					>
						<NavArrowDown
							className={`h-3 w-3 transition-transform ${node.isOpen ? "" : "-rotate-90"}`}
						/>
					</button>
				)}
				{isFolder && <span className="pl-4 leading-relaxed text-nowrap ">📁 {node.name}</span>}
				{!isFolder && <span className="leading-relaxed text-nowrap ">📄 {node.name}</span>}
			</div>
			{isFolder &&
				node.isOpen &&
				node.children?.map((child) => (
					<FileTreeItem
						key={child.path}
						node={child}
						level={level + 1}
						onSelect={onSelect}
						onToggle={onToggle}
						selectedPath={selectedPath}
						onAction={onAction}
						onDropFile={onDropFile}
						onContextMenuOpen={onContextMenuOpen}
					/>
				))}
		</>
	);
};

export default FileTreeItem;
