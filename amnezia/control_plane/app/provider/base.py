from abc import ABC, abstractmethod


class VpnProvider(ABC):
    @abstractmethod
    def create_client(self, client_id: str, remark: str) -> tuple[str, str]:
        """Returns (provider_ref, config)."""

    @abstractmethod
    def revoke_client(self, provider_ref: str) -> None:
        """Disables or deletes a client in backend."""

    @abstractmethod
    def get_config(self, provider_ref: str) -> str:
        """Returns config text for client."""

    @abstractmethod
    def get_qr_svg(self, provider_ref: str) -> str:
        """Returns SVG QR representation of client config."""
