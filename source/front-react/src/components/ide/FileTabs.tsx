import type React from "react";
import type { Tab } from "@/types/ide";
import TabsBar, { type TabItem } from "./TabsBar";

const MAX_DISPLAY_LENGTH = 25;

const formatTabLabel = (path: string, fallback: string): string => {
	const normalized = (path || "").replace(/^\/?app\//, "").replace(/^\/+/, "");
	if (!normalized) return fallback;
	if (normalized.length <= MAX_DISPLAY_LENGTH) {
		return normalized;
	}
	return `...${normalized.slice(-MAX_DISPLAY_LENGTH)}`;
};

interface FileTabsProps {
	tabs: Tab[];
	activeTab: string | null;
	onTabChange: (id: string) => void;
	onTabClose: (id: string) => void;
	rightActions?: React.ReactNode;
}

const FileTabs: React.FC<FileTabsProps> = ({
	tabs,
	activeTab,
	onTabChange,
	onTabClose,
	rightActions,
}) => {
	const items: TabItem[] = tabs.map((tab) => ({
		id: tab.id,
		title: formatTabLabel(tab.path, tab.title),
		isDirty: tab.isDirty,
	}));

	return (
		<TabsBar
			items={items}
			activeId={activeTab}
			onChange={onTabChange}
			onClose={onTabClose}
			rightActions={rightActions}
		/>
	);
};

export default FileTabs;
