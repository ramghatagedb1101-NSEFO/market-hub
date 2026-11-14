"""
Moves the fixed address ICICI knows (130.210.31.37) from market-hub-ip to market-hub-trader (owner, 14 Nov 2026), so
one Oracle machine does everything. Run by .github/workflows/oci-ip.yml:
    python infra/oci_move_ip.py check   # prints both machines' addresses and whether the fixed one can move
    python infra/oci_move_ip.py move    # moves it (the trader's temporary address is given up)
Only a RESERVED Oracle address can move between machines; a temporary (EPHEMERAL) one cannot, and then this stops
without changing anything. If the move fails part-way, the trader gets a temporary address back so it stays reachable.
Same settings as infra/oci_launch.py. Nothing secret is printed.
"""
import sys

import oci

import oci_launch
from oci_launch import config

FIXED = "130.210.31.37"


def primary_private_ip(compute, network, compartment: str, name: str):
    oci_launch.NAME = name
    inst = oci_launch.existing(compute, compartment)
    if not inst:
        raise SystemExit(f"no machine named {name}")
    for att in compute.list_vnic_attachments(compartment, instance_id=inst.id).data:
        vnic = network.get_vnic(att.vnic_id).data
        if vnic.is_primary:
            pip = [p for p in network.list_private_ips(vnic_id=vnic.id).data if p.is_primary][0]
            return inst, vnic, pip
    raise SystemExit(f"{name}: no primary network card")


def public_of(network, pip):
    try:
        return network.get_public_ip_by_private_ip_id(
            oci.core.models.GetPublicIpByPrivateIpIdDetails(private_ip_id=pip.id)).data
    except oci.exceptions.ServiceError as e:
        if e.status == 404:
            return None
        raise


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    cfg = config()
    comp = cfg["tenancy"]
    compute, network = oci.core.ComputeClient(cfg), oci.core.VirtualNetworkClient(cfg)
    fixed = network.get_public_ip_by_ip_address(oci.core.models.GetPublicIpByIpAddressDetails(ip_address=FIXED)).data
    _, _, t_pip = primary_private_ip(compute, network, comp, "market-hub-trader")
    t_pub = public_of(network, t_pip)
    on_trader = fixed.private_ip_id == t_pip.id
    print(f"fixed address {FIXED}: {fixed.lifetime}, on {'market-hub-trader' if on_trader else 'market-hub-ip'}")
    print(f"market-hub-trader now: {'the fixed address' if on_trader else (t_pub.lifetime if t_pub else 'no') + ' address'}")
    if action == "check" or on_trader:
        if on_trader:
            print("already moved")
        return 0
    if fixed.lifetime != "RESERVED":
        print("::error::the fixed address is temporary (EPHEMERAL): Oracle cannot move it. Nothing changed.")
        return 1
    if t_pub and t_pub.lifetime == "EPHEMERAL":
        network.delete_public_ip(t_pub.id)
        oci.wait_until(network, network.get_public_ip(t_pub.id), "lifecycle_state", "TERMINATED",
                       succeed_on_not_found=True, max_wait_seconds=180)
        print("trader's temporary address released")
    try:
        network.update_public_ip(fixed.id, oci.core.models.UpdatePublicIpDetails(private_ip_id=t_pip.id))
        oci.wait_until(network, network.get_public_ip(fixed.id), "lifecycle_state", "ASSIGNED", max_wait_seconds=300)
    except Exception:
        print("::error::move failed; giving the trader a temporary address back")
        if not public_of(network, t_pip):
            network.create_public_ip(oci.core.models.CreatePublicIpDetails(
                compartment_id=comp, lifetime="EPHEMERAL", private_ip_id=t_pip.id))
        raise
    print(f"moved: {FIXED} is now market-hub-trader's address")
    return 0


if __name__ == "__main__":
    sys.exit(main())
