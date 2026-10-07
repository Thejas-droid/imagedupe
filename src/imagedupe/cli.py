from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from imagedupe.catalog.db import Catalog
from imagedupe.core.benchmark import run_benchmark, write_benchmark_report
from imagedupe.core.collections import CollectionService
from imagedupe.core.config import Settings
from imagedupe.core.search import SearchService
from imagedupe.hashing.base import DEFAULT_SPEC_ID, get_spec
from imagedupe.indexes.manager import IndexManager
from imagedupe.observability.diagnostics import doctor as run_doctor

app = typer.Typer(no_args_is_help=True, help="ImageDupe administration and search CLI")
collections = typer.Typer(no_args_is_help=True, help="Manage image collections")
indexes = typer.Typer(no_args_is_help=True, help="Manage index generations")
search = typer.Typer(no_args_is_help=True, help="Search indexed collections")
app.add_typer(collections, name="collection")
app.add_typer(indexes, name="index")
app.add_typer(search, name="search")


def services():
    settings = Settings()
    catalog = Catalog(settings.db_path)
    settings.apply_saved(catalog.all_settings())
    index_manager = IndexManager(catalog, settings.index_dir, settings)
    return (
        settings,
        catalog,
        index_manager,
        CollectionService(catalog, settings),
        SearchService(catalog, index_manager, settings),
    )


@app.command()
def serve(host: str | None = None, port: int | None = None):
    """Run the local browser/API service."""
    import uvicorn
    from imagedupe.app import create_app

    settings = Settings()
    bind_host = host or settings.host
    bind_port = port or settings.port
    if bind_host not in {"127.0.0.1", "localhost", "::1"}:
        typer.secho(
            "WARNING: ImageDupe is binding beyond loopback. v1 does not include multi-user authentication; "
            "put it behind an authenticated reverse proxy or trusted network boundary.",
            fg=typer.colors.YELLOW,
            err=True,
        )
    uvicorn.run(create_app(settings), host=bind_host, port=bind_port)


@app.command()
def doctor(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    show_paths: bool = typer.Option(False, "--show-paths", help="Show full configured paths"),
):
    """Report dependency, storage, backend, and compatibility diagnostics."""
    settings, catalog, *_ = services()
    report = run_doctor(settings, catalog, show_paths=show_paths)
    if json_output:
        typer.echo(json.dumps(report, indent=2))
    else:
        for key, value in report.items():
            typer.echo(f"{key}: {value}")


@collections.command("add")
def add_collection(
    name: str,
    root: list[Path] = typer.Option(..., "--root", help="Image root; may be repeated"),
    spec: str = typer.Option(DEFAULT_SPEC_ID, "--spec"),
    backend: str = typer.Option("auto", "--backend"),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive"),
    follow_symlinks: bool = typer.Option(False, "--follow-symlinks/--no-follow-symlinks"),
    exclude: list[str] = typer.Option([], "--exclude"),
    include: list[str] = typer.Option([], "--include"),
):
    """Create a collection definition without modifying source files."""
    get_spec(spec)
    _, _, _, service, _ = services()
    created = service.create(
        name,
        [
            {
                "path": str(item),
                "recursive": recursive,
                "follow_symlinks": follow_symlinks,
                "include_globs": include,
                "exclude_globs": exclude,
            }
            for item in root
        ],
        spec,
        backend,
    )
    typer.echo(created["id"])


@collections.command("list")
def list_collections():
    _, catalog, *_ = services()
    typer.echo(json.dumps(catalog.list_collections(), indent=2))


@collections.command("show")
def show_collection(collection_id: str):
    _, catalog, *_ = services()
    collection = catalog.get_collection(collection_id)
    if not collection:
        raise typer.BadParameter("unknown collection")
    typer.echo(json.dumps(collection, indent=2))


@collections.command("scan")
def scan_collection(collection_id: str):
    _, _, _, service, _ = services()
    typer.echo(json.dumps(service.scan(collection_id), indent=2))


@collections.command("failures")
def collection_failures(collection_id: str, limit: int = 500):
    _, catalog, *_ = services()
    typer.echo(json.dumps(catalog.list_images(collection_id, "failed", limit), indent=2))


@indexes.command("build")
def build_index(
    collection_id: str,
    backend: str = typer.Option("auto", "--backend"),
    activate: bool = typer.Option(True, "--activate/--no-activate"),
):
    _, _, manager, _, _ = services()
    typer.echo(json.dumps(manager.build(collection_id, backend, activate=activate), indent=2))


@indexes.command("list")
def list_indexes(collection_id: str):
    _, catalog, *_ = services()
    typer.echo(json.dumps(catalog.generations(collection_id), indent=2))


@indexes.command("activate")
def activate_index(collection_id: str, generation: int, backend: str | None = None):
    _, _, manager, _, _ = services()
    typer.echo(json.dumps(manager.activate(collection_id, generation, backend), indent=2))


@search.command("image")
def search_image(
    collection_id: str,
    path: Path,
    k: int = 20,
    backend: str = "auto",
    max_hamming: int | None = None,
):
    _, _, _, _, service = services()
    typer.echo(
        json.dumps(
            service.image(
                collection_id,
                path.read_bytes(),
                path.name,
                k,
                backend,
                max_hamming,
            ),
            indent=2,
        )
    )


@search.command("hash")
def search_hash(
    collection_id: str,
    hash_value: str,
    k: int = 20,
    backend: str = "auto",
    max_hamming: int | None = None,
):
    _, _, _, _, service = services()
    typer.echo(
        json.dumps(
            service.hash(collection_id, hash_value, k, backend, max_hamming), indent=2
        )
    )


@app.command()
def status(collection_id: str | None = None):
    _, catalog, manager, _, _ = services()
    payload = catalog.system_stats(collection_id)
    if collection_id:
        collection = catalog.get_collection(collection_id)
        if not collection:
            raise typer.BadParameter("unknown collection")
        payload.update(
            {
                "health": collection["health"],
                "active_generation": collection["active_index"],
                **manager.delta_status(collection_id),
            }
        )
    typer.echo(json.dumps(payload, indent=2))


@app.command()
def benchmark(
    collection_id: str,
    queries: int = 100,
    k: int = 20,
    backend: str = "auto",
    json_output: Path | None = typer.Option(None, "--json-output"),
    json_only: bool = typer.Option(False, "--json"),
):
    """Benchmark search and recall against independent exact Hamming ground truth."""
    _, catalog, manager, _, _ = services()
    report = run_benchmark(catalog, manager, collection_id, k, queries, backend)
    if json_output:
        write_benchmark_report(report, json_output)
    if not json_only:
        typer.echo(
            f"ImageDupe benchmark: backend={report['backend']} k={report['k']} "
            f"queries={report['queries']} p50={report['p50_ms']:.2f} ms "
            f"p95={report['p95_ms']:.2f} ms recall@{report['k']}={report['recall_at_k']:.4f}",
            err=True,
        )
    typer.echo(json.dumps(report, indent=2))


if __name__ == "__main__":
    app()
