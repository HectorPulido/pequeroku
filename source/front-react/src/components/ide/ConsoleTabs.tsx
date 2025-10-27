import type React from "react";
import type { TerminalTab } from "@/types/ide";
import TabsBar, { type TabItem } from "./TabsBar";

interface ConsoleTabsProps {
	tabs: TerminalTab[];
	activeTab: string;
	onTabChange: (id: string) => void;
	onTabClose: (id: string) => void;
	onNewTab: () => void;
}

const ConsoleTabs: React.FC<ConsoleTabsProps> = ({
	tabs,
	activeTab,
	onTabChange,
	onTabClose,
	onNewTab,
}) => {
	const items: TabItem[] = tabs.map((tab) => ({
		id: tab.id,
		title: tab.title,
	}));

	return (
		<TabsBar
			items={items}
			activeId={activeTab}
			onChange={onTabChange}
			onClose={onTabClose}
			onAdd={onNewTab}
		/>
	);
};

export default ConsoleTabs;
