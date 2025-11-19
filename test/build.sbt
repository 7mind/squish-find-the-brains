ThisBuild / scalaVersion := "3.3.3"
ThisBuild / version := "0.1.0"
ThisBuild / organization := "example"

lazy val root = (project in file("."))
  .settings(
    name := "sbt-nix-test",
    libraryDependencies ++= Seq(
      "com.lihaoyi" %% "os-lib" % "0.10.7",
      "com.lihaoyi" %% "upickle" % "3.3.1"
    ),
    assembly / mainClass := Some("example.Main"),
    assembly / assemblyJarName := "sbt-nix-test.jar",
    assembly / assemblyMergeStrategy := {
      case PathList("META-INF", xs @ _*) => MergeStrategy.discard
      case x => MergeStrategy.first
    }
  )
