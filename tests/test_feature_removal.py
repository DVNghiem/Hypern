import importlib
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def reset_store():
    """Keep public-surface tests independent of the HTTP test server."""
    yield


@pytest.mark.parametrize("module_name", ["hypern.database", "hypern.grpc", "hypern.graphql"])
def test_removed_feature_modules_are_not_importable(module_name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)


@pytest.mark.parametrize(
    "symbol",
    [
        "Database",
        "DbSession",
        "ConnectionPool",
        "PoolConfig",
        "PoolStatus",
        "get_database",
        "get_db",
        "finalize_db",
    ],
)
def test_database_symbols_are_not_exported_from_hypern(symbol: str) -> None:
    import hypern

    assert not hasattr(hypern, symbol)


@pytest.mark.parametrize(
    "symbol",
    [
        "AnyPool",
        "ConnectionPool",
        "DbSession",
        "PoolConfig",
        "PoolStatus",
        "RowStream",
        "finalize_db",
        "finalize_db_all",
        "get_db",
        "GrpcConfig",
        "GrpcServer",
    ],
)
def test_removed_native_symbols_are_not_exported(symbol: str) -> None:
    from hypern import _hypern

    assert not hasattr(_hypern, symbol)


@pytest.mark.parametrize(
    "symbol",
    [
        "AnyPool",
        "ConnectionPool",
        "DbSession",
        "PoolConfig",
        "PoolStatus",
        "RowStream",
        "finalize_db",
        "finalize_db_all",
        "get_db",
        "GrpcConfig",
        "GrpcServer",
    ],
)
def test_removed_native_type_stubs_do_not_declare_symbols(symbol: str) -> None:
    import hypern

    stub = Path(hypern.__file__).with_name("_hypern.pyi").read_text()

    assert symbol not in stub


def test_legacy_di_module_is_not_importable() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("hypern.di")


@pytest.mark.parametrize(
    "symbol",
    [
        "DIContainer",
        "Validator",
        "inject",
        "validate",
        "validate_body",
        "validate_params",
        "validate_query",
    ],
)
def test_legacy_di_and_validation_symbols_are_not_exported(symbol: str) -> None:
    import hypern

    assert not hasattr(hypern, symbol)


@pytest.mark.parametrize("symbol", ["di", "singleton", "factory", "inject"])
def test_hypern_class_does_not_expose_legacy_di_methods(symbol: str) -> None:
    from hypern import Hypern

    assert not hasattr(Hypern, symbol)


@pytest.mark.parametrize(
    "symbol",
    ["validate", "validate_body", "validate_params", "validate_query"],
)
def test_validation_module_does_not_expose_positional_decorators(symbol: str) -> None:
    from hypern import validation

    assert not hasattr(validation, symbol)


def test_native_module_does_not_export_di_container() -> None:
    from hypern import _hypern

    assert not hasattr(_hypern, "DIContainer")
