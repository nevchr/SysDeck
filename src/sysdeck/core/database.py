import os
import sqlite3


def get_app_data_directory():
    base_directory = os.getenv(
        "LOCALAPPDATA",
        os.path.expanduser("~"),
    )

    app_directory = os.path.join(
        base_directory,
        "SysDeck",
    )

    os.makedirs(
        app_directory,
        exist_ok=True,
    )

    return app_directory


def get_database_path():
    return os.path.join(
        get_app_data_directory(),
        "sysdeck.db",
    )


def connect_database():
    connection = sqlite3.connect(
        get_database_path(),
        timeout=30,
    )

    connection.execute(
        "PRAGMA journal_mode = WAL"
    )

    connection.execute(
        "PRAGMA synchronous = NORMAL"
    )

    initialize_database(
        connection
    )

    return connection


def initialize_database(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            root_path TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            parent TEXT NOT NULL,
            extension TEXT,
            size INTEGER NOT NULL,
            modified REAL NOT NULL
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_files_name
        ON files(name COLLATE NOCASE)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_files_root
        ON files(root_path)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_files_extension
        ON files(extension COLLATE NOCASE)
        """
    )

    connection.commit()