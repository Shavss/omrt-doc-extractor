"""Shared filters for classifying NumericalConstraints.

Both reconcile.py and massing.py need to know which height constraints
represent a base maximum building height (used to drive the primary mass
extrusion) versus additive deviations or peripheral exceptions (rooftop
equipment, antennas, fences, etc.). Putting the classifier here keeps
the two consumers in lockstep.

No municipality- or document-specific values are hardcoded. The classifier
inspects structural fields (`category`, `is_maximum`) and looks for generic
Dutch/English keywords that universally signal an additive or peripheral
rule rather than a base mass.
"""

from __future__ import annotations

from omrt_extractor.schemas import NumericalConstraint

# Name/id substrings that universally identify non-base height rules:
# additive deviations or heights for peripheral built elements that don't
# define the building mass envelope.
_NON_BASE_KEYWORDS: tuple[str, ...] = (
    "deviation",
    "overschrijding",
    "afwijking",
    "equipment",
    "installatie",
    "schoorsteen",
    "ventilatie",
    "dakopbouw",
    "antenne",
    "reclame",
    "mast",
    "erfafscheiding",
    "fence",
    "playground",
    "speeltoestel",
    "lichtmasten",
    "overige_bouwwerken",
)

# Condition substrings signalling the value is an additive delta above
# another base height, not a base value itself.
_ADDITIVE_DEVIATION_TOKENS: tuple[str, ...] = (
    "overschrijding",
    "extra hoogte",
    "above the maximum",
    "boven de maximale",
    "additional",
    "additive",
)


def is_base_height_constraint(constraint: NumericalConstraint) -> bool:
    """True if this height constraint represents a base maximum building height.

    A "base" max height drives the primary mass extrusion of a polygon. An
    additive deviation (e.g. "5 m above the maximum for chimneys") or a
    peripheral element max (fence, reclame mast, antenna) is NOT a base
    height and must not be used as a polygon's primary extrusion value.

    Base examples (return True):
      - 'max_height_sba1' (name 'Maximum bouwhoogte sba-1')
      - 'avg_height_sba1' (name 'Gemiddelde bouwhoogte sba-1')
      - 'max_hamerblok_base_height'

    NOT base (return False):
      - 'deviation_rooftop_equipment_height_increase'
      - 'max_height_schoorsteen'
      - 'max_height_reclamemasten_verkeer'
      - 'max_height_fence_groen'
      - Any constraint with category != 'height' or is_maximum != True
    """
    if constraint.category != "height" or not constraint.is_maximum:
        return False

    # A base building height must be expressed in metres. Storey counts,
    # ratios, and the like are unit-incompatible with a primary mass extrusion.
    if (constraint.unit or "").strip().lower() != "m":
        return False

    name_lower = (constraint.name or "").lower() + " " + constraint.id.lower()
    if any(kw in name_lower for kw in _NON_BASE_KEYWORDS):
        return False

    condition = (constraint.condition or "").lower()
    return not any(token in condition for token in _ADDITIVE_DEVIATION_TOKENS)
