"""One adapter per state. Unknown codes are reported by lookup.py."""

from .az_roc import lookup as lookup_az
from .ca_cslb import lookup as lookup_ca
from .nj_dca import lookup as lookup_nj
from .pa_hic import lookup as lookup_pa

ADAPTERS = {
    "CA": lookup_ca,
    "AZ": lookup_az,
    "NJ": lookup_nj,
    "PA": lookup_pa,
}
