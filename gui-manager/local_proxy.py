"""Compatibility shim for the retired unrestricted loopback proxy."""

PROXY_HOST = "127.0.0.1"
PROXY_PORT = 51180


def start_local_proxy(port: int = PROXY_PORT) -> bool:
    """The old listener is disabled; use the routed provider dispatcher."""
    return False


def stop_local_proxy() -> None:
    """No legacy listener is started."""
