import { Eye, EyeClosed, Lock, User } from "iconoir-react";
import type React from "react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import ThemeToggle from "@/components/ThemeToggle";
import { USE_MOCKS } from "@/config";
import { alertStore } from "@/lib/alertStore";
import { makeApi } from "@/services/api";
import { fetchCurrentUser } from "@/services/user";

const Login: React.FC = () => {
	const navigate = useNavigate();
	const [showPassword, setShowPassword] = useState(false);
	const [credentials, setCredentials] = useState({
		username: "",
		password: "",
	});
	const [isLoading, setIsLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		if (USE_MOCKS) return;
		let cancelled = false;
		const probe = async () => {
			try {
				await fetchCurrentUser();
				if (!cancelled) {
					navigate("/", { replace: true });
				}
			} catch {
				// stay on login
			}
		};
		probe();
		return () => {
			cancelled = true;
		};
	}, [navigate]);

	const handleSubmit = async (event: React.FormEvent) => {
		event.preventDefault();
		setIsLoading(true);
		setError(null);
		try {
			if (USE_MOCKS) {
				await new Promise((resolve) => setTimeout(resolve, 300));
			} else {
				const api = makeApi("/api");
				await api("/user/login/", {
					method: "POST",
					body: JSON.stringify({
						username: credentials.username,
						password: credentials.password,
					}),
				});
			}
			alertStore.push({ message: "Welcome back!", variant: "success" });
			navigate("/", { replace: true });
		} catch (err) {
			const message = err instanceof Error ? err.message : "Unable to sign in";
			setError(message);
			alertStore.push({ message, variant: "error" });
		} finally {
			setIsLoading(false);
		}
	};

	return (
		<div className="min-h-screen bg-[#0B1220] flex items-center justify-center p-4">
			{/* Background decorations */}
			<div className="absolute inset-0 overflow-hidden pointer-events-none">
				<div className="absolute top-20 left-20 w-72 h-72 bg-indigo-600 rounded-full mix-blend-multiply filter blur-3xl opacity-10 animate-blob"></div>
				<div className="absolute top-40 right-20 w-72 h-72 bg-cyan-500 rounded-full mix-blend-multiply filter blur-3xl opacity-10 animate-blob animation-delay-2000"></div>
				<div className="absolute -bottom-8 left-1/2 w-72 h-72 bg-indigo-600 rounded-full mix-blend-multiply filter blur-3xl opacity-10 animate-blob animation-delay-4000"></div>
			</div>

			<div className="absolute right-6 top-6 z-20">
				<ThemeToggle />
			</div>

			{/* Login Card */}
			<div className="w-full max-w-md relative z-10">
				<div className="overflow-hidden rounded-xl border border-gray-800 bg-[#111827] shadow-2xl">
					<div className="bg-gradient-to-r from-indigo-600 to-cyan-500 px-8 py-6">
						<h1 className="text-3xl font-bold text-white">PequeRoku</h1>
						<p className="text-sm text-indigo-100">Cloud Container Platform</p>
					</div>

					<form onSubmit={handleSubmit} className="space-y-5 px-8 py-6">
						<div>
							<label className="mb-2 block text-sm text-gray-400" htmlFor="login-username">
								Username
							</label>
							<div className="relative">
								<div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
									<User className="h-5 w-5 text-gray-500" />
								</div>
								<input
									id="login-username"
									type="text"
									name="username"
									value={credentials.username}
									onChange={(event) =>
										setCredentials((prev) => ({ ...prev, username: event.target.value }))
									}
									className="w-full rounded-lg border border-gray-700 bg-[#0B1220] py-3 pl-10 pr-4 text-sm text-white placeholder-gray-500 focus:border-indigo-600 focus:outline-none focus:ring-2 focus:ring-indigo-600 focus:ring-opacity-50"
									placeholder="Enter your username"
									required
								/>
							</div>
						</div>

						<div>
							<label className="mb-2 block text-sm text-gray-400" htmlFor="login-password">
								Password
							</label>
							<div className="relative">
								<div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
									<Lock className="h-5 w-5 text-gray-500" />
								</div>
								<input
									id="login-password"
									type={showPassword ? "text" : "password"}
									name="password"
									value={credentials.password}
									onChange={(event) =>
										setCredentials((prev) => ({ ...prev, password: event.target.value }))
									}
									className="w-full rounded-lg border border-gray-700 bg-[#0B1220] py-3 pl-10 pr-12 text-sm text-white placeholder-gray-500 focus:border-indigo-600 focus:outline-none focus:ring-2 focus:ring-indigo-600 focus:ring-opacity-50"
									placeholder="Enter your password"
									required
								/>
								<button
									type="button"
									onClick={() => setShowPassword((value) => !value)}
									className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-500 transition-colors hover:text-gray-300"
								>
									{showPassword ? <EyeClosed className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
								</button>
							</div>
						</div>

						{error && (
							<div className="rounded-md border border-rose-500/60 bg-rose-500/10 px-3 py-2 text-sm text-rose-100">
								{error}
							</div>
						)}

						<button
							type="submit"
							disabled={isLoading}
							className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-indigo-600 to-cyan-500 py-3 text-sm font-medium text-white transition-all hover:from-indigo-700 hover:to-cyan-600 disabled:cursor-not-allowed disabled:opacity-60"
						>
							{isLoading ? (
								<>
									<span className="h-5 w-5 animate-spin rounded-full border-2 border-white border-t-transparent" />
									<span>Signing in...</span>
								</>
							) : (
								"Sign in"
							)}
						</button>
					</form>
				</div>

				<p className="mt-6 text-center text-sm text-gray-500">
					Access to PequeRoku requires an existing account.
				</p>
			</div>

			<style>{`
        @keyframes blob {
          0%, 100% {
            transform: translate(0px, 0px) scale(1);
          }
          33% {
            transform: translate(30px, -50px) scale(1.1);
          }
          66% {
            transform: translate(-20px, 20px) scale(0.9);
          }
        }
        .animate-blob {
          animation: blob 7s infinite;
        }
        .animation-delay-2000 {
          animation-delay: 2s;
        }
        .animation-delay-4000 {
          animation-delay: 4s;
        }
      `}</style>
		</div>
	);
};

export default Login;
