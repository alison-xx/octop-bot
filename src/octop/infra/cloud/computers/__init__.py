"""Octop Bot cloud computers: one Tencent Cloud AGS sandbox per Bot, billed by the minute."""

from octop.infra.errors import OctopError


class DiskBalanceInsufficient(OctopError):
    """The disk-charge endpoint explicitly reported insufficient balance for this operation."""
