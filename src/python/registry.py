#!/usr/bin/env python3
"""ai-leverage/src/python/registry.py

Asks an image registry (Docker Hub, ghcr.io, quay.io, ...) which build an image
tag points to now, without downloading the image. src/bash/service.sh uses it
to tell whether Update would fetch something new.

Usage: python3 -I registry.py <image> [--labels]
  Prints the tag's digest: the same sha256 Docker keeps for a pulled image.
  With --labels, also the image's version label and build date, for this
  PC's platform: digest|version|created

The digest comes from a HEAD request, which Docker Hub doesn't count toward
its download limit. --labels reads the image's settings, a few kilobytes,
which Docker Hub counts like the start of a download.
"""

import json
import platform
import sys
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 20

# Every kind of image description, so the registry answers with the one the
# tag points to: a list of platforms, or a single image
ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])

INDEX_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
)


def parse(image):
    """Splits an image name into registry, repository and tag or digest."""
    name, ref = image, "latest"
    if "@" in name:
        name, ref = name.split("@", 1)
    else:
        last = name.rsplit("/", 1)[-1]
        if ":" in last:
            name, ref = name.rsplit(":", 1)
    first, _, rest = name.partition("/")
    if rest and ("." in first or ":" in first or first == "localhost"):
        registry, repo = first, rest
    else:
        registry, repo = "registry-1.docker.io", name
    if registry in ("docker.io", "index.docker.io"):
        registry = "registry-1.docker.io"
    if registry == "registry-1.docker.io" and "/" not in repo:
        repo = "library/" + repo
    return registry, repo, ref


class Registry:
    def __init__(self, registry, repo):
        self.base = f"https://{registry}/v2/{repo}"
        self.token = None

    def _login(self, challenge):
        """Gets an anonymous token, as the registry's 401 answer describes."""
        scheme, _, params = challenge.partition(" ")
        if scheme.lower() != "bearer":
            raise RuntimeError(f"the registry asks for {scheme} sign-in")
        fields = {}
        for part in params.split(","):
            key, _, value = part.strip().partition("=")
            fields[key] = value.strip('"')
        query = {k: v for k, v in fields.items() if k in ("service", "scope")}
        url = fields["realm"] + "?" + urllib.parse.urlencode(query)
        with urllib.request.urlopen(url, timeout=TIMEOUT) as answer:
            data = json.load(answer)
        self.token = data.get("token") or data.get("access_token")

    def request(self, path, method="GET", accept=ACCEPT):
        for _ in range(2):
            req = urllib.request.Request(self.base + path, method=method)
            req.add_header("Accept", accept)
            req.add_header("User-Agent", "ai-leverage-update-check")
            if self.token:
                # Not passed on when the registry redirects to its storage
                req.add_unredirected_header("Authorization", "Bearer " + self.token)
            try:
                return urllib.request.urlopen(req, timeout=TIMEOUT)
            except urllib.error.HTTPError as error:
                challenge = error.headers.get("WWW-Authenticate", "")
                if error.code == 401 and challenge and not self.token:
                    self._login(challenge)
                    continue
                raise
        raise RuntimeError("the registry refused the anonymous sign-in")

    def get_json(self, path, accept=ACCEPT):
        with self.request(path, accept=accept) as answer:
            return json.load(answer)


def this_platform():
    machine = platform.machine().lower()
    return {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(machine, machine)


def digest_of(reg, ref):
    with reg.request(f"/manifests/{ref}", method="HEAD") as answer:
        digest = answer.headers.get("Docker-Content-Digest")
    if digest:
        return digest
    # A registry that doesn't name it: the digest of the description itself
    import hashlib
    with reg.request(f"/manifests/{ref}") as answer:
        return "sha256:" + hashlib.sha256(answer.read()).hexdigest()


def labels_of(reg, digest):
    """The version label and build date of the image for this PC's platform."""
    manifest = reg.get_json(f"/manifests/{digest}")
    if manifest.get("mediaType") in INDEX_TYPES or "manifests" in manifest:
        arch = this_platform()
        chosen = None
        for entry in manifest.get("manifests", []):
            plat = entry.get("platform", {})
            if plat.get("os") == "linux" and plat.get("architecture") == arch:
                chosen = entry["digest"]
                break
        if not chosen:
            return "", ""
        manifest = reg.get_json(f"/manifests/{chosen}")
    config = reg.get_json(f"/blobs/{manifest['config']['digest']}", accept="*/*")
    labels = (config.get("config") or {}).get("Labels") or {}
    created = (config.get("created") or "")[:10]
    return labels.get("org.opencontainers.image.version", ""), created


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__.split("\n\n")[2], file=sys.stderr)
        return 2
    registry, repo, ref = parse(args[0])
    reg = Registry(registry, repo)
    try:
        digest = digest_of(reg, ref)
        if "--labels" in sys.argv:
            version, created = labels_of(reg, digest)
            print(f"{digest}|{version.replace('|', ' ')}|{created}")
        else:
            print(digest)
    except (urllib.error.URLError, RuntimeError, KeyError, ValueError, OSError) as error:
        print(f"{args[0]}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
