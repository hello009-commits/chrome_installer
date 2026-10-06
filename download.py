import argparse
import hashlib
import json
import os
import requests
import shutil
import subprocess

from fetch import asset_name, pick_url, version_tuple

ARCH_KEYS = ["win_stable_x64", "mac_stable_arm64"]


def get_last_version():
    result = subprocess.run(
        ["git", "tag", "--sort=-creatordate"], capture_output=True, text=True
    )
    version = result.stdout.split("\n")[0].strip()
    return version if version else "0.0.0.0"


def export_latest_version(arch_keys):
    # Windows and macOS stable can sit on different builds, and one run makes
    # one tag, so the tag tracks the newest installer in the release.
    with open("data.json", "r") as f:
        data = json.load(f)
    latest_version = max((data[k]["version"] for k in arch_keys), key=version_tuple)
    github_env = os.getenv("GITHUB_ENV")
    if github_env and os.path.exists(github_env):
        with open(github_env, "a") as env_file:
            env_file.write(f"latest_version={latest_version}\n")


def check_update(arch_key):
    last_version = get_last_version()
    with open("data.json", "r") as f:
        data = json.load(f)
        latest_version = data[arch_key]["version"]
    return version_tuple(last_version) < version_tuple(latest_version)


def get_download_info(arch_key):
    with open("data.json", "r") as f:
        data = json.load(f)
        entry = data[arch_key]
        version = entry["version"]
        download_url = pick_url(entry["urls"])
        sha256 = entry["sha256"]
    return version, download_url, sha256


def download_for_arch(arch_key):
    if check_update(arch_key):
        print(f"New version detected for {arch_key}, start downloading...")
        version, url, expected_sha256 = get_download_info(arch_key)
        filename = asset_name(arch_key, url)

        if os.path.exists(filename):
            print(f"The file {filename} already exists, skip downloading")
            return
        r = requests.get(url, stream=True)
        r.raise_for_status()
        digest = hashlib.sha256()
        with open(filename, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    digest.update(chunk)
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != expected_sha256.lower():
            os.remove(filename)
            raise SystemExit(
                f"SHA256 mismatch for {arch_key}: "
                f"expected {expected_sha256}, got {actual_sha256}"
            )
        print(f"Download complete and verified for {arch_key}")
    else:
        print(f"No new version detected for {arch_key}, skip downloading")


def main():
    parser = argparse.ArgumentParser(
        description="Download Chrome installers for different platforms"
    )
    parser.add_argument(
        "--arch",
        nargs="+",
        default=ARCH_KEYS,
        choices=ARCH_KEYS,
        help=f"Target(s) to download (default: {' '.join(ARCH_KEYS)})",
    )
    args = parser.parse_args()
    export_latest_version(args.arch)
    for arch in args.arch:
        download_for_arch(arch)
    if os.path.exists("__pycache__"):
        shutil.rmtree("__pycache__")


if __name__ == "__main__":
    main()
