"""Readable allocation names derived from the immutable creation request."""

import hashlib
from uuid import UUID

# Keep word order stable so creation retries resolve to the same allocation.
ADJECTIVES = (
    "bold",
    "calm",
    "cool",
    "fair",
    "gold",
    "keen",
    "kind",
    "mint",
    "neat",
    "sage",
    "soft",
    "tidy",
    "warm",
    "wild",
    "wise",
    "blue",
    "able",
    "airy",
    "apt",
    "avid",
    "cozy",
    "deft",
    "fast",
    "glad",
    "lush",
    "mild",
    "snug",
    "spry",
    "true",
    "zany",
)
ANIMALS = (
    "bison",
    "crane",
    "eagle",
    "finch",
    "gecko",
    "heron",
    "koala",
    "lynx",
    "otter",
    "panda",
    "quail",
    "robin",
    "swift",
    "tiger",
    "whale",
    "zebra",
    "bat",
    "bear",
    "boar",
    "deer",
    "dove",
    "duck",
    "elk",
    "emu",
    "fox",
    "hare",
    "ibis",
    "mole",
    "seal",
    "wolf",
)


def sandbox_name(request_id):
    # Four-letter adjectives, five-letter animals and the suffix fit 16 characters.
    digest = hashlib.sha256(UUID(str(request_id)).bytes).hexdigest()
    adjective = ADJECTIVES[int(digest[:4], 16) % len(ADJECTIVES)]
    animal = ANIMALS[int(digest[4:8], 16) % len(ANIMALS)]
    return f"{adjective}-{animal}-{digest[8:13]}"
