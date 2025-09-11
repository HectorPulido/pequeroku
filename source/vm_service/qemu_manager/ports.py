import socket


def _pick_free_port() -> int:
    """
    Pick an ephemeral localhost TCP port (bound then released).
    """
    print("Picking a port...")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    print("Port selected", port)
    return port
