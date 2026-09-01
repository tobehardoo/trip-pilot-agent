"""DNS resolution contracts and public-address validation for acquisition."""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from typing import Protocol

import httpx

type IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class HostResolver(Protocol):
    async def resolve(self, hostname: str, port: int) -> tuple[str, ...]: ...


class SystemHostResolver:
    async def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        loop = asyncio.get_running_loop()
        results = await loop.getaddrinfo(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
        return tuple(dict.fromkeys(result[4][0] for result in results))


class HostResolutionError(RuntimeError):
    """Raised when DNS does not produce a usable address set."""


class UnsafeHostResolutionError(HostResolutionError):
    """Raised when any DNS result can reach a non-public network."""


@dataclass(frozen=True, slots=True)
class PublicHostResolution:
    hostname: str
    addresses: tuple[IpAddress, ...]

    @classmethod
    def from_strings(
        cls,
        *,
        hostname: str,
        addresses: tuple[str, ...],
    ) -> "PublicHostResolution":
        if not addresses:
            raise HostResolutionError(f"host did not resolve to any address: {hostname}")
        try:
            parsed = tuple(dict.fromkeys(ipaddress.ip_address(value) for value in addresses))
        except ValueError as error:
            raise HostResolutionError(f"host returned an invalid IP address: {hostname}") from error
        if any(not address.is_global or address.is_multicast for address in parsed):
            raise UnsafeHostResolutionError(
                f"host resolved to a non-public address: {hostname}"
            )
        return cls(hostname=hostname, addresses=parsed)

    @property
    def connection_address(self) -> str:
        return str(self.addresses[0])


@dataclass(frozen=True, slots=True)
class PinnedRequestTarget:
    network_url: str
    hostname: str


async def resolve_request_target(
    *,
    logical_url: str,
    resolver: HostResolver,
    pinned_hosts: dict[str, PublicHostResolution],
    timeout: float,
) -> PinnedRequestTarget:
    url = httpx.URL(logical_url)
    hostname = url.host
    resolution = pinned_hosts.get(hostname)
    if resolution is None:
        addresses = await asyncio.wait_for(
            resolver.resolve(hostname, 443),
            timeout=timeout,
        )
        resolution = PublicHostResolution.from_strings(
            hostname=hostname,
            addresses=addresses,
        )
        pinned_hosts[hostname] = resolution
    return PinnedRequestTarget(
        network_url=str(url.copy_with(host=resolution.connection_address)),
        hostname=hostname,
    )
