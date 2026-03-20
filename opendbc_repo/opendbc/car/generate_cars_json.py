#!/usr/bin/env python3
"""
Generate a JSON file containing manufacturer and name information for all
supported vehicles from opendbc/car/*/values.py.

Usage:
  python generate_cars_json.py [output_file]

If output_file is not specified, the JSON is written to cars.json in the
same directory as this script.
"""

import json
import sys
import os
from unittest.mock import MagicMock

# Some brand value modules have a transitive dependency on openpilot which
# is not part of the opendbc package.  Mock it so we can import every brand.
for module_name in ("openpilot", "openpilot.common", "openpilot.common.params"):
  if module_name not in sys.modules:
    sys.modules[module_name] = MagicMock()

# Import all brands via the top-level values module so new brands are
# automatically included without requiring changes to this script.
from opendbc.car.values import BRANDS


def generate_cars_data() -> list[dict]:
  """Return a list of dicts with 'platform', 'make', and 'name' for every car."""
  cars: list[dict] = []
  seen: set[tuple[str, str]] = set()

  for brand_enum in BRANDS:
    for platform in brand_enum:
      for car_doc in platform.config.car_docs:
        key = (car_doc.make, car_doc.name)
        if key in seen:
          continue
        seen.add(key)
        cars.append({
          "platform": str(platform),
          "make": car_doc.make,
          "name": car_doc.name,
        })

  return sorted(cars, key=lambda c: (c["make"], c["name"]))


def main() -> None:
  output_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "cars.json")

  cars = generate_cars_data()
  with open(output_path, "w", encoding="utf-8") as f:
    json.dump(cars, f, ensure_ascii=False, indent=2)

  print(f"Wrote {len(cars)} vehicles to {output_path}")


if __name__ == "__main__":
  main()
