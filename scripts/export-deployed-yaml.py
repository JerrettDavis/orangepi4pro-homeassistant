#!/usr/bin/env python3
"""Export an offline HA YAML capture for review, replacing credential fields."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re

import yaml


@dataclass
class Tagged:
    tag: str
    value: str


class Loader(yaml.SafeLoader):
    pass


class Dumper(yaml.SafeDumper):
    pass


Loader.add_multi_constructor("!", lambda loader, tag, node: Tagged("!" + tag, loader.construct_scalar(node)))
Dumper.add_representer(Tagged, lambda dumper, value: dumper.represent_scalar(value.tag, value.value))
SENSITIVE = re.compile(
    r"password|passwd|token|secret|api.?key|authorization|webhook_id|private_key|^key$|cookie",
    re.IGNORECASE,
)
PATTERNS = ("configuration.yaml", "automations.yaml", "scripts.yaml", "scenes.yaml",
            "mqtt.yaml", "three_d_print_work_dashboard.yaml", "packages/*.yaml", "esphome/*.yaml",
            "dashboards/*.yaml", "addon_options/*.yaml")


def sanitize(value, prefix: str, required: set[str]):
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            path = prefix + "_" + re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
            protected = SENSITIVE.search(str(key)) or (key == "value" and "_env_vars_" in path)
            if protected and child is not None and not isinstance(child, (dict, list, Tagged)):
                required.add(path)
                result[key] = Tagged("!secret", path)
            else:
                result[key] = sanitize(child, path, required)
        return result
    if isinstance(value, list):
        return [sanitize(child, f"{prefix}_{index}", required) for index, child in enumerate(value)]
    return value


def export(source: Path, destination: Path) -> set[str]:
    required: set[str] = set()
    for pattern in PATTERNS:
        for file in sorted(source.glob(pattern)):
            if file.name == "secrets.yaml":
                continue
            relative = file.relative_to(source)
            prefix = re.sub(r"[^a-z0-9]+", "_", relative.with_suffix("").as_posix().lower())
            value = yaml.load(file.read_text(encoding="utf-8"), Loader=Loader)
            cleaned = sanitize(value, prefix, required)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(yaml.dump(cleaned, Dumper=Dumper, sort_keys=False, allow_unicode=True),
                              encoding="utf-8")
    return required


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.destination.exists():
        parser.error("Destination must not exist; review exports before replacing committed files")
    for name in sorted(export(args.source, args.destination)):
        print("Private replacement required:", name)


if __name__ == "__main__":
    main()
