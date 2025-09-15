import { $ } from "../core/dom.js";
import { applyTheme } from "../core/themes.js";
import { hideHeader } from "../core/utils.js";

hideHeader();

const DEFAULT_POLL_MS = 1000;
const TIMEOUT_MS = 8000;
const MAX_POINTS = 300;

const urlParams = new URLSearchParams(window.location.search);
const container_id = urlParams.get("container");

let polling = true;
let pollTimer = null;
const endpoint = `/api/containers/${container_id}/statistics/`;

const series = {
	labels: [],
	cpu: [],
	rss: [],
	thr: [],
};

function formatTime(tsSec) {
	const d = new Date(tsSec * 1000);
	return d.toLocaleString();
}
function clampSeries() {
	["labels", "cpu", "rss", "thr"].forEach((k) => {
		if (series[k].length > MAX_POINTS)
			series[k].splice(0, series[k].length - MAX_POINTS);
	});
}
function setStatus(ok, msg) {
	const dot = $("#status-dot");
	dot.classList.toggle("err", !ok);
	$("#status-text").textContent = msg || (ok ? "Connected" : "Error");
}
function setKPIs(d) {
	$("#cpu-val").textContent = (d.cpu_percent ?? 0).toFixed(2);
	$("#mem-val").textContent = (
		d.rss_mib ?? (d.rss_bytes ? d.rss_bytes / (1024 * 1024) : 0)
	).toFixed(2);
	$("#thr-val").textContent = d.num_threads ?? "—";
	$("#last-updated").textContent = d.ts ? `Updated: ${formatTime(d.ts)}` : "";
}

Chart.defaults.font.family =
	"ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu";
Chart.defaults.color = getComputedStyle(
	document.documentElement,
).getPropertyValue("--text");
Chart.defaults.borderColor = "#263245";
function makeLineConfig(label) {
	return {
		type: "line",
		data: {
			labels: series.labels,
			datasets: [
				{
					label,
					data: [],
					tension: 0.25,
					fill: false,
					pointRadius: 0,
				},
			],
		},
		options: {
			responsive: true,
			maintainAspectRatio: false,
			scales: {
				x: { ticks: { autoSkip: true, maxTicksLimit: 8 } },
				y: { beginAtZero: true },
			},
			animation: false,
			plugins: {
				legend: { display: true },
				tooltip: { intersect: false, mode: "index" },
			},
		},
	};
}
const cpuChart = new Chart($("#cpuChart"), makeLineConfig("CPU %"));
const memChart = new Chart($("#memChart"), makeLineConfig("MiB"));
const thrChart = new Chart($("#thrChart"), makeLineConfig("Threads"));

function updateCharts() {
	cpuChart.data.datasets[0].data = series.cpu;
	memChart.data.datasets[0].data = series.rss;
	thrChart.data.datasets[0].data = series.thr;
	cpuChart.update();
	memChart.update();
	thrChart.update();
}

async function fetchWithTimeout(url, init = {}, timeoutMs = TIMEOUT_MS) {
	const controller = new AbortController();
	const id = setTimeout(() => controller.abort(), timeoutMs);
	try {
		const res = await fetch(url, {
			...init,
			signal: controller.signal,
		});
		clearTimeout(id);
		return res;
	} catch (e) {
		clearTimeout(id);
		throw e;
	}
}

async function pollOnce() {
	try {
		const headers = { accept: "application/json" };

		const res = await fetchWithTimeout(endpoint, { headers });
		if (!res.ok) throw new Error(`HTTP ${res.status}`);
		const data = await res.json();

		setKPIs(data);

		const ts = typeof data.ts === "number" ? data.ts : Date.now() / 1000;
		series.labels.push(new Date(ts * 1000).toLocaleTimeString());
		series.cpu.push(Number(data.cpu_percent ?? 0));
		const rssMiB =
			typeof data.rss_mib === "number"
				? data.rss_mib
				: typeof data.rss_bytes === "number"
					? data.rss_bytes / (1024 * 1024)
					: 0;
		series.rss.push(rssMiB);
		series.thr.push(Number(data.num_threads ?? 0));
		clampSeries();
		updateCharts();

		setStatus(true, "Connected");
	} catch (e) {
		setStatus(false, `Error: ${e.message}`);
	}
}

function startPolling() {
	stopPolling();
	polling = true;
	pollTimer = setInterval(pollOnce, DEFAULT_POLL_MS);

	pollOnce();
}
function stopPolling() {
	polling = false;
	if (pollTimer) {
		clearInterval(pollTimer);
		pollTimer = null;
	}
}

document.addEventListener("visibilitychange", () => {
	if (document.hidden) {
		if (polling) stopPolling();
	} else {
		if (!polling) startPolling();
	}
});

startPolling();
applyTheme();
