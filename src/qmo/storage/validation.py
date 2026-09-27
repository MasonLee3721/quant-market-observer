"""Validation utilities for storage identifiers, paths, and SHA-256 hashes."""

import re

IDENTIFIER_REGEX = re.compile(r"^[a-zA-Z0-9_-]+$")
HEX_SHA256_REGEX = re.compile(r"^[0-9a-fA-F]{64}$")


def validate_safe_identifier(value: str, field_name: str = "identifier") -> str:
    """Validate that value contains only safe characters (alphanumeric, underscore, hyphen).

    Prevents path traversal vulnerabilities.
    """
    if not value or not IDENTIFIER_REGEX.match(value):
        raise ValueError(
            f"Unsafe or invalid {field_name} '{value}'. "
            "Must be non-empty and contain only letters, numbers, underscores, or hyphens."
        )
    return value


def validate_sha256_hex(value: str, field_name: str = "SHA-256 hash") -> str:
    """Validate that value is a 64-character hexadecimal SHA-256 string."""
    if not value or not HEX_SHA256_REGEX.match(value):
        raise ValueError(
            f"Invalid {field_name} '{value}'. Must be a 64-character hex string."
        )
    return value.lower()
