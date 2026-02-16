"""Helpers for formatting #roquescript metadata in event notes."""
from typing import Iterable, List

ROQUESCRIPT_INFO_MARKER = "[--#roquescript-info-below-]"


def build_roquescript_block(tag_line: str, description_lines: Iterable[str], timestamp: str) -> List[str]:
    """Return a sequence of lines that represent a single roquescript block."""
    block: List[str] = [tag_line]
    block.extend(description_lines)
    block.append(f"({timestamp})")
    block.append("#end")
    return block


def append_roquescript_block(existing_notes: str | None, block_lines: Iterable[str]) -> str:
    """Append a roquescript block, adding the marker if it does not already exist."""
    base = existing_notes or ""
    if base and not base.endswith("\n"):
        base += "\n"

    if ROQUESCRIPT_INFO_MARKER not in base:
        base += f"{ROQUESCRIPT_INFO_MARKER}\n"
    else:
        base += "\n"

    base += "\n".join(block_lines)
    return base
