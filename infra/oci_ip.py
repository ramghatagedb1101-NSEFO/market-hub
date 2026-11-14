"""
Prints the public address of an Oracle machine by name (default market-hub-trader), for jobs that reach it over SSH
without keeping its address in this public repo (14 Nov 2026). Same settings as infra/oci_launch.py: OCI_TENANCY,
OCI_USER, OCI_FINGERPRINT, OCI_REGION, OCI_KEY_FILE.
    python infra/oci_ip.py [name]
"""
import sys

import oci

from oci_launch import config, existing  # noqa: E402  (same folder)


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "market-hub-trader"
    cfg = config()
    compute, network = oci.core.ComputeClient(cfg), oci.core.VirtualNetworkClient(cfg)
    import oci_launch
    oci_launch.NAME = name
    inst = existing(compute, cfg["tenancy"])
    if not inst:
        print(f"no machine named {name}", file=sys.stderr)
        return 1
    for att in compute.list_vnic_attachments(cfg["tenancy"], instance_id=inst.id).data:
        ip = network.get_vnic(att.vnic_id).data.public_ip
        if ip:
            print(ip)
            return 0
    print(f"{name} has no public address", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
