import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchListeningPorts, type ListeningPort } from "@/services/ide/actions";

export type PortOption = { port: number; label: string };

export interface UsePreviewPorts {
	detectedPorts: ListeningPort[];
	selectedPort: number | null;
	/** Select a port as the user's explicit choice (sticks over auto-defaults). */
	setSelectedPort: (port: number | null) => void;
	portOptions: PortOption[];
	/** Re-run autodetection; resolves with the fresh list (handy for sync logic). */
	rescanPorts: () => Promise<ListeningPort[]>;
}

/**
 * Shared preview-port logic for the IDE editor and the AI preview browser.
 *
 * Given the container and its `config.json` port (the preferred default), it
 * autodetects the ports an app is listening on, derives the effective
 * `selectedPort` (config wins → a single detected port auto-selects → otherwise
 * the user must pick), and builds the labelled, deduped options for the selector.
 */
export function usePreviewPorts(containerId: string, configPort: number | null): UsePreviewPorts {
	const [detectedPorts, setDetectedPorts] = useState<ListeningPort[]>([]);
	const [selectedPort, setSelectedPortState] = useState<number | null>(null);
	// Once the user picks a port explicitly, auto-defaults stop overriding it.
	const userPickedRef = useRef(false);

	const setSelectedPort = useCallback((port: number | null) => {
		userPickedRef.current = true;
		setSelectedPortState(port);
	}, []);

	// Reset detection + selection whenever the active container changes.
	// biome-ignore lint/correctness/useExhaustiveDependencies: reset-on-container-change
	useEffect(() => {
		userPickedRef.current = false;
		setDetectedPorts([]);
		setSelectedPortState(null);
	}, [containerId]);

	const rescanPorts = useCallback(async () => {
		const ports = await fetchListeningPorts(containerId);
		setDetectedPorts(ports);
		return ports;
	}, [containerId]);

	// Auto-default (until the user picks): config.json wins; otherwise keep a still
	// valid auto-selection, else a single detected port, else nothing. config can
	// resolve after detection, so it must be able to override an earlier auto-pick.
	useEffect(() => {
		if (userPickedRef.current) return;
		setSelectedPortState((current) => {
			if (configPort !== null) return configPort;
			if (current !== null && detectedPorts.some((p) => p.port === current)) return current;
			if (detectedPorts.length === 1) return detectedPorts[0].port;
			return null;
		});
	}, [configPort, detectedPorts]);

	const portOptions = useMemo<PortOption[]>(() => {
		const labels = new Map<number, string>();
		if (configPort !== null) labels.set(configPort, `${configPort} · config.json`);
		for (const detected of detectedPorts) {
			if (labels.has(detected.port)) continue;
			labels.set(
				detected.port,
				detected.process ? `${detected.port} · ${detected.process}` : `${detected.port}`,
			);
		}
		return Array.from(labels.entries())
			.map(([port, label]) => ({ port, label }))
			.sort((a, b) => a.port - b.port);
	}, [configPort, detectedPorts]);

	return { detectedPorts, selectedPort, setSelectedPort, portOptions, rescanPorts };
}
