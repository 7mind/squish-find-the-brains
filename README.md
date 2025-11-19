# squish-find-the-brains

Reusable Nix flake for building sbt projects with lockfile-based dependency management.

## Overview

This flake provides a two-phase approach to building sbt projects in Nix:

1. **Lockfile generation**: Run sbt with network access to discover dependencies, then generate a lockfile with SHA256 hashes
2. **Offline build**: Use the lockfile to fetch dependencies as content-addressed Nix store paths, then build in offline mode

This approach avoids fixed-output derivations (FODs) and provides fully reproducible builds.

## Quick Start

### 1. Add to your flake

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    squish-find-the-brains.url = "github:7mind/squish-find-the-brains";
  };

  outputs = { self, nixpkgs, flake-utils, squish-find-the-brains }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };

        coursierCache = squish-find-the-brains.lib.mkCoursierCache {
          inherit pkgs;
          lockfilePath = ./deps.lock.json;
        };

        sbtSetup = squish-find-the-brains.lib.mkSbtSetup {
          inherit pkgs coursierCache;
        };
      in
      {
        packages.default = pkgs.stdenv.mkDerivation {
          pname = "my-app";
          version = "1.0.0";
          src = ./.;

          nativeBuildInputs = sbtSetup.nativeBuildInputs;
          inherit (sbtSetup) JAVA_HOME;

          buildPhase = ''
            ${sbtSetup.setupScript}
            sbt --batch compile assembly
          '';

          installPhase = ''
            mkdir -p $out/lib
            cp target/scala-*/my-app.jar $out/lib/
          '';
        };
      }
    );
}
```

### 2. Create lockfile config

Create `lockfile-config.json`:

```json
{
  "sbt_runs": [
    {"args": [";reload plugins; update; reload return"]},
    {"args": ["+update", "+compile"]}
  ]
}
```

the `{"args": [";reload plugins; update; reload return"]},` line is especially important to make sure all the plugins were pulled in.

### 3. Generate lockfile

```bash
nix run github:7mind/squish-find-the-brains -- lockfile-config.json > deps.lock.json
```

### 4. Build

```bash
nix build
```

## API Reference

### `mkCoursierCache`

Builds a Coursier cache from a lockfile.

```nix
squish-find-the-brains.lib.mkCoursierCache {
  pkgs = pkgs;                    # required: nixpkgs package set
  lockfilePath = ./deps.lock.json; # required: path to lockfile
}
```

Returns a derivation containing the reconstructed Coursier cache.

### `mkSbtSetup`

Generates sbt setup configuration for use in custom derivations.

```nix
squish-find-the-brains.lib.mkSbtSetup {
  pkgs = pkgs;                    # required: nixpkgs package set
  coursierCache = coursierCache;  # required: from mkCoursierCache
  jdk = pkgs.jdk21;              # optional: JDK to use (default: jdk21)
  extraSbtOpts = "";             # optional: additional SBT_OPTS
}
```

Returns an attrset with:
- `setupScript`: shell script to set up sbt environment
- `nativeBuildInputs`: packages needed for building (sbt, jdk, which)
- `JAVA_HOME`: path to JDK

### `mkSbtShell`

Creates a development shell for sbt projects.

```nix
squish-find-the-brains.lib.mkSbtShell {
  pkgs = pkgs;                    # required: nixpkgs package set
  jdk = pkgs.jdk21;              # optional: JDK to use
  extraPackages = [];            # optional: additional packages
  shellHook = "";                # optional: additional shell hook
}
```

## Lockfile Format

The lockfile is a JSON file with the following structure:

```json
{
  "version": 1,
  "artifacts": [
    {
      "url": "https://repo1.maven.org/maven2/...",
      "sha256": "base32-encoded-hash"
    }
  ]
}
```

## Local Development

```bash
# Enter development shell
nix develop

# Generate lockfile
python scripts/generate-lockfile.py lockfile-config.json > deps.lock.json

# Build
nix build
```

## Testing

The `test/` directory contains a sample project demonstrating usage:

```bash
cd test

# Generate lockfile
nix develop ..#default --command python ../scripts/generate-lockfile.py lockfile-config.json > deps.lock.json

# Build with local squish-find-the-brains
nix build --override-input squish-find-the-brains path:..

# Run
./result/bin/squish-find-the-brains-test
```

## Alternatives

### sbt-derivation

[sbt-derivation](https://github.com/zaninime/sbt-derivation) is another approach to building sbt projects in Nix. It uses a fixed-output derivation (FOD) to fetch dependencies, which has different trade-offs:

**sbt-derivation (FOD approach)**:
- Simpler setup - no lockfile generation step
- Dependencies fetched in a single FOD
- Hash must be updated when dependencies change
- Less granular caching

**squish-find-the-brains (lockfile approach)**:
- Each dependency is a separate content-addressed derivation
- Better caching - unchanged dependencies are reused
- Lockfile provides visibility into exact dependencies
- Requires lockfile generation step

Choose based on your needs:
- Use **sbt-derivation** for simpler projects or when you prefer less setup
- Use **squish-find-the-brains** for better caching, reproducibility, and dependency visibility

## License

MIT
