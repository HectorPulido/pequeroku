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

	const chartOptions = {
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
					color: "#9CA3AF",
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
				backgroundColor: "#1F2937",
				titleColor: "#E5E7EB",
				bodyColor: "#9CA3AF",
				borderColor: "#374151",
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
					color: "#1F2937",
					drawBorder: false,
				},
				ticks: {
					color: "#6B7280",
					font: {
						size: 10,
					},
					maxRotation: 45,
					minRotation: 45,
				},
			},
			y: {
				grid: {
					color: "#1F2937",
					drawBorder: false,
				},
				ticks: {
					color: "#6B7280",
					font: {
						size: 10,
					},
				},
			},
		},
	};

	const cpuData = {
		labels,
		datasets: [
			{
				label: "CPU %",
				data: metricsData.map((d) => d.cpu),
				borderColor: "#06B6D4",
				backgroundColor: "rgba(6, 182, 212, 0.1)",
				borderWidth: 2,
				tension: 0.4,
				fill: true,
				pointRadius: 0,
				pointHoverRadius: 4,
				pointHoverBackgroundColor: "#06B6D4",
				pointHoverBorderColor: "#fff",
				pointHoverBorderWidth: 2,
			},
		],
	};

	const memoryData = {
		labels,
		datasets: [
			{
				label: "MiB",
				data: metricsData.map((d) => d.memory),
				borderColor: "#06B6D4",
				backgroundColor: "rgba(6, 182, 212, 0.1)",
				borderWidth: 2,
				tension: 0.4,
				fill: true,
				pointRadius: 0,
				pointHoverRadius: 4,
				pointHoverBackgroundColor: "#06B6D4",
				pointHoverBorderColor: "#fff",
				pointHoverBorderWidth: 2,
			},
		],
	};

	const threadsData = {
		labels,
		datasets: [
			{
				label: "Threads",
				data: metricsData.map((d) => d.threads),
				borderColor: "#06B6D4",
				backgroundColor: "rgba(6, 182, 212, 0.1)",
				borderWidth: 2,
				tension: 0.4,
				fill: true,
				pointRadius: 0,
				pointHoverRadius: 4,
				pointHoverBackgroundColor: "#06B6D4",
				pointHoverBorderColor: "#fff",
				pointHoverBorderWidth: 2,
			},
		],
	};

	if (!Number.isFinite(containerId)) {
		return (
			<div className="min-h-screen bg-[#0B1220] text-gray-200">
				{showHeader ? <Header /> : null}
				<main className="p-6">
					<div className="rounded-lg border border-gray-800 bg-[#111827] p-6 text-sm">
						Provide a valid container id in the query string (e.g. <code>?container=123</code>).
					</div>
				</main>
			</div>
		);
	}

	return (
		<div className="min-h-screen bg-[#0B1220]">
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
					<div className="bg-[#111827] border border-gray-800 rounded-lg p-6">
						<div className="text-gray-400 text-sm mb-2">CPU</div>
						<div className="text-white text-4xl font-bold mb-1">
							{(latestMetrics?.cpu || 0).toFixed(2)}%
						</div>
						<div className="text-gray-500 text-xs">cpu_percent</div>
					</div>

					{/* Memory Card */}
					<div className="bg-[#111827] border border-gray-800 rounded-lg p-6">
						<div className="text-gray-400 text-sm mb-2">Memory RSS</div>
						<div className="text-white text-4xl font-bold mb-1">
							{(latestMetrics?.memory || 0).toFixed(2)} MiB
						</div>
						<div className="text-gray-500 text-xs">rss_mib</div>
					</div>

					{/* Threads Card */}
					<div className="bg-[#111827] border border-gray-800 rounded-lg p-6">
						<div className="text-gray-400 text-sm mb-2">Threads</div>
						<div className="text-white text-4xl font-bold mb-1">{latestMetrics?.threads || 0}</div>
						<div className="text-gray-500 text-xs">num_threads</div>
					</div>
				</div>

				{/* Charts Grid */}
				<div className="space-y-6">
					{/* CPU Chart */}
					<div className="bg-[#111827] border border-gray-800 rounded-lg p-6">
						<h3 className="text-gray-400 text-sm mb-4">CPU %</h3>
						<div className="h-64">
							<Line options={chartOptions} data={cpuData} />
						</div>
					</div>

					{/* Memory Chart */}
					<div className="bg-[#111827] border border-gray-800 rounded-lg p-6">
						<h3 className="text-gray-400 text-sm mb-4">RSS (MiB)</h3>
						<div className="h-64">
							<Line options={chartOptions} data={memoryData} />
						</div>
					</div>

					{/* Threads Chart */}
					<div className="bg-[#111827] border border-gray-800 rounded-lg p-6">
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
