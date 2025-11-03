import {
	Expand,
	GraphUp,
	Group,
	Play,
	RefreshDouble,
	Square,
	StatsUpSquare,
	Trash,
	User,
	Wrench,
} from "iconoir-react";
import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Button from "@/components/Button";
import Header from "@/components/Header";
import Modal from "@/components/Modal";
import CreateContainerModal from "@/components/modals/CreateContainerModal";
import { alertStore } from "@/lib/alertStore";
import { buildAppUrl, resolveAppBase } from "@/lib/appBase";
import { signatureFrom } from "@/lib/signature";
import { formatDate, isSmallScreen, statusTone } from "@/pages/Dashboard.helpers";
import {
	createContainer,
	deleteContainer,
	fetchContainerTypes,
	listContainers,
	powerOffContainer,
	powerOnContainer,
} from "@/services/containers";
import { fetchCurrentUser } from "@/services/user";
import type { Container, ContainerType } from "@/types/container";
import type { UserInfo } from "@/types/user";

const WARNING_STORAGE_KEY = "pequeroku:dashboard:tos-warning-shown";

const PLATFORM_WARNING = [
	"📜 Important Notice (Pequeroku)",
	"1. Pequeroku provides no warranty or official support. Help is community-based and not guaranteed.",
	"2. Illegal activity or behaviour that compromises the platform is forbidden.",
	"3. Nothing on Pequeroku is private; VMs are monitored for security.",
	"4. Administrators may revoke access at any time.",
	"5. Users are responsible for any misuse of the platform.",
	"6. Excessive resource usage (mining, spam, attacks) is prohibited and may be terminated without notice.",
	"7. Using Pequeroku implies acceptance of these terms.",
].join("\n");

type PendingAction = `${number}:${"start" | "stop" | "delete"}`;

const Dashboard: React.FC = () => {
	const appBase = useMemo(() => resolveAppBase(), []);
	const buildUrl = useCallback((path: string) => buildAppUrl(path, appBase), [appBase]);

	const [user, setUser] = useState<UserInfo | null>(null);
	const [containers, setContainers] = useState<Container[]>([]);
	const [isCreateModalOpen, setCreateModalOpen] = useState(false);
	const [containerTypes, setContainerTypes] = useState<ContainerType[] | null>(null);
	const [isLoadingTypes, setIsLoadingTypes] = useState(false);
	const [pendingActions, setPendingActions] = useState<Record<PendingAction, boolean>>({});
	const [consoleContainer, setConsoleContainer] = useState<Container | null>(null);
	const [metricsContainer, setMetricsContainer] = useState<Container | null>(null);
	const [isRefreshing, setIsRefreshing] = useState(false);
	const [hasLoadedContainers, setHasLoadedContainers] = useState(false);

	const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
	const abortRef = useRef<AbortController | null>(null);
	const mountedRef = useRef(true);
	const signatureRef = useRef<string>("");

	useEffect(() => {
		mountedRef.current = true;
		return () => {
			mountedRef.current = false;
			if (pollRef.current) clearInterval(pollRef.current);
			if (abortRef.current) abortRef.current.abort();
		};
	}, []);

	const refreshUser = useCallback(async () => {
		try {
			const info = await fetchCurrentUser();
			if (!mountedRef.current) return;
			setUser(info);
			if (!info.is_superuser) {
				const storage = typeof window !== "undefined" ? window.sessionStorage : null;
				if (storage && !storage.getItem(WARNING_STORAGE_KEY)) {
					alertStore.push({
						message: PLATFORM_WARNING,
						variant: "warning",
						dismissible: true,
					});
					storage.setItem(WARNING_STORAGE_KEY, "1");
				}
			}
		} catch (error) {
			const message = error instanceof Error ? error.message : "Unable to fetch user data";
			alertStore.push({ message, variant: "error" });
		}
	}, []);

	const refreshContainers = useCallback(async ({ lazy }: { lazy: boolean }) => {
		if (abortRef.current) {
			abortRef.current.abort();
		}
		const controller = new AbortController();
		abortRef.current = controller;
		if (!lazy) setIsRefreshing(true);

		try {
			const data = await listContainers({
				signal: controller.signal,
				suppressLoader: lazy,
			});
			if (!mountedRef.current) return;
			const sorted = [...data].sort((a, b) => a.id - b.id);
			const sig = signatureFrom(
				sorted.map((item) => ({
					id: item.id,
					status: item.status,
					desired_state: item.desired_state,
					updated_at: item.created_at,
					status_label: item.status_label,
				})),
			);
			if (lazy && sig === signatureRef.current) return;
			signatureRef.current = sig;
			setContainers(sorted);
			setHasLoadedContainers(true);
		} catch (error) {
			if (lazy) return;
			const message = error instanceof Error ? error.message : "Unable to fetch containers";
			alertStore.push({ message, variant: "error" });
		} finally {
			if (!lazy) setIsRefreshing(false);
		}
	}, []);

	useEffect(() => {
		const bootstrap = async () => {
			await refreshUser();
			await refreshContainers({ lazy: false });
		};
		bootstrap();
	}, [refreshUser, refreshContainers]);

	useEffect(() => {
		if (pollRef.current) {
			clearInterval(pollRef.current);
			pollRef.current = null;
		}
		pollRef.current = setInterval(() => {
			refreshContainers({ lazy: true });
		}, 5_000);
		return () => {
			if (pollRef.current) {
				clearInterval(pollRef.current);
				pollRef.current = null;
			}
		};
	}, [refreshContainers]);

	const ensureContainerTypes = async () => {
		if (containerTypes || isLoadingTypes) return;
		setIsLoadingTypes(true);
		try {
			const types = await fetchContainerTypes();
			if (!mountedRef.current) return;
			setContainerTypes(types);
		} catch (error) {
			const message = error instanceof Error ? error.message : "Unable to fetch container types";
			alertStore.push({ message, variant: "error" });
		} finally {
			setIsLoadingTypes(false);
		}
	};

	const setActionPending = (
		containerId: number,
		action: "start" | "stop" | "delete",
		value: boolean,
	) => {
		setPendingActions((current) => {
			const key = `${containerId}:${action}` as PendingAction;
			if (value) {
				return { ...current, [key]: true };
			}
			if (!(key in current)) return current;
			const next = { ...current };
			delete next[key];
			return next;
		});
	};

	const handlePowerOn = async (containerId: number) => {
		setActionPending(containerId, "start", true);
		try {
			await powerOnContainer(containerId);
			await refreshContainers({ lazy: false });
		} catch (error) {
			const message = error instanceof Error ? error.message : "Unable to start container";
			alertStore.push({ message, variant: "error" });
		} finally {
			setActionPending(containerId, "start", false);
		}
	};

	const handlePowerOff = async (containerId: number) => {
		setActionPending(containerId, "stop", true);
		try {
			await powerOffContainer(containerId);
			await refreshContainers({ lazy: false });
		} catch (error) {
			const message = error instanceof Error ? error.message : "Unable to stop container";
			alertStore.push({ message, variant: "error" });
		} finally {
			setActionPending(containerId, "stop", false);
		}
	};

	const handleDelete = async (container: Container) => {
		if (
			typeof window !== "undefined" &&
			!window.confirm(`Delete VM "${container.id} — ${container.name}"?`)
		) {
			return;
		}
		setActionPending(container.id, "delete", true);
		try {
			await deleteContainer(container.id);
			await refreshContainers({ lazy: false });
			await refreshUser();
		} catch (error) {
			const message = error instanceof Error ? error.message : "Unable to delete container";
			alertStore.push({ message, variant: "error" });
		} finally {
			setActionPending(container.id, "delete", false);
		}
	};

	const handleCreateContainer = async (typeId: number, name: string) => {
		try {
			await createContainer(
				name ? { container_type: typeId, container_name: name } : { container_type: typeId },
			);
			alertStore.push({ message: "Container queued for creation", variant: "success" });
			await refreshContainers({ lazy: false });
			await refreshUser();
		} catch (error) {
			const message = error instanceof Error ? error.message : "Unable to create container";
			alertStore.push({ message, variant: "error" });
			throw error;
		}
	};

	const handleOpenIde = (container: Container) => {
		if (isSmallScreen()) {
			window.open(buildUrl(`ide?containerId=${container.id}`), "_blank", "noopener,noreferrer");
			return;
		}
		setConsoleContainer(container);
	};

	const handleOpenMetrics = (container: Container) => {
		if (isSmallScreen()) {
			window.open(buildUrl(`metrics?container=${container.id}`), "_blank", "noopener,noreferrer");
			return;
		}
		setMetricsContainer(container);
	};

	const renderContainerCard = (container: Container, isOwner: boolean) => {
		const actionKey = (action: "start" | "stop" | "delete") =>
			pendingActions[`${container.id}:${action}` as PendingAction];
		const statusLabel = container.status_label ?? container.status;
		const shapeClass = isOwner ? "rounded-xl bg-[#111827]" : "rounded-lg bg-[#0F172A]";
		return (
			<div
				key={container.id}
				className={`flex flex-col border border-gray-800 p-5 text-sm shadow-lg shadow-indigo-900/10 transition hover:border-indigo-500/60 ${shapeClass}`}
			>
				<div className="mb-4 flex items-start justify-between">
					<div>
						<div className="text-sm font-semibold text-white">
							{container.id} — {container.name}
						</div>
						<div className="text-[11px] uppercase tracking-wide text-gray-400">
							{container.container_type_name} • {formatDate(container.created_at)}
						</div>
						{!isOwner ? (
							<div className="text-[11px] uppercase tracking-wide text-gray-500">
								Owner: {container.username}
							</div>
						) : null}
					</div>
					<span className={`text-xs font-semibold ${statusTone(statusLabel)}`}>{statusLabel}</span>
				</div>

				<div className="mt-auto flex flex-wrap gap-2">
					{container.status === "running" ? (
						<>
							<Button
								size="sm"
								onClick={() => handleOpenIde(container)}
								icon={<Wrench className="h-4 w-4" />}
							>
								Open
							</Button>
							<Button
								size="sm"
								variant="secondary"
								disabled={Boolean(actionKey("stop"))}
								onClick={() => handlePowerOff(container.id)}
								icon={<Square className="h-4 w-4" />}
							>
								{actionKey("stop") ? "Stopping..." : "Stop"}
							</Button>
							<Button
								size="sm"
								variant="secondary"
								onClick={() => handleOpenMetrics(container)}
								icon={<StatsUpSquare className="h-4 w-4" />}
							>
								Metrics
							</Button>
						</>
					) : (
						<Button
							size="sm"
							onClick={() => handlePowerOn(container.id)}
							disabled={Boolean(actionKey("start"))}
							icon={<Play className="h-4 w-4" />}
						>
							{actionKey("start") ? "Starting..." : "Start"}
						</Button>
					)}
					<Button
						size="sm"
						variant="danger"
						disabled={Boolean(actionKey("delete"))}
						onClick={() => handleDelete(container)}
						icon={<Trash className="h-4 w-4" />}
					>
						{actionKey("delete") ? "Deleting..." : "Delete"}
					</Button>
				</div>
			</div>
		);
	};

	const mine = useMemo(() => {
		if (!user) return [];
		return containers.filter((container) => container.username === user.username);
	}, [containers, user]);

	const others = useMemo(() => {
		if (!user) return [];
		return containers.filter((container) => container.username !== user.username);
	}, [containers, user]);

	const creditsLeft = user?.quota?.credits_left ?? 0;
	const canCreateContainer = Boolean(user?.has_quota && creditsLeft > 0);
	const newContainerLabel = user?.has_quota ? `New (${creditsLeft})` : "No quota";

	return (
		<div className="min-h-screen bg-[#0B1220] text-gray-200">
			<Header>
				<div className="flex items-center gap-2 rounded-md border border-gray-700 bg-[#0B1220] px-3 py-2">
					<User className="h-4 w-4 text-gray-400" />
					<div className="text-xs leading-tight text-gray-300">
						<div className="font-semibold text-white">
							Hello{" "}
							{user?.username
								? `${user.username.charAt(0).toUpperCase()}${user.username.slice(1)}`
								: "User"}
							!
						</div>
					</div>
				</div>

				<div className="relative">
					<details className="group">
						<summary className="flex cursor-pointer list-none items-center gap-2 rounded-md border border-gray-700 bg-[#0B1220] px-3 py-2 text-xs font-medium text-gray-300 transition hover:text-white">
							<GraphUp className="h-4 w-4" />
							Quota
						</summary>
						<div className="absolute right-0 z-20 mt-2 min-w-[20rem] rounded-md border border-gray-800 bg-[#111827] p-3 text-xs text-gray-300 shadow-xl">
							<pre className="max-h-48 overflow-auto whitespace-pre-wrap text-[11px] leading-snug text-gray-200">
								{JSON.stringify(user?.quota ?? {}, null, 2)}
							</pre>
						</div>
					</details>
				</div>

				<Button
					variant="secondary"
					size="sm"
					icon={
						isRefreshing ? (
							<span className="h-4 w-4 animate-spin rounded-full border border-indigo-400 border-t-transparent" />
						) : (
							<RefreshDouble className="h-4 w-4" />
						)
					}
					onClick={() => refreshContainers({ lazy: false })}
				>
					Refresh
				</Button>

				<Button
					variant="primary"
					size="sm"
					icon={<Wrench className="h-4 w-4" />}
					disabled={!canCreateContainer}
					onClick={() => {
						setCreateModalOpen(true);
						void ensureContainerTypes();
					}}
				>
					{newContainerLabel}
				</Button>
			</Header>

			<main className="px-6 py-8">
				<section className="mb-10">
					<div className="mb-4 flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-gray-500">
						<User className="h-4 w-4 text-indigo-400" />
						Containers
					</div>
					{!hasLoadedContainers ? (
						<div className="flex items-center justify-center gap-3 rounded-lg border border-gray-800 bg-[#111827] px-6 py-12 text-sm text-gray-400">
							<span className="h-4 w-4 animate-spin rounded-full border border-indigo-400 border-t-transparent" />
							Loading your containers...
						</div>
					) : mine.length === 0 ? (
						<div className="rounded-lg border border-dashed border-gray-700 bg-[#111827] px-6 py-10 text-center text-sm text-gray-400">
							You do not own any containers yet. Use the{" "}
							<strong className="text-indigo-300">New</strong> button to create one.
						</div>
					) : (
						<div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
							{mine.map((container) => renderContainerCard(container, true))}
						</div>
					)}
				</section>

				{others.length > 0 && (
					<section className="mt-12">
						<div className="mb-4 flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-gray-500">
							<Group className="h-4 w-4 text-indigo-400" />
							Other containers
						</div>
						<div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
							{others.map((container) => renderContainerCard(container, false))}
						</div>
					</section>
				)}
			</main>

			<CreateContainerModal
				isOpen={isCreateModalOpen}
				onClose={() => setCreateModalOpen(false)}
				credits={creditsLeft}
				types={containerTypes}
				isLoading={isLoadingTypes}
				onCreate={handleCreateContainer}
			/>

			<Modal
				isOpen={consoleContainer !== null}
				onClose={() => setConsoleContainer(null)}
				title={consoleContainer ? `${consoleContainer.id} — ${consoleContainer.name} - Editor` : ""}
				size="xl"
				padding=""
				headerActions={
					consoleContainer ? (
						<Button
							variant="secondary"
							size="sm"
							onClick={() => {
								if (!consoleContainer) return;
								window.open(
									buildUrl(`ide?containerId=${consoleContainer.id}`),
									"_blank",
									"noopener,noreferrer",
								);
							}}
						>
							<Expand />
						</Button>
					) : null
				}
			>
				{consoleContainer ? (
					<iframe
						title={`IDE-${consoleContainer.id}`}
						src={buildUrl(`ide?containerId=${consoleContainer.id}&showHeader=1`)}
						className="h-full w-full rounded-lg border border-gray-800"
					/>
				) : null}
			</Modal>

			<Modal
				isOpen={metricsContainer !== null}
				onClose={() => setMetricsContainer(null)}
				title={
					metricsContainer ? `${metricsContainer.id} — ${metricsContainer.name} - Metrics` : ""
				}
				padding=""
				size="xl"
				headerActions={
					metricsContainer ? (
						<Button
							variant="secondary"
							size="sm"
							onClick={() => {
								if (!metricsContainer) return;
								window.open(
									buildUrl(`metrics?container=${metricsContainer.id}`),
									"_blank",
									"noopener,noreferrer",
								);
							}}
						>
							<Expand />
						</Button>
					) : null
				}
			>
				{metricsContainer ? (
					<iframe
						title={`METRICS-${metricsContainer.id}`}
						src={buildUrl(`metrics?container=${metricsContainer.id}&showHeader=1`)}
						className="h-full w-full rounded-lg border border-gray-800"
					/>
				) : null}
			</Modal>
		</div>
	);
};

export default Dashboard;
