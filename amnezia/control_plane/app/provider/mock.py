from .base import VpnProvider


class MockProvider(VpnProvider):
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def create_client(self, client_id: str, remark: str) -> tuple[str, str]:
        provider_ref = f"mock-{client_id}"
        config = (
            "[Interface]\n"
            f"# {remark or 'horizonnetvpn-client'}\n"
            f"PrivateKey = mock-private-{client_id}\n"
            "Address = 10.8.0.2/32\n\n"
            "[Peer]\n"
            "PublicKey = mock-server-public-key\n"
            "Endpoint = vpn.example.com:51820\n"
            "AllowedIPs = 0.0.0.0/0, ::/0\n"
            "PersistentKeepalive = 25\n"
        )
        self._store[provider_ref] = config
        return provider_ref, config

    def revoke_client(self, provider_ref: str) -> None:
        # Keep config in store for audit/history, but mark revocation externally.
        if provider_ref not in self._store:
            raise KeyError(f"Unknown provider_ref: {provider_ref}")

    def get_config(self, provider_ref: str) -> str:
        config = self._store.get(provider_ref)
        if not config:
            raise KeyError(f"Unknown provider_ref: {provider_ref}")
        return config
