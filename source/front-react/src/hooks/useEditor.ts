import { useCallback, useEffect, useRef, useState } from "react";
import type { Tab } from "@/types/ide";

type FileSystemWebService = InstanceType<
	typeof import("@/services/ide/FileSystemWebService").default
>;

export function getOrCreateTab(
	prevTabs: Tab[],
	path: string,
	now: number,
): { tabs: Tab[]; activeId: string; reused: boolean } {
	const existing = prevTabs.find((tab) => tab.path === path);
	if (existing) {
		return { tabs: prevTabs, activeId: existing.id, reused: true };
	}
	const newTab: Tab = {
		id: `${now}`,
		title: path.split("/").pop() || path,
		path,
		isDirty: false,
	};
	return { tabs: [...prevTabs, newTab], activeId: newTab.id, reused: false };
}

export const useEditor = (containerId: string, service: FileSystemWebService) => {
	const [tabsState, setTabsState] = useState<Tab[]>([]);
	const [activeTabState, setActiveTabState] = useState<string | null>(null);
	const [editorContent, setEditorContentState] = useState("");
	const tabsRef = useRef<Tab[]>([]);
	const activeTabRef = useRef<string | null>(null);
	const originalContentRef = useRef<Record<string, string>>({});
	const tabContentRef = useRef<Record<string, string>>({});

	const setTabs = useCallback((updater: Tab[] | ((prev: Tab[]) => Tab[])) => {
		if (typeof updater === "function") {
			setTabsState((prev) => {
				const next = (updater as (prev: Tab[]) => Tab[])(prev);
				tabsRef.current = next;
				return next;
			});
			return;
		}
		tabsRef.current = updater;
		setTabsState(updater);
	}, []);

	const setActiveTab = useCallback((id: string | null) => {
		activeTabRef.current = id;
		setActiveTabState(id);
	}, []);

	const notifyDirtyState = useCallback((path: string, dirty: boolean) => {
		if (typeof window === "undefined") return;
		window.dispatchEvent(
			new CustomEvent("editor-dirty-changed", {
				detail: { path, dirty, source: "front-react:ide" },
			}),
		);
	}, []);

	// biome-ignore lint/correctness/useExhaustiveDependencies: the editor must reset entirely when the container changes.
	useEffect(() => {
		setTabs([]);
		setActiveTab(null);
		setEditorContentState("");
		tabsRef.current = [];
		tabContentRef.current = {};
		originalContentRef.current = {};
	}, [containerId, service, setActiveTab, setTabs]);

	const getService = useCallback(() => service, [service]);

	const updateTabContent = useCallback(
		(path: string, content: string, markSaved = false) => {
			if (markSaved) {
				originalContentRef.current[path] = content;
			}
			tabContentRef.current[path] = content;
			const original = originalContentRef.current[path];
			const isDirty = markSaved ? false : content !== original;
			let shouldNotify = false;
			setTabs((prev) =>
				prev.map((tab) => {
					if (tab.path !== path) {
						return tab;
					}
					if ((tab.isDirty ?? false) !== isDirty) {
						shouldNotify = true;
					}
					return { ...tab, isDirty };
				}),
			);
			if (shouldNotify) {
				notifyDirtyState(path, isDirty);
			}
		},
		[notifyDirtyState, setTabs],
	);

	const readFile = useCallback(
		async (path: string) => {
			const res = await getService().call<{ content?: string }>("read", { path });
			const content = typeof res?.content === "string" ? res.content : "";
			updateTabContent(path, content, true);
			return content;
		},
		[getService, updateTabContent],
	);

	const openFile = useCallback(
		async (path: string) => {
			const timestamp = Date.now();
			const {
				tabs: candidateTabs,
				activeId,
				reused: reusedFlag,
			} = getOrCreateTab(tabsRef.current, path, timestamp);
			const nextTabs = candidateTabs.map((tab) =>
				tab.id === activeId
					? { ...tab, isDirty: reusedFlag ? (tab.isDirty ?? false) : false }
					: tab,
			);
			setTabs(nextTabs);
			if (activeId) {
				setActiveTab(activeId);
			}
			const reused = reusedFlag;
			if (reused) {
				const cached = tabContentRef.current[path];
				if (typeof cached === "string") {
					setEditorContentState(cached);
					return;
				}
			}
			const content = await readFile(path);
			setEditorContentState(content);
		},
		[readFile, setActiveTab, setTabs],
	);

	const saveFile = useCallback(
		async (path: string, content: string) => {
			await getService().call("write", { path, content });
			updateTabContent(path, content, true);
		},
		[getService, updateTabContent],
	);

	const handleCloseTab = useCallback(
		(id: string) => {
			setTabs((prev) => {
				const closing = prev.find((tab) => tab.id === id);
				if (closing) {
					delete tabContentRef.current[closing.path];
					delete originalContentRef.current[closing.path];
				}
				const nextTabs = prev.filter((tab) => tab.id !== id);
				if (activeTabRef.current === id) {
					const nextActive = nextTabs[nextTabs.length - 1]?.id ?? nextTabs[0]?.id ?? null;
					setActiveTab(nextActive);
					if (nextActive) {
						const nextTab = nextTabs.find((tab) => tab.id === nextActive);
						if (nextTab) {
							const cached = tabContentRef.current[nextTab.path];
							if (typeof cached === "string") {
								setEditorContentState(cached);
							} else {
								void readFile(nextTab.path).then((content) => {
									if (activeTabRef.current === nextActive) {
										setEditorContentState(content);
									}
								});
							}
						}
					} else {
						setEditorContentState("");
					}
				}
				return nextTabs;
			});
		},
		[readFile, setActiveTab, setTabs],
	);

	const handleTabChange = useCallback(
		(id: string) => {
			setActiveTab(id);
			const tab = tabsRef.current.find((entry) => entry.id === id);
			if (!tab) return;
			const cached = tabContentRef.current[tab.path];
			if (typeof cached === "string") {
				setEditorContentState(cached);
				return;
			}
			void readFile(tab.path).then((content) => {
				if (activeTabRef.current === id) {
					setEditorContentState(content);
				}
			});
		},
		[readFile, setActiveTab],
	);

	const handleEditorContentChange = useCallback(
		(value: string) => {
			setEditorContentState(value);
			const activeId = activeTabRef.current;
			if (!activeId) return;
			const tab = tabsRef.current.find((entry) => entry.id === activeId);
			if (!tab) return;
			updateTabContent(tab.path, value, false);
		},
		[updateTabContent],
	);

	const saveActiveFile = useCallback(async () => {
		let activeId = activeTabRef.current;
		if (!activeId && tabsRef.current.length > 0) {
			activeId = tabsRef.current[tabsRef.current.length - 1]?.id ?? null;
			if (activeId) {
				setActiveTab(activeId);
			}
		}
		if (!activeId) return;
		const tab = tabsRef.current.find((entry) => entry.id === activeId);
		if (!tab) return;
		const contentToSave = editorContent;
		tabContentRef.current[tab.path] = contentToSave;
		await saveFile(tab.path, contentToSave);
	}, [editorContent, saveFile, setActiveTab]);

	const reset = useCallback(() => {
		tabsRef.current = [];
		tabContentRef.current = {};
		originalContentRef.current = {};
		setTabsState([]);
		setActiveTabState(null);
		setEditorContentState("");
		activeTabRef.current = null;
	}, []);

	useEffect(() => {
		if (typeof window === "undefined") return;
		const handler = (event: Event) => {
			const detail = (event as CustomEvent<{ path?: string; dirty?: boolean; source?: string }>)
				.detail;
			if (!detail) return;
			if (detail.source === "front-react:ide") return;
			const path = typeof detail.path === "string" ? detail.path : "";
			if (!path) return;
			const dirty = Boolean(detail.dirty);
			setTabs((prev) => {
				let changed = false;
				const next = prev.map((tab) => {
					if (tab.path !== path) {
						return tab;
					}
					if ((tab.isDirty ?? false) === dirty) {
						return tab;
					}
					changed = true;
					return { ...tab, isDirty: dirty };
				});
				if (!changed) {
					return prev;
				}
				if (!dirty) {
					originalContentRef.current[path] =
						tabContentRef.current[path] ?? originalContentRef.current[path] ?? "";
				}
				return next;
			});
		};
		window.addEventListener("editor-dirty-changed", handler);
		return () => {
			window.removeEventListener("editor-dirty-changed", handler);
		};
	}, [setTabs]);

	return {
		tabs: tabsState,
		activeTab: activeTabState,
		editorContent,
		setEditorContent: handleEditorContentChange,
		openFile,
		saveFile,
		handleCloseTab,
		handleTabChange,
		saveActiveFile,
		reset,
	};
};
