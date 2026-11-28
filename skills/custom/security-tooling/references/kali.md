# Package and release lookup

Identify the host where the evidence was collected. Record its OS release, architecture, executable path and installed package revision. On Arch, use `pacman -Qo /absolute/path/to/tool` and `pacman -Q package`. Use `pacman -Si package` for the candidate in the local sync database.

For a Kali or Debian installation, `dpkg-query -W package` shows the installed revision and `apt-cache policy package` shows the cached candidate and suite. For a container, identify the image digest as well as its release. A rolling repository can change after an image is published.

Use the publisher's release record for a question about the current upstream release. Record the lookup date. For an image, verify its signed checksums against the expected signing key. [Kali release history](https://www.kali.org/releases/) · [Kali package tracker](https://pkg.kali.org/) · [Image verification](https://www.kali.org/docs/introduction/download-official-kali-linux-images/)
