"""Fetch the exact organizer revision without vendoring or modifying its sources."""
import subprocess

from .upstream import REVISION, UPSTREAM, verify


def main():
    if not UPSTREAM.exists():
        UPSTREAM.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--no-checkout", "--filter=blob:none",
                        "https://github.com/jaromero3rd/Action_Space.git", str(UPSTREAM)], check=True)
        subprocess.run(["git", "-C", str(UPSTREAM), "checkout", "--detach", REVISION], check=True)
    print("Organizer source verified:", verify())


if __name__ == "__main__":
    main()
