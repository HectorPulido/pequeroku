import { useCallback, useEffect, useRef, useState } from "react";
import TerminalWebService from "@/services/ide/TerminalWebService";
import type { TerminalTab } from "@/types/ide";

export function generateTerminalId(currentCount: number): string {
	return `s${currentCount + 1}`;
}

const buildNextId = (existing: TerminalTab[], desired?: string) => {
	if (desired && !existing.some((tab) => tab.id === desired)) {
		return desired;
	}
	let index = existing.length;
	let candidate = generateTerminalId(index);
	while (existing.some((tab) => tab.id === candidate)) {
		index += 1;
		candidate = generateTerminalId(index);
	}
	return candidate;
};

export const useTerminals = (containerId: string) => {
	const [terminalTabs, setTerminalTabs] = useState<TerminalTab[]>([]);
	const [activeTerminalId, setActiveTerminalId] = useState<string | null>(null);
	const tabsRef = useRef<TerminalTab[]>([]);
	const activeIdRef = useRef<string | null>(null);
	const lastCreatedIdRef = useRef<string | null>(null);

	const disposeTabs = useCallback((tabs: TerminalTab[]) => {
		tabs.forEach((tab) => {
			try {
				tab.fitAddon?.dispose();
			} catch (error) {
				console.error("terminal fit addon dispose failed", error);
			}
			tab.fitAddon = null;
			try {
				tab.terminal?.dispose();
			} catch (error) {
				console.error("terminal dispose failed", error);
			}
			try {
				tab.service?.close();
			} catch (error) {
				console.error("terminal service close failed", error);
			}
		});
	}, []);

	const createTab = useCallback(
		(id: string): TerminalTab => ({
			id,
			title: id,
			terminal: null,
			fitAddon: null,
			service: new TerminalWebService(containerId, id),
		}),
		[containerId],
	);

	const setTabs = useCallback((updater: (prev: TerminalTab[]) => TerminalTab[]) => {
		setTerminalTabs((prev) => {
			const next = updater(prev);
			tabsRef.current = next;
			return next;
		});
	}, []);

	const focusTab = useCallback((id: string | null) => {
		activeIdRef.current = id;
		setActiveTerminalId(id);
	}, []);

	const handleNewTerminal = useCallback(
		(desiredId?: string) => {
			setTabs((prev) => {
				const id = buildNextId(prev, desiredId);
				lastCreatedIdRef.current = id;
				const nextTabs = [...prev, createTab(id)];
				focusTab(id);
				return nextTabs;
			});
		},
		[createTab, focusTab, setTabs],
	);

	const handleCloseTerminal = useCallback(
		(id: string) => {
			setTabs((prev) => {
				const tab = prev.find((entry) => entry.id === id);
				if (tab) {
					try {
						tab.fitAddon?.dispose();
					} catch (error) {
						console.error("terminal fit addon dispose failed", error);
					}
					tab.fitAddon = null;
					tab.terminal?.dispose();
					tab.service?.close();
				}
				const nextTabs = prev.filter((entry) => entry.id !== id);
				if (activeIdRef.current === id) {
					focusTab(nextTabs[nextTabs.length - 1]?.id ?? nextTabs[0]?.id ?? null);
				}
				return nextTabs;
			});
		},
		[focusTab, setTabs],
	);

	useEffect(() => {
		activeIdRef.current = activeTerminalId;
	}, [activeTerminalId]);

	useEffect(() => {
		return () => {
			disposeTabs(tabsRef.current);
			tabsRef.current = [];
			lastCreatedIdRef.current = null;
		};
	}, [disposeTabs]);

	// biome-ignore lint/correctness/useExhaustiveDependencies: we must tear down terminals whenever the container id changes.
	useEffect(() => {
		if (tabsRef.current.length > 0) {
			disposeTabs(tabsRef.current);
			tabsRef.current = [];
		}
		setTerminalTabs([]);
		focusTab(null);
		lastCreatedIdRef.current = null;
	}, [containerId, disposeTabs, focusTab]);

	useEffect(() => {
		if (!tabsRef.current.length) {
			handleNewTerminal();
		}
	}, [handleNewTerminal]);

	const waitForConnection = useCallback(
		async (service: TerminalTab["service"] | undefined | null) => {
			if (!service) return false;
			if (service.hasConnection?.()) return true;
			for (let attempt = 0; attempt < 20; attempt += 1) {
				await new Promise((resolve) => setTimeout(resolve, 100));
				if (service.hasConnection?.()) {
					return true;
				}
			}
			return service.hasConnection?.() ?? false;
		},
		[],
	);

	const sendToActive = useCallback(
		async (input: string) => {
			const payload = input.endsWith("\r") ? input : `${input}\r`;
			if (!tabsRef.current.length) {
				handleNewTerminal();
				await new Promise((resolve) => setTimeout(resolve, 0));
			}

			let activeId = activeIdRef.current;
			if (!activeId) {
				activeId = tabsRef.current[0]?.id ?? lastCreatedIdRef.current ?? null;
				if (!activeId) return false;
				focusTab(activeId);
			}

			const tab = tabsRef.current.find((entry) => entry.id === activeId);
			if (!tab?.service) return false;

			const ready = await waitForConnection(tab.service);
			if (!ready) {
				return false;
			}

			try {
				tab.service.send(payload);
				tab.terminal?.focus();
				return true;
			} catch (error) {
				console.error("terminal send failed", error);
				return false;
			}
		},
		[focusTab, handleNewTerminal, waitForConnection],
	);

	const clearTerminal = useCallback((id: string | null) => {
		if (!id) return;
		const tab = tabsRef.current.find((entry) => entry.id === id);
		tab?.terminal?.clear();
	}, []);

	const resetTerminals = useCallback(() => {
		disposeTabs(tabsRef.current);
		tabsRef.current = [];
		setTerminalTabs([]);
		focusTab(null);
		lastCreatedIdRef.current = null;
		handleNewTerminal("s1");
	}, [disposeTabs, focusTab, handleNewTerminal]);

	return {
		terminalTabs,
		activeTerminalId,
		setActiveTerminalId: focusTab,
		handleNewTerminal,
		handleCloseTerminal,
		listSessions: () => tabsRef.current.map((tab) => tab.id),
		sendToActiveTerminal: sendToActive,
		clearTerminal,
		resetTerminals,
	};
};
