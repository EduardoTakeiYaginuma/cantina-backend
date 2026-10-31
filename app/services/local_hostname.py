"""
Nome de acesso na rede local (ex.: http://cantina.local:8080).

O backend anuncia o nome via mDNS (o mesmo mecanismo do ".local" de impressoras
e Macs). Assim os aparelhos da rede acessam o sistema pelo nome em vez do IP,
sem configurar nada no roteador. Funciona em Windows 10+, macOS, iPhone, Linux
e Android recentes.
"""
import logging
import os
import re
import socket
from typing import List, Optional

import ifaddr
from zeroconf import IPVersion, ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

logger = logging.getLogger(__name__)

DEFAULT_HOSTNAME = "cantina"
FRONTEND_PORT = int(os.getenv("FRONTEND_PORT", "8080"))
# No Docker o anúncio usaria o IP interno do container: desligue com LOCAL_HOSTNAME_ENABLED=false
ENABLED = os.getenv("LOCAL_HOSTNAME_ENABLED", "true").strip().lower() not in ("0", "false", "no", "nao", "não")
SETTING_KEY = "network_hostname"

_HOSTNAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_hostname(name: str) -> str:
    """'Cantina Shalom' -> 'cantina-shalom'. Remove '.local' e acentos simples."""
    name = (name or "").strip().lower()
    if name.endswith(".local"):
        name = name[: -len(".local")]
    for a, b in (("á", "a"), ("à", "a"), ("ã", "a"), ("â", "a"), ("é", "e"), ("ê", "e"), ("í", "i"),
                 ("ó", "o"), ("õ", "o"), ("ô", "o"), ("ú", "u"), ("ç", "c")):
        name = name.replace(a, b)
    name = re.sub(r"[\s_]+", "-", name)
    return name


def is_valid_hostname(name: str) -> bool:
    return bool(_HOSTNAME_RE.match(name))


def local_ipv4_addresses() -> List[str]:
    """IPs IPv4 desta máquina na rede (sem loopback e sem link-local)."""
    ips = []
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            if not isinstance(ip.ip, str):
                continue  # IPv6
            if ip.ip.startswith("127.") or ip.ip.startswith("169.254."):
                continue
            if ip.ip not in ips:
                ips.append(ip.ip)
    return ips


def preferred_ipv4() -> Optional[str]:
    """IP usado para sair para a rede (o mais provável de ser o da rede local)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        ips = local_ipv4_addresses()
        return ips[0] if ips else None


class LocalHostnameAnnouncer:
    def __init__(self):
        self._zc: Optional[AsyncZeroconf] = None
        self._info: Optional[ServiceInfo] = None
        self.hostname: Optional[str] = None
        self.addresses: List[str] = []
        self.error: Optional[str] = None

    @property
    def active(self) -> bool:
        return self._info is not None and self.error is None

    async def start(self, hostname: str):
        await self.stop()
        self.hostname = hostname
        self.error = None
        if not ENABLED:
            self.addresses = []
            self.error = "Nome .local desativado neste servidor (LOCAL_HOSTNAME_ENABLED=false). Use o endereço pelo IP."
            return
        # Anuncia só o IP da rede principal; adaptadores virtuais (WSL, VPN) confundem os aparelhos
        preferred = preferred_ipv4()
        addresses = [preferred] if preferred else local_ipv4_addresses()
        self.addresses = addresses
        if not addresses:
            self.error = "Nenhuma rede encontrada neste computador"
            return
        try:
            self._zc = AsyncZeroconf(ip_version=IPVersion.V4Only)
            self._info = ServiceInfo(
                "_http._tcp.local.",
                f"Cantina ({hostname})._http._tcp.local.",
                addresses=[socket.inet_aton(ip) for ip in addresses],
                port=FRONTEND_PORT,
                properties={"path": "/"},
                server=f"{hostname}.local.",
            )
            await self._zc.async_register_service(self._info, allow_name_change=True)
            logger.info("Nome na rede: http://%s.local:%s (%s)", hostname, FRONTEND_PORT, ", ".join(addresses))
        except Exception as exc:  # rede sem multicast, porta 5353 bloqueada etc.
            self.error = f"Não foi possível anunciar o nome na rede: {exc}"
            logger.warning(self.error)
            self._info = None

    async def stop(self):
        if self._zc is not None:
            try:
                if self._info is not None:
                    await self._zc.async_unregister_service(self._info)
                await self._zc.async_close()
            except Exception:
                pass
        self._zc = None
        self._info = None


announcer = LocalHostnameAnnouncer()
