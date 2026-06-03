import { Check, NavArrowDown, Tools } from "iconoir-react";
import type React from "react";
import { useState } from "react";
import type { ToolPart } from "@/hooks/useAiChat";

interface ToolActivityProps {
	part: ToolPart;
}

const ToolActivity: React.FC<ToolActivityProps> = ({ part }) => {
	const [open, setOpen] = useState(false);
	const running = part.status === "running";
	const hasArgs = part.args !== undefined && part.args !== null;
	const argsText = hasArgs
		? (() => {
				try {
					return JSON.stringify(part.args, null, 2);
				} catch {
					return String(part.args);
				}
			})()
		: "";

	return (
		<div className="overflow-hidden rounded-lg border border-gray-800 bg-[#0d1117]">
			<button
				type="button"
				onClick={() => setOpen((prev) => !prev)}
				className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-gray-300 transition hover:bg-white/5"
			>
				{running ? (
					<span className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border border-indigo-400 border-t-transparent" />
				) : (
					<Check className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
				)}
				<Tools className="h-3.5 w-3.5 shrink-0 text-gray-500" />
				<span className="truncate">
					{running ? "Using" : "Result from"}{" "}
					<span className="font-mono text-indigo-300">{part.name}</span>
				</span>
				<NavArrowDown
					className={`ml-auto h-4 w-4 shrink-0 text-gray-500 transition-transform ${open ? "rotate-180" : ""}`}
				/>
			</button>
			{open ? (
				<div className="space-y-2 border-t border-gray-800 px-3 py-2">
					{part.command ? (
						<div>
							<div className="mb-1 text-[10px] uppercase tracking-wide text-gray-500">Command</div>
							<pre className="overflow-x-auto rounded bg-black/40 p-2 font-mono text-[11px] text-gray-200">
								{part.command}
							</pre>
						</div>
					) : hasArgs ? (
						<div>
							<div className="mb-1 text-[10px] uppercase tracking-wide text-gray-500">
								Arguments
							</div>
							<pre className="overflow-x-auto rounded bg-black/40 p-2 font-mono text-[11px] text-gray-200">
								{argsText}
							</pre>
						</div>
					) : null}
					{part.output !== undefined ? (
						<div>
							<div className="mb-1 text-[10px] uppercase tracking-wide text-gray-500">Output</div>
							<pre className="max-h-72 overflow-auto rounded bg-black/40 p-2 font-mono text-[11px] text-gray-200">
								{part.output || "(empty)"}
							</pre>
						</div>
					) : null}
				</div>
			) : null}
		</div>
	);
};

export default ToolActivity;
