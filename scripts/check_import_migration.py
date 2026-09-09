"""Migration round-trip in an exclusively owned, disposable database."""

import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from erp.platform.config import get_settings
from erp.platform.database import Database


async def database_command(name: str, *, create: bool) -> None:
    if re.fullmatch(r"erp_m23_check_[a-f0-9]{32}", name) is None:
        raise ValueError("Only this check's generated database name is allowed.")
    engine = create_async_engine(
        Database.build_url(get_settings()).set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        hide_parameters=True,
    )
    try:
        async with engine.connect() as connection:
            verb = "CREATE DATABASE" if create else "DROP DATABASE"
            await connection.execute(text(f'{verb} "{name}"'))
    finally:
        await engine.dispose()


def main() -> None:
    name = "erp_m23_check_" + uuid4().hex
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "POSTGRES_DB": name, "DEV_AUTH_ENABLED": "false"}
    asyncio.run(database_command(name, create=True))
    try:
        for direction, revision in (
            ("upgrade", "head"),
            ("downgrade", "0012"),
            ("upgrade", "head"),
        ):
            subprocess.run(
                [sys.executable, "-m", "alembic", direction, revision],
                cwd=root,
                env=env,
                check=True,
            )
        subprocess.run(
            [sys.executable, "-m", "pytest", "tests/integration/test_import_schema.py", "-q"],
            cwd=root,
            env=env,
            check=True,
        )
        print("Import migration round-trip and real schema checks passed.")
    finally:
        asyncio.run(database_command(name, create=False))
        print("Removed only the temporary database:", name)


if __name__ == "__main__":
    main()
