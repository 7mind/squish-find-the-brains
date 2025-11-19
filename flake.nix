{
  description = "Reusable Nix flake for building sbt projects with lockfile-based dependency management";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    let
      # Library functions available for all systems
      lib = {
        # Build Coursier cache from a lockfile
        # Args:
        #   pkgs: nixpkgs package set
        #   lockfilePath: path to deps.lock.json
        # Returns: derivation containing the reconstructed cache
        mkCoursierCache = { pkgs, lockfilePath }:
          let
            depsLock = builtins.fromJSON (builtins.readFile lockfilePath);

            fetchDep = dep: pkgs.fetchurl {
              url = dep.url;
              sha256 = dep.sha256;
            };
          in
          pkgs.runCommand "coursier-cache" { } ''
            mkdir -p $out
            ${builtins.concatStringsSep "\n" (map (dep:
              let
                fetched = fetchDep dep;
                cachePath = builtins.replaceStrings ["://"] ["/"] dep.url;
                cacheDir = builtins.dirOf cachePath;
              in ''
                mkdir -p "$out/${cacheDir}"
                cp ${fetched} "$out/${cachePath}"
              ''
            ) depsLock.artifacts)}
          '';

        # Generate sbt setup configuration for use in custom derivations
        # Args:
        #   pkgs: nixpkgs package set
        #   coursierCache: derivation from mkCoursierCache
        #   jdk: JDK package to use (default: pkgs.jdk21)
        #   extraSbtOpts: additional SBT_OPTS
        # Returns: attrset with:
        #   setupScript: shell script to set up sbt environment (call before running sbt)
        #   nativeBuildInputs: packages needed for building
        #   JAVA_HOME: path to JDK
        mkSbtSetup =
          { pkgs
          , coursierCache
          , jdk ? pkgs.jdk21
          , extraSbtOpts ? ""
          }: {
            # Shell script to set up sbt environment - call this in your buildPhase
            setupScript = ''
              export HOME=$(mktemp -d)

              # Set up Coursier cache - sbt uses .cache/coursier/https/...
              mkdir -p $HOME/.cache
              cp -r ${coursierCache} $HOME/.cache/coursier
              chmod -R u+w $HOME/.cache/coursier

              # Configure sbt for offline mode
              export COURSIER_MODE=offline
              export COURSIER_CACHE=$HOME/.cache/coursier
              export SBT_OPTS="-Dsbt.offline=true -Dsbt.boot.directory=$HOME/.sbt/boot ${extraSbtOpts}"
            '';

            # Packages needed for sbt builds
            nativeBuildInputs = [
              pkgs.sbt
              jdk
              pkgs.which
            ];

            # Environment variable for JAVA_HOME
            JAVA_HOME = jdk;
          };

        # Create a development shell for sbt projects
        # Args:
        #   pkgs: nixpkgs package set
        #   jdk: JDK package to use (default: pkgs.jdk21)
        #   extraPackages: additional packages to include
        #   shellHook: additional shell hook commands
        mkSbtShell =
          { pkgs
          , jdk ? pkgs.jdk21
          , extraPackages ? [ ]
          , shellHook ? ""
          }:
          pkgs.mkShell {
            buildInputs = [
              pkgs.sbt
              jdk
              pkgs.coursier
              pkgs.python3
            ] ++ extraPackages;

            shellHook = ''
              export JAVA_HOME=${jdk}
              ${shellHook}
            '';
          };
      };
    in
    {
      # Export library functions
      lib = lib;

      # Also provide overlays for convenience
      overlays.default = final: prev: {
        sbt-nix = lib;
      };
    } //
    # Per-system outputs
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };

        # Package the lockfile generator script
        generateLockfile = pkgs.writeScriptBin "sbt-nix-lockfile" ''
          #!${pkgs.python3}/bin/python3
          ${builtins.readFile ./scripts/generate-lockfile.py}
        '';
      in
      {
        packages = {
          generate-lockfile = generateLockfile;
          default = generateLockfile;
        };

        # Apps for easy execution
        apps = {
          generate-lockfile = {
            type = "program";
            program = "${generateLockfile}/bin/sbt-nix-lockfile";
          };
          default = {
            type = "program";
            program = "${generateLockfile}/bin/sbt-nix-lockfile";
          };
        };

        # Development shell for working on this flake
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            python3
            sbt
            jdk21
            coursier
            nix
          ];
        };
      }
    );
}
