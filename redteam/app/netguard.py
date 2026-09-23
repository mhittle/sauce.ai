"""SSRF guard for researcher-supplied target URLs.

The service makes outbound requests to whatever URL a researcher enters,
so without this check it is an open proxy into the host's private network
(cloud metadata endpoint, internal services). Resolution happens at
validation time; a DNS-rebinding host could still flip after the check,
which is why the runner re-validates before every trial.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeTarget(ValueError):
    pass


def _is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_multicast or addr.is_reserved or addr.is_unspecified)


def check_url(url: str, allow_private: bool = False, resolver=socket.getaddrinfo) -> str:
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeTarget("target URL must be http(s) with a host")
    if allow_private:
        return url
    try:
        infos = resolver(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise UnsafeTarget(f"cannot resolve {parsed.hostname}") from exc
    ips = {info[4][0] for info in infos}
    if not ips or not all(_is_public(ip) for ip in ips):
        raise UnsafeTarget(f"{parsed.hostname} resolves to a non-public address")
    return url
