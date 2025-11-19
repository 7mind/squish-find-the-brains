{
  description = "Test project for sbt-nix flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    # For local testing, use: nix build --override-input sbt-nix path:..
    # For CI, the workflow handles this
    sbt-nix.url = "github:pshirshov/sbt-nix";
  };

  outputs = { self, nixpkgs, flake-utils, sbt-nix }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };

        # Build Coursier cache from lockfile
        coursierCache = sbt-nix.lib.mkCoursierCache {
          inherit pkgs;
          lockfilePath = ./deps.lock.json;
        };

        # Get sbt setup configuration
        sbtSetup = sbt-nix.lib.mkSbtSetup {
          inherit pkgs coursierCache;
        };

        # Build the sbt project using stdenv.mkDerivation directly
        sbtBuild = pkgs.stdenv.mkDerivation {
          pname = "sbt-nix-test";
          version = "0.1.0";
          src = ./.;

          # Use nativeBuildInputs from sbtSetup
          nativeBuildInputs = sbtSetup.nativeBuildInputs;

          # Set JAVA_HOME from sbtSetup
          inherit (sbtSetup) JAVA_HOME;

          buildPhase = ''
            runHook preBuild

            # Set up sbt environment
            ${sbtSetup.setupScript}

            # Run sbt commands
            sbt --batch compile assembly

            runHook postBuild
          '';

          installPhase = ''
            mkdir -p $out/lib $out/bin

            # Copy compiled classes
            if [ -d target/scala-*/classes ]; then
              cp -r target/scala-*/classes $out/lib/
            fi

            # Copy assembly jar
            if [ -f target/scala-*/sbt-nix-test.jar ]; then
              cp target/scala-*/sbt-nix-test.jar $out/lib/

              # Create wrapper script
              cat > $out/bin/sbt-nix-test <<EOF
            #!${pkgs.bash}/bin/bash
            exec ${pkgs.jdk21}/bin/java -jar $out/lib/sbt-nix-test.jar "\$@"
            EOF
              chmod +x $out/bin/sbt-nix-test
            fi
          '';
        };
      in
      {
        packages = {
          default = sbtBuild;
          coursierCache = coursierCache;
        };

        # Development shell
        devShells.default = sbt-nix.lib.mkSbtShell {
          inherit pkgs;
          extraPackages = [ pkgs.nix ];
        };
      }
    );
}
