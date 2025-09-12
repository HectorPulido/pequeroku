export function signatureFrom(data) {
	const norm = (data || [])
		.map((c) => ({
			id: c.id,
			status: c.status,
			created_at: c.created_at,
			name: c.name,
		}))
		.sort((a, b) => String(a.id).localeCompare(String(b.id)));
	return JSON.stringify(norm);
}
export const capitalizeFirstLetter = (s) =>
	s ? s[0].toUpperCase() + s.slice(1) : s;
