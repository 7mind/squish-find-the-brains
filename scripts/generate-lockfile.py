#!/usr/bin/env python3
"""
Two-phase lockfile generator for sbt projects.

Phase 1: Run sbt with network access to populate caches
Phase 2: Generate lockfile from populated caches with SHA256 hashes
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

NIX_BASE32_ALPHABET = "0123456789abcdfghijklmnpqrsvwxyz"
HASH_READ_CHUNK_SIZE = 65536


class SbtRun:
    """Configuration for a single sbt run."""

    def __init__(self, args: list[str]) -> None:
        if not args:
            raise ValueError("SbtRun requires at least one argument")
        self.args = args


class Config:
    """Configuration for lockfile generation."""

    def __init__(self, sbt_runs: list[SbtRun]) -> None:
        if not sbt_runs:
            raise ValueError("Config requires at least one sbt_runs entry")
        self.sbt_runs = sbt_runs

    @staticmethod
    def load(config_path: Path) -> "Config":
        """Load configuration from JSON file."""
        with open(config_path) as f:
            data = json.load(f)

        if "sbt_runs" not in data:
            raise ValueError("Config must contain 'sbt_runs' array")

        if not isinstance(data["sbt_runs"], list):
            raise ValueError("'sbt_runs' must be an array")

        sbt_runs = []
        for i, run_data in enumerate(data["sbt_runs"]):
            if not isinstance(run_data, dict):
                raise ValueError(f"sbt_runs[{i}] must be an object")
            if "args" not in run_data:
                raise ValueError(f"sbt_runs[{i}] must contain 'args' array")
            if not isinstance(run_data["args"], list):
                raise ValueError(f"sbt_runs[{i}].args must be an array")

            sbt_runs.append(SbtRun(run_data["args"]))

        return Config(sbt_runs)


def log(message: str) -> None:
    """Print message to stderr."""
    print(message, file=sys.stderr)


def _nix_base32(digest: bytes) -> str:
    """Encode raw digest bytes using Nix's little-endian base32 alphabet."""
    value = int.from_bytes(digest, "little")

    encoded_reversed = []
    while value > 0:
        value, remainder = divmod(value, 32)
        encoded_reversed.append(NIX_BASE32_ALPHABET[remainder])

    target_length = (len(digest) * 8 + 4) // 5  # ceil(bits / 5)
    encoded = "".join(reversed(encoded_reversed)).rjust(target_length, NIX_BASE32_ALPHABET[0])
    return encoded


def compute_sha256(path: Path) -> str:
    """Compute nix-compatible SHA256 hash (base32) for a regular file."""
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"Expected file for hashing, got: {resolved}")

    hasher = hashlib.sha256()
    with resolved.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(HASH_READ_CHUNK_SIZE), b""):
            hasher.update(chunk)

    return _nix_base32(hasher.digest())


def find_coursier_artifacts(cache_dir: Path) -> list[Path]:
    """Find all artifacts in Coursier cache."""
    artifacts = []

    # Coursier uses cache_dir/cache/https/... or cache_dir/https/...
    https_dirs = [
        cache_dir / "cache" / "https",
        cache_dir / "https",
    ]

    for https_dir in https_dirs:
        if not https_dir.exists():
            continue

        for path in https_dir.rglob("*"):
            # Include Maven artifacts (.jar, .pom) and Ivy artifacts (.xml for ivy.xml)
            if path.is_file() and path.suffix in (".jar", ".pom", ".xml"):
                artifacts.append(path)

    return sorted(artifacts)


def assert_no_ivy_artifacts(ivy_cache: Path) -> None:
    """Assert that no Ivy artifacts exist (sbt 1.3+ uses Coursier only)."""
    if not ivy_cache.exists():
        return

    artifacts = list(ivy_cache.rglob("*.jar")) + list(ivy_cache.rglob("*.pom"))
    if artifacts:
        raise AssertionError(
            f"Found {len(artifacts)} Ivy artifacts, but modern sbt should use Coursier only. "
            f"First artifact: {artifacts[0]}"
        )


def path_to_url(path: Path, cache_dir: Path) -> str:
    """Convert cache path to URL."""
    # Path structure: cache_dir/[cache/]https/repo.example.com/path/to/artifact
    relative = path.relative_to(cache_dir)
    parts = relative.parts

    # Find 'https' in path and take everything after it
    try:
        https_idx = parts.index("https")
        url_parts = parts[https_idx + 1:]
        return "https://" + "/".join(url_parts)
    except ValueError:
        raise ValueError(f"Unexpected path structure (no 'https'): {path}")


def generate_lockfile(project_dir: Path, config: Config, keep_temp: bool = False) -> dict:
    """Generate lockfile for the sbt project."""

    if keep_temp:
        temp_dir = tempfile.mkdtemp(prefix="squish-lockfile-")
        temp_home = Path(temp_dir)
        log(f"=== Debug mode: temp directory will be kept at {temp_home} ===")
    else:
        temp_context = tempfile.TemporaryDirectory()
        temp_dir = temp_context.__enter__()
        temp_home = Path(temp_dir)

    try:
        return _generate_lockfile_impl(project_dir, config, temp_home)
    finally:
        if not keep_temp:
            temp_context.__exit__(None, None, None)
        else:
            log(f"=== Temp directory preserved at: {temp_home} ===")


def _generate_lockfile_impl(project_dir: Path, config: Config, temp_home: Path) -> dict:
    """Implementation of lockfile generation."""
    # Set up isolated environment
    coursier_cache = temp_home / ".cache" / "coursier"
    sbt_global = temp_home / ".sbt"
    sbt_boot = sbt_global / "boot"

    coursier_cache.mkdir(parents=True)
    sbt_global.mkdir(parents=True)
    sbt_boot.mkdir(parents=True)

    # Environment for sbt
    env = os.environ.copy()
    env["HOME"] = str(temp_home)
    env["COURSIER_CACHE"] = str(coursier_cache)
    env["SBT_GLOBAL_BASE"] = str(sbt_global)
    env["SBT_BOOT_DIRECTORY"] = str(sbt_boot)
    env["SBT_OPTS"] = f"-Dsbt.boot.directory={sbt_boot} -Dsbt.coursier.home={coursier_cache}"

    log("=== Phase 1: Populating caches ===")
    log(f"Home: {temp_home}")

    # Clean target directories
    log("Cleaning target directory...")
    target_dir = project_dir / "target"
    project_target = project_dir / "project" / "target"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    if project_target.exists():
        shutil.rmtree(project_target)

    # Run sbt commands from config
    for i, sbt_run in enumerate(config.sbt_runs, 1):
        cmd = ["sbt", "--batch"] + sbt_run.args
        log(f"Running sbt ({i}/{len(config.sbt_runs)}): {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            env=env,
            cwd=project_dir,
            capture_output=True,
            text=True,
        )
        # Log launcher messages
        for line in result.stderr.split('\n'):
            if '[launcher]' in line:
                log(f"[info] {line.strip()}")
        if result.returncode != 0:
            log(f"sbt failed:\n{result.stdout}\n{result.stderr}")
            raise RuntimeError(f"sbt command failed: {' '.join(cmd)}")

    log("=== Phase 2: Generating lockfile ===")

    # Assert no Ivy artifacts (modern sbt uses Coursier only)
    ivy_cache = temp_home / ".ivy2" / "cache"
    assert_no_ivy_artifacts(ivy_cache)

    # Find Coursier artifacts
    coursier_artifacts = find_coursier_artifacts(coursier_cache)
    log(f"Found {len(coursier_artifacts)} Coursier artifacts")

    if not coursier_artifacts:
        raise AssertionError("No Coursier artifacts found - sbt may have failed to download dependencies")

    # Process Coursier artifacts
    entries = []
    for i, path in enumerate(coursier_artifacts, 1):
        url = path_to_url(path, coursier_cache)
        sha256 = compute_sha256(path)
        entries.append({
            "url": url,
            "sha256": sha256,
        })

        if i % 100 == 0:
            log(f"  Processed {i} artifacts...")

    # Sort entries by URL for deterministic output
    entries.sort(key=lambda e: e["url"])

    log(f"=== Done! Processed {len(entries)} artifacts ===")

    return {
        "version": 1,
        "artifacts": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate lockfile for sbt projects"
    )
    parser.add_argument(
        "config",
        type=Path,
        help="Path to JSON config file with sbt_runs definition"
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep temporary directory for debugging"
    )
    args = parser.parse_args()

    config = Config.load(args.config)
    project_dir = Path.cwd()
    lockfile = generate_lockfile(project_dir, config, keep_temp=args.keep_temp)

    # Output JSON to stdout
    json.dump(lockfile, sys.stdout, indent=2)
    print()  # Final newline


if __name__ == "__main__":
    main()
