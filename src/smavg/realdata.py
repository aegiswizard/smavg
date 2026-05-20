"""Helpers for building real public benchmark corpora."""

from __future__ import annotations

import json
import re
import urllib.request
import gzip
import subprocess
from pathlib import Path
from typing import Any, Dict

from .json_template import canonical_json_bytes


CISA_KEV_URL = (
    "https://www.cisa.gov/sites/default/files/feeds/"
    "known_exploited_vulnerabilities.json"
)
NVD_CVE_20_BASE_URL = "https://nvd.nist.gov/feeds/json/cve/2.0"
LOGHUB_RAW_BASE_URL = "https://raw.githubusercontent.com/logpai/loghub/master"
WEATHER_CSV_BASE_URL = (
    "https://media.githubusercontent.com/media/"
    "radames/dataset-historical-daily-temperature-210-US/main"
)

LOGHUB_2K_FILES = {
    "Apache": "Apache/Apache_2k.log",
    "Hadoop": "Hadoop/Hadoop_2k.log",
    "HDFS": "HDFS/HDFS_2k.log",
    "Linux": "Linux/Linux_2k.log",
    "OpenSSH": "OpenSSH/OpenSSH_2k.log",
    "Zookeeper": "Zookeeper/Zookeeper_2k.log",
}

WEATHER_CITY_IDS = [
    "USC00042863",
    "USC00166584",
    "USC00280734",
    "USC00286055",
    "USC00356749",
    "USC00380072",
    "USW00003017",
    "USW00003103",
    "USW00003145",
    "USW00003171",
]


def fetch_json(url: str) -> Dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "smavg-phase1-real-benchmark/0.1",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
    if url.endswith(".gz"):
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "smavg-phase1-real-benchmark/0.1",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def write_cisa_kev_corpus(output_dir: Path, limit: int | None = None) -> Dict[str, Any]:
    """Download CISA KEV and write each real vulnerability as one JSON file."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    data = fetch_json(CISA_KEV_URL)
    vulnerabilities = data.get("vulnerabilities")
    if not isinstance(vulnerabilities, list):
        raise ValueError("CISA KEV feed did not contain a vulnerabilities list")

    selected = vulnerabilities[:limit] if limit else vulnerabilities
    records_dir = output_dir / "records"
    records_dir.mkdir(parents=True, exist_ok=True)

    for existing in records_dir.glob("*.json"):
        existing.unlink()

    for index, record in enumerate(selected, start=1):
        if not isinstance(record, dict):
            continue
        cve_id = str(record.get("cveID") or f"record-{index:05d}")
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", cve_id).strip("-")
        target = records_dir / f"{index:05d}-{safe_name}.json"
        target.write_bytes(canonical_json_bytes(record))

    manifest = {
        "source": CISA_KEV_URL,
        "catalog_version": data.get("catalogVersion"),
        "date_released": data.get("dateReleased"),
        "count_in_feed": len(vulnerabilities),
        "count_written": len(list(records_dir.glob("*.json"))),
        "format": "one canonical JSON file per CISA KEV vulnerability record",
    }
    (output_dir / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    return manifest


def write_nvd_cve_corpus(
    output_dir: Path,
    feed: str = "recent",
    limit: int | None = None,
) -> Dict[str, Any]:
    """Download an official NVD CVE 2.0 feed and write one JSON file per CVE."""

    if not re.fullmatch(r"(recent|modified|20\d{2})", feed):
        raise ValueError("feed must be recent, modified, or a year like 2026")

    url = f"{NVD_CVE_20_BASE_URL}/nvdcve-2.0-{feed}.json.gz"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    data = fetch_json(url)
    vulnerabilities = data.get("vulnerabilities")
    if not isinstance(vulnerabilities, list):
        raise ValueError("NVD feed did not contain a vulnerabilities list")

    selected = vulnerabilities[:limit] if limit else vulnerabilities
    records_dir = output_dir / "records"
    records_dir.mkdir(parents=True, exist_ok=True)

    for existing in records_dir.glob("*.json"):
        existing.unlink()

    written = 0
    for index, record in enumerate(selected, start=1):
        if not isinstance(record, dict):
            continue
        cve = record.get("cve")
        cve_id = ""
        if isinstance(cve, dict):
            cve_id = str(cve.get("id") or "")
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", cve_id or f"record-{index:05d}")
        target = records_dir / f"{index:05d}-{safe_name}.json"
        target.write_bytes(canonical_json_bytes(record))
        written += 1

    manifest = {
        "source": url,
        "feed": feed,
        "timestamp": data.get("timestamp"),
        "version": data.get("version"),
        "count_in_feed": len(vulnerabilities),
        "count_written": written,
        "format": "one canonical JSON file per NVD CVE vulnerability record",
    }
    (output_dir / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    return manifest


def _safe_path_name(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", path).strip("_") or "file"


def write_git_history_corpus(
    repo: Path,
    output_dir: Path,
    paths: list[str],
    limit: int | None = None,
) -> Dict[str, Any]:
    """Write exact historical versions of real files from a local Git repo."""

    repo = Path(repo).resolve()
    output_dir = Path(output_dir)
    records_dir = output_dir / "records"
    records_dir.mkdir(parents=True, exist_ok=True)

    if not (repo / ".git").exists():
        raise ValueError(f"Not a Git repository: {repo}")
    if not paths:
        raise ValueError("At least one Git file path is required")

    for existing in records_dir.rglob("*"):
        if existing.is_file():
            existing.unlink()

    written_total = 0
    file_manifests = []
    for file_path in paths:
        log = subprocess.run(
            ["git", "-C", str(repo), "log", "--follow", "--format=%H", "--", file_path],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        commits = [line for line in log.stdout.decode("ascii").splitlines() if line]
        commits.reverse()
        if limit:
            commits = commits[-limit:]

        target_dir = records_dir / _safe_path_name(file_path)
        target_dir.mkdir(parents=True, exist_ok=True)

        written = 0
        for index, commit in enumerate(commits, start=1):
            show = subprocess.run(
                ["git", "-C", str(repo), "show", f"{commit}:{file_path}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if show.returncode != 0:
                continue
            target = target_dir / f"{index:04d}-{commit[:12]}"
            target.write_bytes(show.stdout)
            written += 1

        written_total += written
        file_manifests.append(
            {
                "path": file_path,
                "versions": written,
            }
        )

    manifest = {
        "source": str(repo),
        "format": "exact historical file contents extracted with git show",
        "count_written": written_total,
        "files": file_manifests,
    }
    (output_dir / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    return manifest


def write_loghub_corpus(
    output_dir: Path,
    names: list[str] | None = None,
) -> Dict[str, Any]:
    """Download real Loghub 2k raw log files."""

    output_dir = Path(output_dir)
    records_dir = output_dir / "records"
    records_dir.mkdir(parents=True, exist_ok=True)
    selected = names or ["Apache", "Hadoop", "HDFS", "Linux", "OpenSSH", "Zookeeper"]

    for existing in records_dir.glob("*"):
        if existing.is_file():
            existing.unlink()

    files = []
    for name in selected:
        if name not in LOGHUB_2K_FILES:
            raise ValueError(f"Unknown Loghub dataset: {name}")
        relative = LOGHUB_2K_FILES[name]
        url = f"{LOGHUB_RAW_BASE_URL}/{relative}"
        data = fetch_bytes(url)
        target = records_dir / Path(relative).name
        target.write_bytes(data)
        files.append({"name": name, "source": url, "bytes": len(data)})

    manifest = {
        "source": "https://github.com/logpai/loghub",
        "format": "real Loghub 2k raw log files",
        "count_written": len(files),
        "files": files,
    }
    (output_dir / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    return manifest


def write_weather_csv_corpus(
    output_dir: Path,
    city_ids: list[str] | None = None,
    limit: int | None = None,
) -> Dict[str, Any]:
    """Download real public historical daily weather CSV files."""

    output_dir = Path(output_dir)
    records_dir = output_dir / "records"
    records_dir.mkdir(parents=True, exist_ok=True)
    selected = city_ids or WEATHER_CITY_IDS
    if limit:
        selected = selected[:limit]

    for existing in records_dir.glob("*.csv"):
        existing.unlink()

    files = []
    for city_id in selected:
        safe_id = _safe_path_name(city_id)
        url = f"{WEATHER_CSV_BASE_URL}/{safe_id}.csv"
        data = fetch_bytes(url)
        target = records_dir / f"{safe_id}.csv"
        target.write_bytes(data)
        files.append({"city_id": safe_id, "source": url, "bytes": len(data)})

    manifest = {
        "source": "https://github.com/radames/dataset-historical-daily-temperature-210-US",
        "format": "real historical daily temperature and precipitation CSV files",
        "count_written": len(files),
        "files": files,
    }
    (output_dir / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    return manifest
