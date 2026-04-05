class Cerebrofy < Formula
  desc "AI-ready codebase indexer with hybrid graph + vector search"
  homepage "https://github.com/cerebrofy/cerebrofy"
  url "__URL__"
  sha256 "__SHA256__"
  version "__VERSION__"

  bottle :unneeded

  def install
    bin.install "cerebrofy"
    (share/"cerebrofy").install "queries" if File.directory?("queries")
  end

  test do
    system "#{bin}/cerebrofy", "--version"
  end
end
