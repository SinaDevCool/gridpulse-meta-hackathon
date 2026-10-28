"""Seal an already-built wheel; this command never builds or deploys."""
import argparse
import json
from pathlib import Path

from capacity_backtest.data_center.artifacts import release_manifest, write_artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--dependency-lock", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--engine-version", required=True)
    parser.add_argument("--calibration", action="append", default=[])
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    if args.wheel.suffix != ".whl":
        parser.error("--wheel must identify an already-built wheel")
    manifest = release_manifest(wheel=args.wheel, engine_version=args.engine_version,
        source_revision=args.source_revision, dependency_lock=args.dependency_lock,
        calibration_fingerprints=tuple(args.calibration))
    identity = write_artifact(args.output_directory, manifest)
    print(json.dumps({"release_fingerprint": identity, "manifest": str(args.output_directory / (identity + ".json"))}))


if __name__ == "__main__":
    main()
