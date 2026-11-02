#!/usr/bin/env python3
import argparse
from pathlib import Path
from transcription_summary_core import make_client
from sermon_summary import process_sermon

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    client = make_client()

    for p in args.paths:
        path = Path(p)
        if path.is_file():
            process_sermon(client, path, args.overwrite)
        else:
            for txt in path.rglob("*.txt"):
                process_sermon(client, txt, args.overwrite)

if __name__ == "__main__":
    main()
