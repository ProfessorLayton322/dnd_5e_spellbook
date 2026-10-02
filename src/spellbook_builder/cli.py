from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .service import prefix_search, render_full_spellbook, validate_indexes, verify_append_only
from .store import RuntimeStore
from .util import default_runtime_dir


def _store(args) -> RuntimeStore:
    return RuntimeStore(Path(args.runtime).expanduser().resolve())


def cmd_dataset_info(args) -> int:
    store = _store(args)
    print(json.dumps(store.dataset_metadata(), indent=2, ensure_ascii=False))
    return 0


def cmd_validate(args) -> int:
    report = validate_indexes(_store(args))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


def cmd_list_spells(args) -> int:
    spells = _store(args).load_spells()
    if args.prefix:
        values = prefix_search(spells, args.prefix, limit=args.limit)
    else:
        values = sorted(
            ({"id": spell["id"], "name": spell["name"]} for spell in spells.values()),
            key=lambda item: (item["name"].casefold(), item["id"]),
        )[: args.limit]
    for value in values:
        print(f"{value['name']}\t{value['id']}")
    return 0


def cmd_render(args) -> int:
    path = render_full_spellbook(_store(args), args.spellbook_id)
    print(path)
    return 0


def cmd_verify(args) -> int:
    report = verify_append_only(_store(args), args.spellbook_id)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


def cmd_serve(args) -> int:
    import uvicorn

    from .web import create_app

    uvicorn.run(create_app(Path(args.runtime).expanduser().resolve()), host=args.host, port=args.port)
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="spellbook", description="Offline D&D 5e spellbook builder")
    result.add_argument("--runtime", default=str(default_runtime_dir()), help="runtime/user-data directory (or DND_SPELLBOOK_RUNTIME)")
    commands = result.add_subparsers(dest="command", required=True)

    info = commands.add_parser("dataset-info", help="show bundled spell catalogue metadata")
    info.set_defaults(func=cmd_dataset_info)

    validate = commands.add_parser("validate-index", help="validate the bundled spell catalogue")
    validate.set_defaults(func=cmd_validate)

    listing = commands.add_parser("list-spells", help="list bundled spells")
    listing.add_argument("--prefix")
    listing.add_argument("--limit", type=int, default=100)
    listing.set_defaults(func=cmd_list_spells)

    render = commands.add_parser("render-spellbook", help="reassemble a full PDF from current TOC and immutable segments")
    render.add_argument("spellbook_id")
    render.set_defaults(func=cmd_render)

    verify = commands.add_parser("verify-append-only", help="verify segments, append exports, numbering, and full PDF")
    verify.add_argument("spellbook_id")
    verify.set_defaults(func=cmd_verify)

    serve = commands.add_parser("serve", help="run the localhost browser app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=cmd_serve)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
