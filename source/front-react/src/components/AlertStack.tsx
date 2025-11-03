import type React from "react";
import { useEffect, useState } from "react";
import AlertStackView from "@/components/AlertStackView";
import { type AlertMessage, alertStore } from "@/lib/alertStore";

const AlertStack: React.FC = () => {
	const [alerts, setAlerts] = useState<AlertMessage[]>([]);

	useEffect(() => {
		return alertStore.subscribe((event) => {
			if ("dismiss" in event) {
				setAlerts((current) => current.filter((item) => item.id !== event.id));
				return;
			}
			setAlerts((current) => [...current, event]);
		});
	}, []);

	return <AlertStackView alerts={alerts} onDismiss={alertStore.dismiss} />;
};

export default AlertStack;
