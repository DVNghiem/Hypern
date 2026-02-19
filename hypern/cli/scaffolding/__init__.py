"""scaffolding – modular project generators for ``hypern new``.

Each pattern is a module that exposes:
    LABEL: str                       – human-readable pattern name
    generate(name: str) -> Dict[str, str]  – relative-path→content mapping

Adding a new pattern:
    1. Create a new module in this package (e.g. ``my_pattern.py``).
    2. Register it in the ``PATTERNS`` dict below.
"""

from __future__ import annotations

import os
import sys
from typing import Callable, Dict, Tuple

# ── Pattern registry ─────────────────────────────────────────────
# key  →  (label, generate_function)
# Lazy imports keep startup fast; each module is imported once the
# user actually selects (or specifies) the pattern.

from .layered import LABEL as _l_label, generate as _l_gen
from .ddd import LABEL as _d_label, generate as _d_gen
from .hexagonal import LABEL as _h_label, generate as _h_gen
from .onion import LABEL as _o_label, generate as _o_gen
from .clean import LABEL as _c_label, generate as _c_gen
from .cqrs import LABEL as _q_label, generate as _q_gen
from .saga import LABEL as _s_label, generate as _s_gen
from .event_driven import LABEL as _e_label, generate as _e_gen
from .saga_event import LABEL as _se_label, generate as _se_gen

PATTERNS: Dict[str, Tuple[str, Callable[[str], Dict[str, str]]]] = {
    "layered": (_l_label, _l_gen),
    "ddd": (_d_label, _d_gen),
    "hexagonal": (_h_label, _h_gen),
    "onion": (_o_label, _o_gen),
    "clean": (_c_label, _c_gen),
    "cqrs": (_q_label, _q_gen),
    "saga": (_s_label, _s_gen),
    "event-driven": (_e_label, _e_gen),
    "saga-event": (_se_label, _se_gen),
}


# ── Interactive selection ────────────────────────────────────────


def _interactive_select() -> str:
    """Prompt the user to choose a pattern interactively."""
    print("\nAvailable architecture patterns:\n")
    keys = list(PATTERNS.keys())
    for idx, key in enumerate(keys, 1):
        label = PATTERNS[key][0]
        print(f"  {idx}. {label}  ({key})")

    print()
    while True:
        try:
            choice = input("Select a pattern [1-{}]: ".format(len(keys))).strip()
            num = int(choice)
            if 1 <= num <= len(keys):
                return keys[num - 1]
        except (ValueError, EOFError, KeyboardInterrupt):
            pass
        print("  Invalid choice – please enter a number between 1 and {}.".format(len(keys)))


# ── NewCommand ───────────────────────────────────────────────────


class NewCommand:
    """Handler for ``hypern new <name> [--pattern <key>]``."""

    def execute(self, args) -> None:
        name: str = args.name
        pattern_key: str | None = args.pattern
        directory: str = getattr(args, "directory", ".")

        if pattern_key is None:
            pattern_key = _interactive_select()

        if pattern_key not in PATTERNS:
            print(f"Error: unknown pattern '{pattern_key}'.")
            sys.exit(1)

        label, generate_fn = PATTERNS[pattern_key]
        project_dir = os.path.join(os.path.abspath(directory), name)

        if os.path.exists(project_dir):
            print(f"Error: directory '{project_dir}' already exists.")
            sys.exit(1)

        files = generate_fn(name)
        created = 0
        for rel_path, content in sorted(files.items()):
            full_path = os.path.join(project_dir, rel_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as fh:
                fh.write(content)
            created += 1

        print(f"\n  Project '{name}' created at {project_dir}")
        print(f"  Pattern: {label}")
        print(f"  Files:   {created}\n")
        print("  Next steps:")
        print(f"    cd {name}")
        print("    pip install -r requirements.txt")
        print("    python app.py")
        print()
