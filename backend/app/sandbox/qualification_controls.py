import argparse
import json
import tempfile
from pathlib import Path

from app.core.config import settings
from app.sandbox.node_attestation import NodeAttestationError, NodeAttestationVerifier
from app.sandbox.supply_chain import SupplyChainVerificationError, SupplyChainVerifier


def rejected(control: str, operation) -> dict[str, str]:
    try:
        operation()
    except (NodeAttestationError, SupplyChainVerificationError) as exc:
        return {"control": control, "status": "passed", "rejection": str(exc)[:1000]}
    raise RuntimeError(f"Negative control {control} was unexpectedly accepted")


def wrong_slsa_source(image: str) -> dict[str, str]:
    settings.sandbox_supply_chain_slsa_source = "https://invalid.example/codemate-negative-control"
    return rejected(
        "wrong-slsa-source",
        lambda: SupplyChainVerifier().verify(
            image=image,
            backend=settings.sandbox_execution_plane_backend,
        ),
    )


def unsigned_image(image: str) -> dict[str, str]:
    return rejected(
        "unsigned-image",
        lambda: SupplyChainVerifier().verify(
            image=image,
            backend="kubernetes",
        ),
    )


def wrong_node() -> dict[str, str]:
    expected = settings.sandbox_node_attestation_expected_node_id or "node"
    return rejected(
        "wrong-node-attestation",
        lambda: NodeAttestationVerifier().verify(node_id=f"negative-control-{expected}"),
    )


def tampered_rootfs() -> dict[str, str]:
    configured = Path(settings.sandbox_firecracker_rootfs_path or "")
    if not configured.is_file():
        raise RuntimeError("Firecracker rootfs is not configured on this execution node")
    with tempfile.TemporaryDirectory(prefix="codemate-rootfs-negative-") as directory:
        copy = Path(directory) / "rootfs.ext4"
        with configured.open("rb") as source:
            original = source.read(1)
        if not original:
            raise RuntimeError("Firecracker rootfs is empty")
        copy.write_bytes(bytes([original[0] ^ 0xFF]))
        settings.sandbox_firecracker_rootfs_path = str(copy)
        return rejected("tampered-rootfs", SupplyChainVerifier()._verify_rootfs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run fail-closed sandbox negative controls")
    parser.add_argument(
        "control",
        choices=("wrong-slsa-source", "unsigned-image", "wrong-node", "tampered-rootfs"),
    )
    parser.add_argument("--image")
    args = parser.parse_args()
    if args.control in {"wrong-slsa-source", "unsigned-image"} and not args.image:
        raise SystemExit("--image is required for this control")
    if args.control == "wrong-slsa-source":
        result = wrong_slsa_source(args.image)
    elif args.control == "unsigned-image":
        result = unsigned_image(args.image)
    elif args.control == "wrong-node":
        result = wrong_node()
    else:
        result = tampered_rootfs()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
