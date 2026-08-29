import os
import sqlite3
import time


# ============================================================
# App data paths
# ============================================================

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


# ============================================================
# Path helpers
# ============================================================

def normalize_root_path(
    path,
):
    """
    Return a stable absolute representation of an indexed root.

    We preserve the normal Windows display casing while using
    normcase() separately whenever paths need to be compared.
    """

    return os.path.abspath(
        os.path.normpath(
            path
        )
    )


def comparison_path(
    path,
):
    """
    Normalize a path for operating-system-aware comparison.

    On Windows, normcase() makes comparisons case-insensitive
    and normalizes path separators.
    """

    return os.path.normcase(
        normalize_root_path(
            path
        )
    )


# ============================================================
# Connection
# ============================================================

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


# ============================================================
# Schema
# ============================================================

def initialize_database(
    connection,
):
    # --------------------------------------------------------
    # Indexed file metadata
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Explicit indexed-location registry
    #
    # Previously SysDeck inferred indexed locations from
    # DISTINCT files.root_path values. That means an empty
    # indexed folder could not exist as a location and made
    # overlapping roots difficult to reason about.
    #
    # indexed_roots now owns that responsibility.
    # --------------------------------------------------------

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS indexed_roots (
            root_path TEXT PRIMARY KEY COLLATE NOCASE,
            last_indexed REAL NOT NULL
        )
        """
    )

    # --------------------------------------------------------
    # Migration
    #
    # Existing SysDeck installations already have file rows.
    # Promote every existing root_path into indexed_roots.
    #
    # INSERT OR IGNORE makes this safe to execute every time
    # the database is opened.
    # --------------------------------------------------------

    connection.execute(
        """
        INSERT OR IGNORE INTO indexed_roots (
            root_path,
            last_indexed
        )
        SELECT
            root_path,
            ?
        FROM files
        GROUP BY root_path
        """,
        (
            time.time(),
        ),
    )

    # --------------------------------------------------------
    # Indexes
    # --------------------------------------------------------

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


# ============================================================
# Indexed-root registry
# ============================================================

def register_indexed_root(
    connection,
    root_path,
    indexed_at=None,
):
    root_path = normalize_root_path(
        root_path
    )

    if indexed_at is None:
        indexed_at = time.time()

    connection.execute(
        """
        INSERT INTO indexed_roots (
            root_path,
            last_indexed
        )
        VALUES (?, ?)

        ON CONFLICT(root_path) DO UPDATE SET
            last_indexed = excluded.last_indexed
        """,
        (
            root_path,
            indexed_at,
        ),
    )


def get_indexed_roots(
    connection,
):
    return connection.execute(
        """
        SELECT root_path
        FROM indexed_roots
        ORDER BY root_path COLLATE NOCASE
        """
    ).fetchall()


def get_index_counts(
    connection,
):
    file_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM files
        """
    ).fetchone()[0]

    root_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM indexed_roots
        """
    ).fetchone()[0]

    return (
        file_count,
        root_count,
    )


def get_indexed_root_rows(
    connection,
):
    """
    Return every registered indexed location, including folders
    that currently contain zero indexed files.

    Counts and sizes are calculated from files instead of being
    duplicated in indexed_roots, so duplicate cleanup and the
    Organizer cannot make stored statistics stale.
    """

    return connection.execute(
        """
        SELECT
            roots.root_path,
            COUNT(files.id) AS file_count,
            COALESCE(
                SUM(files.size),
                0
            ) AS total_size
        FROM indexed_roots AS roots

        LEFT JOIN files
            ON files.root_path = roots.root_path

        GROUP BY roots.root_path

        ORDER BY
            roots.root_path COLLATE NOCASE
        """
    ).fetchall()


# ============================================================
# Overlap protection
# ============================================================

def find_indexed_root_conflict(
    connection,
    candidate_root,
):
    """
    Check whether a new indexed root overlaps an existing one.

    Exact matches are allowed because they represent a reindex.

    Returns None when safe, otherwise:

        {
            "type": "covered_by" | "contains",
            "root": existing_root,
        }

    covered_by:
        Existing root contains the candidate.

    contains:
        Candidate contains an existing indexed root.
    """

    candidate_root = normalize_root_path(
        candidate_root
    )

    candidate_compare = comparison_path(
        candidate_root
    )

    existing_roots = get_indexed_roots(
        connection
    )

    for (
        existing_root,
    ) in existing_roots:

        existing_compare = comparison_path(
            existing_root
        )

        # Exact root = ordinary reindex.
        if (
            candidate_compare
            == existing_compare
        ):
            continue

        try:
            common_path = os.path.commonpath(
                [
                    candidate_compare,
                    existing_compare,
                ]
            )

        except ValueError:
            # Different Windows drives, for example C: vs D:.
            continue

        if (
            common_path
            == existing_compare
        ):
            return {
                "type":
                    "covered_by",

                "root":
                    existing_root,
            }

        if (
            common_path
            == candidate_compare
        ):
            return {
                "type":
                    "contains",

                "root":
                    existing_root,
            }

    return None