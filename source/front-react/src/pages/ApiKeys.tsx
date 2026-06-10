import { Code, Key, LongArrowDownLeft, Plus, Trash, WarningTriangle } from "iconoir-react";
import type React from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import CopyButton from "@/components/ai/CopyButton";
import Button from "@/components/Button";
import Header from "@/components/Header";
import Modal from "@/components/Modal";
import { alertStore } from "@/lib/alertStore";
import { createApiKey, fetchMcpInfo, listApiKeys, revokeApiKey } from "@/services/apiKeys";
import type { ApiKey, ApiScope, McpInfo } from "@/types/apiKey";

const ALL_SCOPES: { value: ApiScope; hint: string }[] = [
	{ value: "read", hint: "inspect" },
	{ value: "exec", hint: "run code" },
	{ value: "admin", hint: "create / destroy" },
];

const formatWhen = (value: string | null): string => {
	if (!value) return "never";
	const date = new Date(value);
	return Number.isNaN(date.getTime()) ? "never" : date.toLocaleString();
};

const ConnRow: React.FC<{ label: string; value: string; href?: string }> = ({
	label,
	value,
	href,
}) => (
	<div className="flex items-center justify-between gap-3 border-b border-gray-800 py-2.5 last:border-0">
		<span className="text-xs uppercase tracking-wide text-gray-500">{label}</span>
		<span className="flex items-center gap-2 min-w-0">
			{href ? (
				<a
					href={href}
					target="_blank"
					rel="noreferrer"
					className="truncate font-mono text-xs text-indigo-300 hover:underline"
				>
					{value}
				</a>
			) : (
				<code className="truncate font-mono text-xs text-gray-200">{value}</code>
			)}
			<CopyButton text={value} />
		</span>
	</div>
);

const ApiKeys: React.FC = () => {
	const navigate = useNavigate();

	const [keys, setKeys] = useState<ApiKey[]>([]);
	const [mcp, setMcp] = useState<McpInfo | null>(null);
	const [loading, setLoading] = useState(true);
	const [creating, setCreating] = useState(false);
	const [name, setName] = useState("");
	const [scopes, setScopes] = useState<Record<ApiScope, boolean>>({
		read: true,
		exec: true,
		admin: false,
	});
	const [newKey, setNewKey] = useState<ApiKey | null>(null);

	const refresh = useCallback(async () => {
		try {
			const data = await listApiKeys();
			setKeys(data);
		} catch (error) {
			const message = error instanceof Error ? error.message : "Unable to load API keys";
			alertStore.push({ message, variant: "error" });
		}
	}, []);

	useEffect(() => {
		const bootstrap = async () => {
			setLoading(true);
			try {
				const [info] = await Promise.all([fetchMcpInfo(), refresh()]);
				setMcp(info);
			} catch {
				// individual errors already surfaced via alertStore
			} finally {
				setLoading(false);
			}
		};
		void bootstrap();
	}, [refresh]);

	const toggleScope = (scope: ApiScope) =>
		setScopes((current) => ({ ...current, [scope]: !current[scope] }));

	const selectedScopes = useMemo(
		() => ALL_SCOPES.map((s) => s.value).filter((s) => scopes[s]),
		[scopes],
	);

	const handleCreate = async () => {
		if (selectedScopes.length === 0) {
			alertStore.push({ message: "Pick at least one scope.", variant: "warning" });
			return;
		}
		setCreating(true);
		try {
			const created = await createApiKey(name.trim() || "api-key", selectedScopes);
			setNewKey(created);
			setName("");
			await refresh();
		} catch (error) {
			const message = error instanceof Error ? error.message : "Unable to create API key";
			alertStore.push({ message, variant: "error" });
		} finally {
			setCreating(false);
		}
	};

	const handleRevoke = async (key: ApiKey) => {
		if (
			typeof window !== "undefined" &&
			!window.confirm(`Revoke key "${key.name}"? Anything using it stops working.`)
		) {
			return;
		}
		try {
			await revokeApiKey(key.id);
			await refresh();
		} catch (error) {
			const message = error instanceof Error ? error.message : "Unable to revoke API key";
			alertStore.push({ message, variant: "error" });
		}
	};

	const mcpAddCommand = useMemo(() => {
		const url = mcp?.mcp_url ?? "<mcp-url>";
		const token = newKey?.token ?? "pk_...";
		return `claude mcp add --transport http pequeroku ${url} --header "Authorization: Bearer ${token}"`;
	}, [mcp, newKey]);

	return (
		<div className="min-h-screen bg-[#0B1220] text-gray-200">
			<Header>
				<Button
					variant="secondary"
					size="sm"
					icon={<LongArrowDownLeft className="h-4 w-4" />}
					onClick={() => navigate("/")}
				>
					Dashboard
				</Button>
			</Header>

			<main className="mx-auto max-w-4xl px-6 py-8">
				<div className="mb-6 flex items-center gap-3">
					<Key className="h-6 w-6 text-indigo-400" />
					<div>
						<h1 className="text-xl font-semibold text-white">API keys &amp; MCP</h1>
						<p className="text-sm text-gray-400">
							Drive PequeRoku from scripts, the SDK, or an MCP-capable agent.
						</p>
					</div>
				</div>

				{/* Connection details */}
				<section className="mb-6 rounded-xl border border-gray-800 bg-[#111827] p-5">
					<div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-gray-500">
						<Code className="h-4 w-4 text-indigo-400" />
						Connection details
					</div>
					{mcp ? (
						<div>
							<ConnRow label="MCP server" value={mcp.mcp_url} />
							<ConnRow label="REST API base" value={mcp.api_base} />
							<ConnRow label="OpenAPI / Swagger" value={mcp.swagger_url} href={mcp.swagger_url} />
						</div>
					) : (
						<p className="text-sm text-gray-500">Loading…</p>
					)}
					<p className="mt-3 text-xs text-gray-500">
						Authenticate with <code className="text-gray-300">Authorization: Bearer pk_…</code>.
						Create a key below to get a ready-to-paste agent command.
					</p>
				</section>

				{/* Create a key */}
				<section className="mb-6 rounded-xl border border-gray-800 bg-[#111827] p-5">
					<div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-gray-500">
						<Plus className="h-4 w-4 text-indigo-400" />
						Create a key
					</div>
					<label htmlFor="key-name" className="mb-1 block text-xs text-gray-400">
						Label
					</label>
					<input
						id="key-name"
						type="text"
						value={name}
						onChange={(event) => setName(event.target.value)}
						placeholder="e.g. my-laptop-agent"
						className="mb-3 w-full rounded-md border border-gray-700 bg-[#0B1220] px-3 py-2 text-sm text-gray-100 outline-none focus:border-indigo-500"
					/>
					<div className="mb-4 flex flex-wrap gap-4">
						{ALL_SCOPES.map((scope) => (
							<label
								key={scope.value}
								className="flex cursor-pointer items-center gap-2 text-sm text-gray-200"
							>
								<input
									type="checkbox"
									checked={scopes[scope.value]}
									onChange={() => toggleScope(scope.value)}
									className="h-4 w-4 accent-indigo-500"
								/>
								<span className="font-medium">{scope.value}</span>
								<span className="text-xs text-gray-500">— {scope.hint}</span>
							</label>
						))}
					</div>
					<Button
						variant="primary"
						size="sm"
						icon={<Plus className="h-4 w-4" />}
						disabled={creating}
						onClick={handleCreate}
					>
						{creating ? "Creating…" : "Create key"}
					</Button>
					<p className="mt-3 text-xs text-gray-500">
						Scopes are hierarchical: <code className="text-gray-300">read</code> &lt;{" "}
						<code className="text-gray-300">exec</code> &lt;{" "}
						<code className="text-gray-300">admin</code>.
					</p>
				</section>

				{/* Existing keys */}
				<section className="rounded-xl border border-gray-800 bg-[#111827] p-5">
					<div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-gray-500">
						<Key className="h-4 w-4 text-indigo-400" />
						Your keys
					</div>
					{loading ? (
						<div className="flex items-center gap-3 py-6 text-sm text-gray-400">
							<span className="h-4 w-4 animate-spin rounded-full border border-indigo-400 border-t-transparent" />
							Loading…
						</div>
					) : keys.length === 0 ? (
						<p className="py-4 text-sm text-gray-500">No keys yet. Create one above.</p>
					) : (
						<div className="overflow-x-auto">
							<table className="w-full text-left text-sm">
								<thead>
									<tr className="text-xs uppercase tracking-wide text-gray-500">
										<th className="py-2 pr-4 font-semibold">Prefix</th>
										<th className="py-2 pr-4 font-semibold">Label</th>
										<th className="py-2 pr-4 font-semibold">Scopes</th>
										<th className="py-2 pr-4 font-semibold">Last used</th>
										<th className="py-2 pr-4 font-semibold">Status</th>
										<th className="py-2"></th>
									</tr>
								</thead>
								<tbody>
									{keys.map((key) => (
										<tr key={key.id} className="border-t border-gray-800">
											<td className="py-2.5 pr-4 font-mono text-xs text-gray-300">
												pk_{key.prefix}_…
											</td>
											<td className="py-2.5 pr-4">{key.name}</td>
											<td className="py-2.5 pr-4 text-gray-400">{key.scopes.join(", ")}</td>
											<td className="py-2.5 pr-4 text-gray-500">{formatWhen(key.last_used_at)}</td>
											<td className="py-2.5 pr-4">
												{key.revoked ? (
													<span className="rounded-full border border-rose-500/60 px-2 py-0.5 text-[11px] text-rose-400">
														revoked
													</span>
												) : (
													<span className="rounded-full border border-emerald-500/60 px-2 py-0.5 text-[11px] text-emerald-400">
														active
													</span>
												)}
											</td>
											<td className="py-2.5 text-right">
												{!key.revoked ? (
													<Button
														variant="danger"
														size="sm"
														icon={<Trash className="h-4 w-4" />}
														onClick={() => handleRevoke(key)}
													>
														Revoke
													</Button>
												) : null}
											</td>
										</tr>
									))}
								</tbody>
							</table>
						</div>
					)}
				</section>
			</main>

			{/* New token — shown once */}
			<Modal
				isOpen={newKey !== null}
				onClose={() => setNewKey(null)}
				title="Your new API key"
				size="md"
			>
				<div className="space-y-4">
					<div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-amber-300">
						<WarningTriangle className="mt-0.5 h-4 w-4 shrink-0" />
						<p className="text-xs">
							Copy it now — it is shown <strong>only once</strong>. We store only its hash.
						</p>
					</div>

					<div>
						<div className="mb-1 flex items-center justify-between">
							<span className="text-xs uppercase tracking-wide text-gray-500">API key</span>
							<CopyButton text={newKey?.token ?? ""} label="Copy key" />
						</div>
						<pre className="overflow-x-auto rounded-md border border-gray-800 bg-[#0B1220] p-3 font-mono text-xs text-gray-100">
							{newKey?.token}
						</pre>
					</div>

					<div>
						<div className="mb-1 flex items-center justify-between">
							<span className="text-xs uppercase tracking-wide text-gray-500">
								Connect an agent (Claude Code)
							</span>
							<CopyButton text={mcpAddCommand} label="Copy command" />
						</div>
						<pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-md border border-gray-800 bg-[#0B1220] p-3 font-mono text-xs text-gray-100">
							{mcpAddCommand}
						</pre>
					</div>
				</div>
			</Modal>
		</div>
	);
};

export default ApiKeys;
