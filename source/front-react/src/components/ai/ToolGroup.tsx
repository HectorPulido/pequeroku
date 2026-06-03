import { NavArrowDown, Tools } from "iconoir-react";
import type React from "react";
import { useState } from "react";
import type { ToolPart } from "@/hooks/useAiChat";
import ToolActivity from "./ToolActivity";

interface ToolGroupProps {
	tools: ToolPart[];
}

/** Collapses a run of tool calls into a single dropdown ("Tools · N"). */
const ToolGroup: React.FC<ToolGroupProps> = ({ tools }) => {
	const [open, setOpen] = useState(false);
	const running = tools.some((tool) => tool.status === "running");

	return (
		<div className="my-2 overflow-hidden rounded-lg border border-gray-800 bg-[#0d1117]">
			<button
				type="button"
				onClick={() => setOpen((prev) => !prev)}
				className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-gray-300 transition hover:bg-white/5"
			>
				{running ? (
					<span className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border border-indigo-400 border-t-transparent" />
				) : (
					<Tools className="h-3.5 w-3.5 shrink-0 text-gray-500" />
				)}
				<span>
					{running ? "Running tools" : "Tools"}{" "}
					<span className="text-gray-500">· {tools.length}</span>
				</span>
				<NavArrowDown
					className={`ml-auto h-4 w-4 shrink-0 text-gray-500 transition-transform ${open ? "rotate-180" : ""}`}
				/>
			</button>
			{open ? (
				<div className="space-y-2 border-t border-gray-800 p-2">
					{tools.map((tool) => (
						<ToolActivity key={tool.id} part={tool} />
					))}
				</div>
			) : null}
		</div>
	);
};

export default ToolGroup;
