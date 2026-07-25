"""Guide command: surface the docs/ playbooks from the CLI itself.

An agent discovers the CLI through `--help`, not by browsing the repo, so the
help output has to point at the guides and the CLI has to be able to print them.
"""

import argparse
import sys
from pathlib import Path

GUIDE_DIR = Path(__file__).parent / 'docs'


def available_guides() -> list[tuple[str, str]]:
    """Return [(slug, first-heading)] for every guide in docs/."""
    guides = []
    for path in sorted(GUIDE_DIR.glob('*.md')):
        title = path.stem
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.startswith('# '):
                title = line[2:].strip()
                break
        guides.append((path.stem, title))
    return guides


def guide_hint() -> str:
    """One-line pointer for argparse epilogs, listing real guide slugs."""
    guides = available_guides()
    if not guides:
        return ''
    slugs = ', '.join(slug for slug, _ in guides)
    return (f'guides: {slugs}\n'
            f"  read one with: gmail guide <name>   (do this before building a "
            f'live doc-collaboration loop)')


def cmd_guide(args: argparse.Namespace) -> int:
    """List guides, or print one to stdout."""
    guides = available_guides()

    if not args.name:
        if not guides:
            print(f'No guides found in {GUIDE_DIR}', file=sys.stderr)
            return 1
        print('Available guides:\n')
        for slug, title in guides:
            print(f'  {slug:<24} {title}')
        print('\nPrint one with: gmail guide <name>')
        return 0

    path = GUIDE_DIR / f'{args.name}.md'
    if not path.exists():
        print(f"Error: no guide named '{args.name}'", file=sys.stderr)
        print('Available: ' + ', '.join(slug for slug, _ in guides), file=sys.stderr)
        return 1

    print(path.read_text(encoding='utf-8'))
    return 0
