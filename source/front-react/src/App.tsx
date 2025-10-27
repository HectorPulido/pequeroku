import { useEffect } from "react";
import { Route, Routes, useLocation, useNavigate } from "react-router-dom";
import AlertStack from "@/components/AlertStack";
import LoaderOverlay from "@/components/LoaderOverlay";
import ProtectedRoute from "@/components/ProtectedRoute";
import Dashboard from "./pages/Dashboard";
import IDE from "./pages/IDE";
import Login from "./pages/Login";
import Metrics from "./pages/Metrics";
import "./App.css";

function App() {
	const navigate = useNavigate();
	const location = useLocation();

	useEffect(() => {
		const handleUnauthorized = () => {
			if (location.pathname !== "/login") {
				navigate("/login", { replace: true });
			}
		};
		window.addEventListener("auth:unauthorized", handleUnauthorized as EventListener);
		return () => {
			window.removeEventListener("auth:unauthorized", handleUnauthorized as EventListener);
		};
	}, [navigate, location.pathname]);

	return (
		<>
			<LoaderOverlay />
			<AlertStack />
			<Routes>
				<Route path="/login" element={<Login />} />
				<Route
					path="/"
					element={
						<ProtectedRoute>
							<Dashboard />
						</ProtectedRoute>
					}
				/>
				<Route
					path="/ide"
					element={
						<ProtectedRoute>
							<IDE />
						</ProtectedRoute>
					}
				/>
				<Route
					path="/metrics"
					element={
						<ProtectedRoute>
							<Metrics />
						</ProtectedRoute>
					}
				/>
			</Routes>
		</>
	);
}

export default App;
