import type React from "react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { USE_MOCKS } from "@/config";
import { fetchCurrentUser } from "@/services/user";

interface ProtectedRouteProps {
	children: React.ReactElement;
}

const ProtectedRoute: React.FC<ProtectedRouteProps> = ({ children }) => {
	const navigate = useNavigate();
	const [ready, setReady] = useState(false);

	useEffect(() => {
		let cancelled = false;

		console.log("Use mocks", USE_MOCKS);
		if (USE_MOCKS) {
			return setReady(true);
		}

		const checkSession = async () => {
			try {
				await fetchCurrentUser();
				if (!cancelled) setReady(true);
			} catch {
				if (!cancelled) {
					navigate("/login", { replace: true });
				}
			}
		};
		checkSession();
		return () => {
			cancelled = true;
		};
	}, [navigate]);

	if (!ready) {
		return null;
	}

	return children;
};

export default ProtectedRoute;
