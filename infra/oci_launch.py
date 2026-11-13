"""
Get the free Oracle Arm machine for IBKR paper trading (13 Nov 2026). Mumbai has had no free capacity for
VM.Standard.A1.Flex ("Out of host capacity" for 4/24, 2/12 and 1/6), so .github/workflows/oci-launch.yml runs this every
few minutes until Oracle has room; "out of capacity" is a normal try-again, not a failure.

What it creates (Always Free only): market-hub-trader, VM.Standard.A1.Flex 4 OCPU / 24 GB, Ubuntu 24.04 for Arm, the
account's existing subnet (the one market-hub-ip uses), a public address, the same SSH key as market-hub-ip.
Exit codes: 0 = made or already there (the workflow then switches itself off), 75 = no capacity yet, 1 = a real error.

Settings come from the environment: OCI_TENANCY, OCI_USER, OCI_FINGERPRINT, OCI_REGION, OCI_KEY_FILE (the API private
key, written by the workflow from the OCI_API_KEY secret), OCI_SSH_PUBKEY. Nothing secret is printed.
"""
import os
import sys

import oci

NAME = "market-hub-trader"
SHAPE = "VM.Standard.A1.Flex"
OCPUS, MEMORY_GB = float(os.getenv("OCI_OCPUS") or 4), float(os.getenv("OCI_MEMORY_GB") or 24)
NO_CAPACITY = 75


def config() -> dict:
    cfg = {"user": os.environ["OCI_USER"], "fingerprint": os.environ["OCI_FINGERPRINT"],
           "tenancy": os.environ["OCI_TENANCY"], "region": os.environ.get("OCI_REGION") or "ap-mumbai-1",
           "key_file": os.environ["OCI_KEY_FILE"]}
    oci.config.validate_config(cfg)
    return cfg


def existing(compute, compartment: str):
    for i in oci.pagination.list_call_get_all_results(compute.list_instances, compartment).data:
        if i.display_name == NAME and i.lifecycle_state not in ("TERMINATED", "TERMINATING"):
            return i
    return None


def ubuntu_image(compute, compartment: str) -> str:
    imgs = compute.list_images(compartment, operating_system="Canonical Ubuntu", operating_system_version="24.04",
                               shape=SHAPE, sort_by="TIMECREATED", sort_order="DESC").data
    imgs = [i for i in imgs if "Minimal" not in i.display_name]
    if not imgs:
        raise RuntimeError("no Ubuntu 24.04 image for the Arm shape")
    return imgs[0].id


def subnet(network, compute, compartment: str) -> str:
    """The subnet market-hub-ip sits in (so both machines share one network and its rules)."""
    for i in oci.pagination.list_call_get_all_results(compute.list_instances, compartment).data:
        if i.display_name == "market-hub-ip" and i.lifecycle_state == "RUNNING":
            att = compute.list_vnic_attachments(compartment, instance_id=i.id).data
            if att:
                return att[0].subnet_id
    subs = network.list_subnets(compartment).data
    if len(subs) == 1:
        return subs[0].id
    raise RuntimeError(f"cannot tell which subnet to use ({len(subs)} subnets)")


def main() -> int:
    cfg = config()
    comp = cfg["tenancy"]
    compute = oci.core.ComputeClient(cfg)
    network = oci.core.VirtualNetworkClient(cfg)
    identity = oci.identity.IdentityClient(cfg)
    have = existing(compute, comp)
    if have:
        print(f"{NAME} already exists ({have.lifecycle_state}); nothing to do")
        return 0
    ad = identity.list_availability_domains(comp).data[0].name
    details = oci.core.models.LaunchInstanceDetails(
        compartment_id=comp, availability_domain=ad, display_name=NAME, shape=SHAPE,
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=OCPUS, memory_in_gbs=MEMORY_GB),
        source_details=oci.core.models.InstanceSourceViaImageDetails(image_id=ubuntu_image(compute, comp)),
        create_vnic_details=oci.core.models.CreateVnicDetails(subnet_id=subnet(network, compute, comp),
                                                              assign_public_ip=True),
        metadata={"ssh_authorized_keys": os.environ["OCI_SSH_PUBKEY"].strip()})
    try:
        inst = compute.launch_instance(details).data
    except oci.exceptions.ServiceError as e:
        if e.status in (500, 429) or "capacity" in (e.message or "").lower():
            print(f"no capacity yet for {OCPUS:g} OCPU / {MEMORY_GB:g} GB ({e.status}: {(e.message or '')[:80]})")
            return NO_CAPACITY
        raise
    print(f"created {NAME} ({inst.lifecycle_state}), {OCPUS:g} OCPU / {MEMORY_GB:g} GB in {ad}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
