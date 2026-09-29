import base64
import os
import json
import xml.etree.ElementTree as tree

import requests

# https://source.chromium.org/chromium/chromium/src/+/main:chrome/installer/util/additional_parameters.cc;drc=406947a0f1e0e6b596d387b6b14156f369e8c55d;l=206
info = {
    "win_stable_x64": {
        "os": '''platform="win" version="10.0.26100.1742" arch="x64"''',
        "app": '''appid="{8A69D345-D564-463C-AFF1-A69D9E530F96}" ap="x64-stable"''',
    },
    "mac_stable_arm64": {
        "os": '''platform="mac" version="15.5.0" arch="arm64"''',
        "app": '''appid="com.google.Chrome" ap="arm64-stable" brand="GGRO"''',
    },
}

update_url = "https://tools.google.com/service/update2"

session = requests.Session()


def post(os: str, app: str) -> str:
    # installsource="ondemandupdate" is what pins the reply to the
    # "Stable Installs & Version Pins" cohort. Without it the server hands out
    # a random staged-rollout cohort (on macOS that means an older build).
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <request protocol="3.0" updater="Omaha" updaterversion="1.3.36.372" shell_version="1.3.36.352" ismachine="0" sessionid="{{11111111-1111-1111-1111-111111111111}}" installsource="ondemandupdate" requestid="{{11111111-1111-1111-1111-111111111111}}" dedup="cr" domainjoined="0">
    <hw physmemory="16"/>
    <os {os}/>
    <app version="" {app}>
    <updatecheck/>
    <data name="install" index="empty"/>
    </app>
    </request>"""
    r = session.post(update_url, data=xml)
    r.raise_for_status()
    return r.text


def decode(text):
    root = tree.fromstring(text)

    manifest_node = root.find(".//manifest")
    if manifest_node is None:
        print("Error: manifest_node is None")
        return

    manifest_version = manifest_node.get("version")

    package_node = root.find(".//package")
    if package_node is None:
        print("Error: package_node is None")
        return
    package_name = package_node.get("name")
    package_size = int(package_node.get("size"))
    package_sha1 = base64.b64decode(package_node.get("hash")).hex()
    package_sha256 = package_node.get("hash_sha256")

    url_nodes = root.findall(".//url")
    url_prefixes = [node.get("codebase") + package_name for node in url_nodes]

    return {
        "version": manifest_version,
        "size": package_size,
        "sha1": package_sha1,
        "sha256": package_sha256,
        "urls": url_prefixes,
    }


def version_tuple(v):
    return tuple(map(int, v.split(".")))


def pick_url(urls):
    return next(
        (url for url in urls if url.startswith("https://") and "google.com" in url),
        urls[0] if urls else "N/A",
    )


def asset_name(key, url):
    """Release asset name, e.g. win_x64_..._installer_uncompressed.exe."""
    platform, _, arch = key.split("_")
    return f"{platform}_{arch}_{url.rsplit('/', 1)[-1]}"


def load_json(file_path="data.json"):
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, "r") as f:
            return json.load(f) or {}
    except (json.JSONDecodeError, ValueError):
        return {}


def fetch(info, results):
    for k, v in info.items():
        res = post(**v)
        data = decode(res)
        if data is None:
            print(f"Error: No data returned for {k}")
            continue
        if version_tuple(data["version"]) < version_tuple(
            results.get(k, {}).get("version", "0.0.0.0")
        ):
            print("ignore", k, data["version"])
            continue
        results[k] = data


suffixes = ["B", "KB", "MB", "GB", "TB", "PB"]


def humansize(nbytes):
    i = 0
    while nbytes >= 1024 and i < len(suffixes) - 1:
        nbytes /= 1024.0
        i += 1
    f = ("%.2f" % nbytes).rstrip("0").rstrip(".")
    return f"{f} {suffixes[i]}"


platform_names = {"win": "Windows", "mac": "macOS"}
arch_names = {"x86": "x86", "x64": "x64", "arm64": "ARM64"}
channel_names = {"stable": "Stable", "beta": "Beta", "dev": "Dev", "canary": "Canary"}


def save_md(results, file_path="readme.md"):
    channels = {}
    for name in info:
        if name not in results:
            continue
        platform, channel, arch = name.split("_")
        entry = results[name]
        url = pick_url(entry["urls"])
        channels.setdefault(channel, []).append(
            {
                "label": f"{platform_names.get(platform, platform)} "
                f"{arch_names.get(arch, arch)}",
                "version": entry["version"],
                "size": humansize(entry["size"]),
                "sha256": entry["sha256"],
                "url": url,
                "asset": asset_name(name, url),
            }
        )

    with open(file_path, "w", encoding="utf-8") as f:
        f.write("# Google Chrome Offline Installers\n")
        f.write(
            "Stable release archive: "
            "https://github.com/Bush2021/chrome_installer/releases\n\n"
        )
        f.write(
            "- **Windows x64** - uncompressed installer, extract with 7-Zip\n"
            "- **macOS ARM64** - universal disk image, open and drag to Applications\n\n"
        )

        for channel, rows in channels.items():
            f.write(f"## {channel_names.get(channel, channel.title())}\n\n")

            f.write("| Platform | Version | Size | SHA-256 | Download |\n")
            f.write("|----------|---------|------|---------|----------|\n")
            for row in rows:
                sha256_short = (
                    row["sha256"][:16] + "..."
                    if len(row["sha256"]) > 16
                    else row["sha256"]
                )
                f.write(
                    f"| **{row['label']}** | `{row['version']}` | {row['size']} | "
                    f"`{sha256_short}` | [Download]({row['url']}) |\n"
                )
            f.write("\n")

            f.write("<details>\n")
            f.write("<summary>Full SHA-256 (sha256sum -c)</summary>\n\n")
            f.write("```\n")
            for row in rows:
                f.write(f"{row['sha256']}  {row['asset']}\n")
            f.write("```\n\n")
            f.write("</details>\n\n")


def save_json(results, file_path="data.json"):
    with open(file_path, "w") as f:
        json.dump(results, f, indent=4)


def main():
    results = load_json()
    # drop anything no longer tracked in `info`
    results = {k: v for k, v in results.items() if k in info}
    fetch(info, results)
    save_md(results)
    save_json(results)


if __name__ == "__main__":
    main()
