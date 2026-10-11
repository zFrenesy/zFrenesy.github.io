import argparse
import sys
from pathlib import Path

from rp.contribute.kit import render_kit, write_kit

parser = argparse.ArgumentParser(prog="python -m rp.contribute.kit", description="write the agent kit into a research repository checkout")
parser.add_argument("--out", required=True, help="research repository checkout")
parser.add_argument("--research", required=True, help="OWNER/NAME of the research repository")
parser.add_argument("--platform", required=True, help="OWNER/NAME of the platform repository")
parser.add_argument("--ref", required=True, help="full platform commit SHA")
parser.add_argument("--site", required=True, help="site URL with a trailing slash")
args = parser.parse_args()
try:
    files = render_kit(research=args.research, platform=args.platform, ref=args.ref, site_url=args.site)
except ValueError as exc:
    print(f"error: {exc}", file=sys.stderr)
    sys.exit(1)
for path in write_kit(Path(args.out), files):
    print(path)
