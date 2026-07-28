"""Export the FastAPI OpenAPI schema to a JSON file for frontend type codegen.

Usage::

    python -m server.scripts.export_openapi [output_path]

Defaults to ``web/admin/openapi.json``. The frontend then runs
``npm run gen:api`` (openapi-typescript) to regenerate ``src/api/schema.d.ts``.
Run this whenever backend request/response schemas change so the frontend types
stay in sync with the API contract.
"""

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.app.main import create_app

DEFAULT_OUTPUT = REPO_ROOT / "web" / "admin" / "openapi.json"


def export_openapi(output_path: Path) -> Path:
    schema = create_app().openapi()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    written = export_openapi(target)
    schema = json.loads(written.read_text(encoding="utf-8"))
    print(
        f"wrote OpenAPI {schema['openapi']} to {written} "
        f"({len(schema.get('paths', {}))} paths, "
        f"{len(schema.get('components', {}).get('schemas', {}))} schemas)"
    )
