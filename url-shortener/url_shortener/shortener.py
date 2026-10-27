"""
Short code generation and Base62 encoding utilities.
"""

import secrets
import string

# Standard Base62 alphabet: 10 digits + 26 lowercase + 26 uppercase
BASE62_ALPHABET = string.digits + string.ascii_lowercase + string.ascii_uppercase
DEFAULT_CODE_LENGTH = 6


def generate_short_code(length: int = DEFAULT_CODE_LENGTH) -> str:
    """
    Generates a cryptographically secure random Base62 short code.
    Using 6 characters provides 62^6 = 56,800,235,584 unique combinations,
    making accidental collision highly improbable for small-to-medium datasets.
    """
    return "".join(secrets.choice(BASE62_ALPHABET) for _ in range(length))
