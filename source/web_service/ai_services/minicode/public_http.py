"""HTTP transport for URLs supplied by users and VM workspaces."""

import ipaddress
import socket
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter


_IPV6_TRANSITION_NETWORKS = tuple(
    ipaddress.ip_network(prefix)
    for prefix in ("64:ff9b::/96", "64:ff9b:1::/48", "2001::/32", "2002::/16")
)


def _public_ip(address):
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return _public_ip(address.ipv4_mapped)
        if address.is_site_local or any(
            address in network for network in _IPV6_TRANSITION_NETWORKS
        ):
            return False
    return address.is_global and not address.is_multicast and not address.is_reserved


def validate_public_url(url):
    """Validate the URL syntax and reject non-public literal destinations."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise requests.exceptions.InvalidURL("Invalid public URL") from exc
    if parts.scheme not in ("http", "https") or not host or parts.username is not None:
        raise requests.exceptions.InvalidURL(
            "Expected an HTTP(S) URL without credentials"
        )
    if port == 0 or "%" in host:
        raise requests.exceptions.InvalidURL("Invalid public URL")
    normalized_host = host.rstrip(".").lower()
    if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        raise requests.exceptions.InvalidURL("Loopback host blocked")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return parts
    if not _public_ip(address):
        raise requests.exceptions.InvalidURL("Non-public address blocked")
    return parts


class _PublicHTTPAdapter(HTTPAdapter):
    def send(self, request, **kwargs):
        # Keep our wire-level Host override out of Requests' redirect/cookie state.
        return super().send(request.copy(), **kwargs)

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        if proxies:
            raise requests.exceptions.InvalidURL("Proxies are disabled for public URLs")
        parts = validate_public_url(request.url)
        host_params, pool_kwargs = self.build_connection_pool_key_attributes(
            request, verify, cert
        )
        port = parts.port or (443 if parts.scheme == "https" else 80)
        try:
            addresses = [
                ipaddress.ip_address(info[4][0])
                for info in socket.getaddrinfo(
                    parts.hostname, port, type=socket.SOCK_STREAM
                )
            ]
        except (OSError, ValueError) as exc:
            raise requests.exceptions.ConnectionError(
                "Could not resolve public host"
            ) from exc
        if not addresses or any(not _public_ip(address) for address in addresses):
            raise requests.exceptions.InvalidURL("Non-public address blocked")

        # Connect only to a validated numeric address. Retain the requested
        # origin for HTTP virtual hosting, TLS SNI and certificate verification.
        host_params["host"] = str(addresses[0])
        request.headers["Host"] = parts.netloc
        if parts.scheme == "https":
            pool_kwargs["server_hostname"] = parts.hostname
            pool_kwargs["assert_hostname"] = parts.hostname.rstrip(".")
        return self.poolmanager.connection_from_host(
            **host_params, pool_kwargs=pool_kwargs
        )


def public_http_session():
    """Use the pinned connection policy for each request, including redirects."""
    session = requests.Session()
    session.trust_env = False
    session.mount("http://", _PublicHTTPAdapter())
    session.mount("https://", _PublicHTTPAdapter())
    return session
