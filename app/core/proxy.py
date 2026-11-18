"""Resolve forwarded addresses only across explicitly trusted proxy hops."""
from ipaddress import ip_address, ip_network
from app.core.config import settings


def client_ip(request):
    peer = request.client.host if request.client else "unknown"
    networks = [ip_network(value.strip(), strict=False) for value in settings.TRUSTED_PROXY_CIDRS.split(",") if value.strip()]
    def trusted(value):
        try:
            address = ip_address(value)
            return any(address in network for network in networks)
        except ValueError:
            return False
    if not trusted(peer):
        return peer
    hops = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    current = peer
    for hop in reversed(hops):
        if not trusted(current):
            break
        try:
            current = str(ip_address(hop))
        except ValueError:
            return peer
    return current
