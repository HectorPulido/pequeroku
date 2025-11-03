import { Plus, Xmark } from "iconoir-react";
import type React from "react";

export interface TabItem {
	id: string;
	title: string;
	isDirty?: boolean;
	closable?: boolean;
}

interface TabsBarProps {
	items: TabItem[];
	activeId: string | null;
	onChange?: (id: string) => void;
	onClose?: (id: string) => void;
	onAdd?: () => void;
	addLabel?: string;
	rightActions?: React.ReactNode;
}

const TabsBar: React.FC<TabsBarProps> = ({
	items,
	activeId,
	onChange,
	onClose,
	onAdd,
	addLabel = "New",
	rightActions,
}) => {
	const showRightSection = Boolean(onAdd || rightActions);

	return (
		<div className="flex items-stretch border-b border-gray-800 bg-[#111827] min-h-auto">
			<div className="flex-1 min-w-0 overflow-hidden">
				<div className="flex h-full items-stretch overflow-x-auto overflow-y-hidden whitespace-nowrap scrollbar-thin">
					{items.map((item) => {
						const isActive = item.id === activeId;
						return (
							<div
								key={item.id}
								className={`inline-flex items-center gap-2 border-r border-gray-800 px-3 py-2 text-xs transition-colors ${
									isActive ? "bg-[#0B1220] text-white" : "text-gray-400 hover:text-white"
								}`}
							>
								<button
									type="button"
									className="flex items-center gap-2 focus:outline-none"
									onClick={() => onChange?.(item.id)}
								>
									<span className="flex items-center gap-1">
										{item.title}
										{item.isDirty ? (
											<span className="align-middle text-indigo-400" aria-hidden="true">
												●
											</span>
										) : null}
									</span>
								</button>
								{item.closable !== false && onClose ? (
									<button
										type="button"
										className="hover:text-red-400 focus:outline-none"
										onClick={() => onClose(item.id)}
										aria-label={`Close ${item.title}`}
									>
										<Xmark className="h-3 w-3" />
									</button>
								) : null}
							</div>
						);
					})}
				</div>
			</div>
			{showRightSection ? (
				<div className="flex shrink-0 items-center gap-2 px-2">
					{rightActions ? <div className="flex items-center gap-2">{rightActions}</div> : null}
					{onAdd ? (
						<button
							type="button"
							onClick={onAdd}
							className="inline-flex w-20 items-center justify-center gap-1 rounded border border-gray-700 px-2 py-1 text-xs text-gray-300 transition hover:border-indigo-500 hover:text-white"
						>
							<Plus className="h-3 w-3" />
							{addLabel}
						</button>
					) : null}
				</div>
			) : null}
		</div>
	);
};

export default TabsBar;
