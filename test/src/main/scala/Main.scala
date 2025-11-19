package example

import upickle.default._

case class Message(text: String, timestamp: Long)

object Message {
  implicit val rw: ReadWriter[Message] = macroRW
}

object Main {
  def main(args: Array[String]): Unit = {
    val msg = Message("Hello from sbt-nix!", System.currentTimeMillis())
    val json = write(msg)

    println("sbt-nix test project built successfully!")
    println(s"Message as JSON: $json")

    // Demonstrate os-lib
    val cwd = os.pwd
    println(s"Current directory: $cwd")
  }
}
