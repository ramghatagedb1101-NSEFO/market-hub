"""
A temporary research machine on the Oracle free-trial credits (owner, 15 Nov 2026: "yes, set up the research
machine"), so the research bot (trader/research.py) tests many ideas at once until the trial ends (~12 Dec 2026).

  market-hub-research: VM.Standard.E5.Flex (AMD, NOT Ampere: if the trial ended with more Ampere capacity than the
  Always Free allowance, Oracle would disable every Ampere machine, the trading machine included), 8 OCPU / 24 GB,
  Ubuntu 24.04, the trading machine's subnet and SSH key. Paid from the trial credits (Oracle price list, the higher
  rates seen: about US$0.04 an OCPU-hour and US$0.0026 a GB-hour -> ~US$0.38 an hour, ~US$220 to 9 Dec 2026, within
  the SGD 400 credits); a free-trial account is never charged unless the owner upgrades it, and when the credits or the
  trial end Oracle stops paid resources instead of billing.
  It is deleted on Wed 9 Dec 2026 (oci-research.yml action=delete, started by the trading machine's clock) at the latest.

    python infra/oci_research.py create|status|delete
Same settings as infra/oci_launch.py (OCI_* and OCI_SSH_PUBKEY). Exit 75 = no capacity yet (try again later).
"""
import os
import sys

import oci

import oci_launch
from oci_launch import config, existing, subnet

NAME, SHAPE = "market-hub-research", "VM.Standard.E5.Flex"
OCPUS, MEMORY_GB = float(os.getenv("RESEARCH_OCPUS") or 8), float(os.getenv("RESEARCH_GB") or 24)
DELETE_BY = "2026-12-09"
CLOUD_INIT = """#cloud-config
package_update: true
packages: [git, python3-venv, python3-pip]
runcmd:
  - mkdir -p /opt/trader/secrets /opt/trader/btcache
  - git clone https://github.com/ramghatagedb1101-NSEFO/market-hub.git /opt/trader/app
  - python3 -m venv /opt/trader/venv
  - /opt/trader/venv/bin/pip install --quiet -r /opt/trader/app/requirements.txt
  - chown -R ubuntu:ubuntu /opt/trader
  - touch /opt/trader/ready
"""


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    cfg = config()
    comp = cfg["tenancy"]
    compute, network = oci.core.ComputeClient(cfg), oci.core.VirtualNetworkClient(cfg)
    oci_launch.NAME = NAME
    have = existing(compute, comp)
    if action == "status":
        print(f"{NAME}: {have.lifecycle_state + ', ' + str(have.shape_config.ocpus) + ' OCPU' if have else 'none'}")
        return 0
    if action == "delete":
        if not have:
            print(f"{NAME}: none to delete")
            return 0
        compute.terminate_instance(have.id, preserve_boot_volume=False)
        print(f"{NAME}: deleted (boot disk too)")
        return 0
    if have:
        print(f"{NAME} already exists ({have.lifecycle_state})")
        return 0
    import base64
    from datetime import date
    from oci_launch import ubuntu_image
    if date.today().isoformat() >= DELETE_BY:
        raise SystemExit("past the delete-by date: not created")
    oci_launch.SHAPE = SHAPE
    identity = oci.identity.IdentityClient(cfg)
    ads = [a.name for a in identity.list_availability_domains(comp).data]
    details = oci.core.models.LaunchInstanceDetails(
        compartment_id=comp, availability_domain=ads[0], display_name=NAME, shape=SHAPE,
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=OCPUS, memory_in_gbs=MEMORY_GB),
        source_details=oci.core.models.InstanceSourceViaImageDetails(image_id=ubuntu_image(compute, comp),
                                                                     boot_volume_size_in_gbs=50),
        create_vnic_details=oci.core.models.CreateVnicDetails(subnet_id=subnet(network, compute, comp), assign_public_ip=True),
        metadata={"ssh_authorized_keys": os.environ["OCI_SSH_PUBKEY"].strip(),
                  "user_data": base64.b64encode(CLOUD_INIT.encode()).decode()},
        freeform_tags={"purpose": "research", "delete_by": DELETE_BY})
    try:
        inst = compute.launch_instance(details).data
    except oci.exceptions.ServiceError as e:
        if e.status in (500, 429) or "capacity" in (e.message or "").lower():
            print(f"no capacity yet ({e.status}: {(e.message or '')[:100]})")
            return 75
        raise
    print(f"created {NAME} ({inst.lifecycle_state}), {OCPUS:g} OCPU / {MEMORY_GB:g} GB, AMD; delete by {DELETE_BY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
