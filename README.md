# Devcontainer Enter



A little helper script for easily entering [VS Code devcontainers](https://code.visualstudio.com/docs/devcontainers/containers) in a separate terminal. Useful if you don't use the integrated VSCode terminal.



It will:



* Detect running VS Code devcontainers automatically (based on Docker labels, container names, etc.).

* List them if multiple are running, or jump straight into the only one if just a single devcontainer is active.

* Open an interactive shell (`bash` if available, falling back to `sh`).

* Optionally run a one-time **post-setup script** (`~/dc-postcommand.sh`) inside the container, tracked by a marker file (`~/.dc-post-setup-done` inside the container).

  This is useful for personal setup, installing extensions, or doing lightweight bootstrapping the first time you enter a container.



⚡️ Disclaimer: This was mostly vibe coded — I didn’t hand-craft all the logic myself, just glued things together until it worked. Expect rough edges.



---



## Installation



Clone this repo and make the script executable somewhere on your `$PATH`:



```bash

git clone https://github.com/sveint/devcontainer-enter.git

cd devcontainer-enter

chmod +x devcontainer_enter.py

ln -s $(pwd)/devcontainer_enter.py ~/.local/bin/dc   # optional shortcut

```



Now you can just run `dc`.



---



## Usage



List running devcontainers (if more than one):



```bash

dc

```



Enter the only running devcontainer directly (runs post script if present):



```bash

dc

```



Enter a specific container from the list:



```bash

dc 2

```



---



## Post-Setup Script



If you create a file `~/dc-postcommand.sh` on your host, it will be copied into the container’s `$HOME` and run the first time you attach.

The script is only executed once per container; the marker file `~/.dc-post-setup-done` is used to remember that setup already ran.



You can override or tweak this behavior:



```bash

dc --postscript ~/my-setup.sh   # different host script

dc --marker ~/.custom-setup-done   # custom marker inside container

dc --force-post   # re-run even if marker exists

dc --skip-post    # don’t run the post script at all

```



---



## Example



`~/dc-postcommand.sh`:



```bash

#!/usr/bin/env bash

set -e

echo "[post] Setting up devcontainer..."

pip install --user ruff black

echo "[post] Done!"

```



---



## Notes



* The post script runs inside the container, as the container user. Don’t assume root privileges.

* Detection is best-effort; if you have unusual container setups, you may need to tweak the heuristics.



---



## License

MIT
