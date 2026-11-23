"""Convert the dashboard's soft Bot characters (softShapes.ts) into mobile JSON.

Usage: python3 mobile/scripts/soft-characters.py <softShapes.ts> <out.json>
"""

import json
import re
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()
shapes = {}
for name, body, eyes in re.findall(r'(\w+): \{\s*body: "([^"]+)",\s*eyes: \[(.*?)\],\s*\}', source, re.S):
    rows = [[float(n) for n in row.split(",")] for row in re.findall(r"\[([^\[\]]+)\]", eyes)]
    shapes[name] = {"body": body, "eyes": rows, "flat": True}
inks_block = re.search(r"softInks[^{]*\{(.*?)\};", source, re.S).group(1)
inks = {name: [light, dark] for name, light, dark in re.findall(r'(\w+): \["(#\w+)", "(#\w+)"\]', inks_block)}
Path(sys.argv[2]).write_text(json.dumps({"shapes": shapes, "inks": inks}, indent=1) + "\n")
print(f"{len(shapes)} shapes, {len(inks)} inks")
