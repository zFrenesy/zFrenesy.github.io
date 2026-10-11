"""Usage: python -m rp.site build --work WORK --out OUTPUT."""
import argparse
import json
import logging
from pathlib import Path
from rp.site.build import build_site


def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    build=sub.add_parser('build')
    build.add_argument('--work',type=Path,default=Path('.'))
    build.add_argument('--out',type=Path,required=True)
    build.add_argument('--base-url',default='https://we-solve-staging.github.io/')
    build.add_argument('--cache-dir',type=Path)
    build.add_argument('--packages-dir',type=Path)
    build.add_argument('--no-search',action='store_true',help='development only: skip search index')
    build.add_argument('--production',action='store_true')
    build.add_argument('--report',type=Path)
    build.add_argument('--link-status',type=Path,help='availability file from rp links sweep')
    args=parser.parse_args()
    report=build_site(args.work,args.out,base_url=args.base_url,cache_dir=args.cache_dir,packages_dir=args.packages_dir,staging=not args.production,search=not args.no_search,link_status=args.link_status)
    text=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(text)
    print(json.dumps({k:v for k,v in report.items() if k not in {'packages','reference_diagnostics'}},indent=2))


if __name__=='__main__': main()
