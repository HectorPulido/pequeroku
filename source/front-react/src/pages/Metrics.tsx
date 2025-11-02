import type { TooltipItem } from "chart.js";
import {
	CategoryScale,
	Chart as ChartJS,
	Filler,
	Legend,
	LinearScale,
	LineElement,
	PointElement,
	Title,
	Tooltip,
} from "chart.js";
import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Line } from "react-chartjs-2";
import { useSearchParams } from "react-router-dom";
import Header from "@/components/Header";
import { METRICS } from "@/constants";
import { fetchContainerStatistics } from "@/services/containers";
import type { MetricData } from "@/types/metrics";

const readCssVar = (name: string, fallback: string) => {
	if (typeof window === "undefined") return fallback;
	const value = getComputedStyle(document.documentElement).getPropertyValue(name);
	return value.trim() || fallback;
};

type Palette = {
	text: string;
	muted: string;
	border: string;
	surface: string;
	surfaceAlt: string;
	accent: string;
	primary: string;
};

const readPalette = (): Palette => ({
	text: readCssVar("--color-text", "#e5e7eb"),
	muted: readCssVar("--color-text-muted", "#9ca3af"),
	border: readCssVar("--color-border", "#1f2937"),
	surface: readCssVar("--color-surface", "#111827"),
	surfaceAlt: readCssVar("--color-surface-alt", "#0f172a"),
	accent: readCssVar("--color-accent", "#06b6d4"),
	primary: readCssVar("--color-primary", "#4f46e5"),
});

const hexToRgba = (hex: string, alpha: number) => {
	const normalized = hex.replace("#", "");
	const bigint = Number.parseInt(normalized, 16);
	const r = (bigint >> 16) & 255;
	const g = (bigint >> 8) & 255;
	const b = bigint & 255;
	return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

ChartJS.register(
	CategoryScale,
	LinearScale,
	PointElement,
	LineElement,
	Title,
	Tooltip,
	Legend,
	Filler,
);

type StatusState = {
	ok: boolean;
	message: string;
};

const MAX_POINTS = METRICS.maxPoints ?? 300;

const Metrics: React.FC = () => {
	const [searchParams] = useSearchParams();
	const containerParam = searchParams.get("container");
	const containerId = containerParam ? Number.parseInt(containerParam, 10) : Number.NaN;
	const showHeader = !searchParams.has("showHeader");

	const [metricsData, setMetricsData] = useState<MetricData[]>([]);
	const [status, setStatus] = useState<StatusState>({
		ok: false,
		message: "Connecting...",
	});
	const [palette, setPalette] = useState<Palette>(() => readPalette());

	const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
	const abortRef = useRef<AbortController | null>(null);

	const stopPolling = useCallback(() => {
		if (pollTimerRef.current) {
			clearInterval(pollTimerRef.current);
			pollTimerRef.current = null;
		}
		if (abortRef.current) {
			abortRef.current.abort();
			abortRef.current = null;
		}
	}, []);

	const pollOnce = useCallback(async () => {
		if (!Number.isFinite(containerId)) return;

		abortRef.current?.abort();
		const controller = new AbortController();
		abortRef.current = controller;

		try {
			const stats = await fetchContainerStatistics(containerId, {
				signal: controller.signal,
				suppressLoader: true,
			});
			setMetricsData((prev) => {
				const next = [...prev, stats];
				if (next.length > MAX_POINTS) {
					next.splice(0, next.length - MAX_POINTS);
				}
				return next;
			});
			setStatus({ ok: true, message: "Connected" });
		} catch (error) {
			if (controller.signal.aborted) return;
			const message =
				error instanceof Error ? error.message : "Unable to fetch metrics from the container";
			setStatus({ ok: false, message });
		}
	}, [containerId]);

	const startPolling = useCallback(() => {
		if (!Number.isFinite(containerId)) return;
		stopPolling();
		pollTimerRef.current = window.setInterval(() => {
			void pollOnce();
		}, METRICS.pollMs);
	}, [containerId, pollOnce, stopPolling]);

	useEffect(() => {
		if (!Number.isFinite(containerId)) return;
		void pollOnce();
		startPolling();
		return () => {
			stopPolling();
		};
	}, [containerId, pollOnce, startPolling, stopPolling]);

	useEffect(() => {
		if (!Number.isFinite(containerId)) return;
		const handleVisibilityChange = () => {
			if (document.hidden) {
				stopPolling();
			} else {
				void pollOnce();
				startPolling();
			}
		};
		document.addEventListener("visibilitychange", handleVisibilityChange);
		return () => document.removeEventListener("visibilitychange", handleVisibilityChange);
	}, [containerId, pollOnce, startPolling, stopPolling]);

	useEffect(() => {
		return () => {
			stopPolling();
		};
	}, [stopPolling]);

	useEffect(() => {
		const handleThemeChange = () => {
			setPalette(readPalette());
		};
		handleThemeChange();
		window.addEventListener("themechange", handleThemeChange);
		return () => {
			window.removeEventListener("themechange", handleThemeChange);
		};
	}, []);

	const labels = useMemo(
		() =>
			metricsData.map((entry) =>
				new Date(entry.timestamp).toLocaleTimeString("en-US", {
					hour: "2-digit",
					minute: "2-digit",
					second: "2-digit",
					hour12: true,
				}),
			),
		[metricsData],
	);

	const latestMetrics = metricsData.at(-1);
	const lastUpdated = latestMetrics ? new Date(latestMetrics.timestamp) : null;

	const chartOptions = useMemo(() => {
		const gridColor = hexToRgba(palette.border, 0.25);
		return {
			responsive: true,
			maintainAspectRatio: false,
			interaction: {
				mode: "index" as const,
				intersect: false,
			},
			plugins: {
				legend: {
					display: true,
					position: "top" as const,
					align: "start" as const,
					labels: {
						color: palette.muted,
						font: {
							size: 11,
							family: "system-ui",
						},
						boxWidth: 12,
						boxHeight: 12,
						padding: 10,
						usePointStyle: true,
					},
				},
				tooltip: {
					enabled: true,
					backgroundColor: palette.surfaceAlt,
					titleColor: palette.text,
					bodyColor: palette.muted,
					borderColor: palette.border,
					borderWidth: 1,
					padding: 8,
					displayColors: true,
					callbacks: {
						label: (context: TooltipItem<"line">) => {
							let label = context.dataset.label || "";
							if (label) {
								label += ": ";
							}
							if (context.parsed.y !== null) {
								if (context.dataset.label === "CPU %") {
									label += `${context.parsed.y.toFixed(2)}%`;
								} else if (context.dataset.label === "MiB") {
									label += `${context.parsed.y.toFixed(2)} MiB`;
								} else {
									label += context.parsed.y;
								}
							}
							return label;
						},
					},
				},
			},
			scales: {
				x: {
					grid: {
						color: gridColor,
						drawBorder: false,
					},
					ticks: {
						color: palette.muted,
						font: {
							size: 10,
						},
						maxRotation: 45,
						minRotation: 45,
					},
				},
				y: {
					grid: {
						color: gridColor,
						drawBorder: false,
					},
					ticks: {
						color: palette.muted,
						font: {
							size: 10,
						},
					},
				},
			},
		};
	}, [palette]);

	const panelStyle = useMemo(
		() => ({
			backgroundColor: palette.surface,
			border: `1px solid ${palette.border}`,
		}),
		[palette.border, palette.surface],
	);

	const createDataset = useCallback(
		(label: string, values: number[]) => ({
			label,
			data: values,
			borderColor: palette.accent,
			backgroundColor: hexToRgba(palette.accent, 0.12),
			borderWidth: 2,
			tension: 0.4,
			fill: true,
			pointRadius: 0,
			pointHoverRadius: 4,
			pointHoverBackgroundColor: palette.primary,
			pointHoverBorderColor: palette.surface,
			pointHoverBorderWidth: 2,
		}),
		[palette.accent, palette.primary, palette.surface],
	);

	const cpuData = {
		labels,
		datasets: [
			{
				...createDataset(
					"CPU %",
					metricsData.map((d) => d.cpu),
				),
			},
		],
	};

	const memoryData = {
		labels,
		datasets: [
			{
				...createDataset(
					"MiB",
					metricsData.map((d) => d.memory),
				),
			},
		],
	};

	const threadsData = {
		labels,
		datasets: [
			{
				...createDataset(
					"Threads",
					metricsData.map((d) => d.threads),
				),
			},
		],
	};

	if (!Number.isFinite(containerId)) {
		return (
			<div
				className="min-h-screen"
				style={{ backgroundColor: "var(--color-bg)", color: "var(--color-text)" }}
			>
				{showHeader ? <Header /> : null}
				<main className="p-6">
					<div
						className="rounded-lg p-6 text-sm"
						style={{
							backgroundColor: "var(--color-surface)",
							border: "1px solid var(--color-border)",
						}}
					>
						Provide a valid container id in the query string (e.g. <code>?container=123</code>).
					</div>
				</main>
			</div>
		);
	}

	return (
		<div
			className="min-h-screen"
			style={{ backgroundColor: "var(--color-bg)", color: "var(--color-text)" }}
		>
			{showHeader ? <Header /> : null}

			{/* Main Content */}
			<main className="p-6">
				{/* Status Bar */}
				<div className="flex justify-between items-center mb-8">
					<div className="flex items-center gap-2">
						<div className={`h-2 w-2 rounded-full ${status.ok ? "bg-green-500" : "bg-red-500"}`} />
						<span className="text-gray-300 text-sm">
							{status.ok ? status.message : `Disconnected — ${status.message}`}
						</span>
					</div>
					<span className="text-gray-400 text-sm">
						Updated:{" "}
						{lastUpdated
							? lastUpdated.toLocaleString("en-US", {
									month: "2-digit",
									day: "2-digit",
									year: "numeric",
									hour: "2-digit",
									minute: "2-digit",
									second: "2-digit",
									hour12: true,
								})
							: "—"}
					</span>
				</div>

				{/* Metrics Summary Cards */}
				<div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
					{/* CPU Card */}
					<div className="rounded-lg p-6" style={panelStyle}>
						<div className="text-gray-400 text-sm mb-2">CPU</div>
						<div className="text-white text-4xl font-bold mb-1">
							{(latestMetrics?.cpu || 0).toFixed(2)}%
						</div>
						<div className="text-gray-500 text-xs">cpu_percent</div>
					</div>

					{/* Memory Card */}
					<div className="rounded-lg p-6" style={panelStyle}>
						<div className="text-gray-400 text-sm mb-2">Memory RSS</div>
						<div className="text-white text-4xl font-bold mb-1">
							{(latestMetrics?.memory || 0).toFixed(2)} MiB
						</div>
						<div className="text-gray-500 text-xs">rss_mib</div>
					</div>

					{/* Threads Card */}
					<div className="rounded-lg p-6" style={panelStyle}>
						<div className="text-gray-400 text-sm mb-2">Threads</div>
						<div className="text-white text-4xl font-bold mb-1">{latestMetrics?.threads || 0}</div>
						<div className="text-gray-500 text-xs">num_threads</div>
					</div>
				</div>

				{/* Charts Grid */}
				<div className="space-y-6">
					{/* CPU Chart */}
					<div className="rounded-lg p-6" style={panelStyle}>
						<h3 className="text-gray-400 text-sm mb-4">CPU %</h3>
						<div className="h-64">
							<Line options={chartOptions} data={cpuData} />
						</div>
					</div>

					{/* Memory Chart */}
					<div className="rounded-lg p-6" style={panelStyle}>
						<h3 className="text-gray-400 text-sm mb-4">RSS (MiB)</h3>
						<div className="h-64">
							<Line options={chartOptions} data={memoryData} />
						</div>
					</div>

					{/* Threads Chart */}
					<div className="rounded-lg p-6" style={panelStyle}>
						<h3 className="text-gray-400 text-sm mb-4">Threads</h3>
						<div className="h-64">
							<Line options={chartOptions} data={threadsData} />
						</div>
					</div>
				</div>
			</main>
		</div>
	);
};

export default Metrics;
