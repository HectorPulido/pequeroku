export function getCSRF() {
	const match = document.cookie.match(/csrftoken=([^;]+)/);
	return match ? match[1] : "";
}
