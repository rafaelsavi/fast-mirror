import contextlib
import hashlib
import os
import re
import sqlite3
import time
from collections.abc import Iterable
from os import PathLike
from pathlib import Path

from core.file import CstmPath, CstmPathType, StatsHash, get_stats_hash
from utils.constants import LOCAL_MIRROR_PATH
from utils.logger import logger
from utils.utils import log_progress, sanitize_path

local_mirror_path = LOCAL_MIRROR_PATH


def _compute_exclusions_hash(exclusions: list[str]) -> str:
    """Compute a deterministic 8-byte hash of the sanitized, sorted exclusions list."""
    cleaned = sorted({sanitize_path(e).strip().lower() for e in exclusions if e.strip()})
    payload = '\n'.join(cleaned).encode('utf-8')
    return hashlib.blake2b(payload, digest_size=8).hexdigest()


class _LegacyDbAdapter:
    """Dict-like context manager adapter providing backwards compatibility for direct table manipulation."""

    def __init__(self, mirror: 'MirrorDatabase', root_dir: str | PathLike[str]):
        self.mirror = mirror
        self.root_dir = root_dir

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def __setitem__(self, key, value):
        root_str = sanitize_path(self.root_dir)
        rel = self.mirror._to_rel_path(root_str, key)
        with self.mirror._get_connection() as conn:
            conn.execute(
                'INSERT OR REPLACE INTO mirror_cache (root_dir, rel_path, stats_hash) VALUES (?, ?, ?);',
                (root_str, rel, str(value)),
            )
            count = conn.execute('SELECT COUNT(*) FROM mirror_cache WHERE root_dir = ?;', (root_str,)).fetchone()[0]
            conn.execute(
                'INSERT OR REPLACE INTO mirror_metadata (root_dir, exclusions_hash, file_count, last_scanned) '
                'VALUES (?, ?, ?, ?);',
                (root_str, self.mirror.exclusions_hash, count, time.time()),
            )
            conn.commit()

    def __delitem__(self, key):
        root_str = sanitize_path(self.root_dir)
        rel = self.mirror._to_rel_path(root_str, key)
        with self.mirror._get_connection() as conn:
            conn.execute(
                'DELETE FROM mirror_cache WHERE root_dir = ? AND rel_path = ?;',
                (root_str, rel),
            )
            count = conn.execute('SELECT COUNT(*) FROM mirror_cache WHERE root_dir = ?;', (root_str,)).fetchone()[0]
            conn.execute(
                'UPDATE mirror_metadata SET file_count = ?, last_scanned = ? WHERE root_dir = ?;',
                (count, time.time(), root_str),
            )
            conn.commit()

    def __contains__(self, key):
        return self.mirror.exists(self.root_dir, key)

    def __len__(self):
        return self.mirror.size(self.root_dir)

    def __bool__(self):
        return self.mirror.size(self.root_dir) > 0


class MirrorDatabase:
    """
    A class to manage a local mirror database using SQLite.
    Stores cached file paths and their stats hashes in a normalized relational schema
    with exclusion fingerprint invalidation.
    """

    def __init__(self, path: str = local_mirror_path, exclusions: None | list[str] = None):
        self.path = path
        self.exclusions = list(sorted([sanitize_path(ex) for ex in exclusions])) if exclusions else []
        self.exclusions_hash = _compute_exclusions_hash(self.exclusions)
        self.init()

    @contextlib.contextmanager
    def _get_connection(self):
        """Context manager for SQLite connections strictly adhering to Windows file lock rules."""
        with contextlib.closing(sqlite3.connect(self.path, timeout=30.0)) as conn:
            yield conn

    def init(self) -> bool:
        """Initialize database file, WAL mode, and tables."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            with self._get_connection() as conn:
                conn.execute('PRAGMA journal_mode=WAL;')
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS mirror_cache (
                        root_dir TEXT NOT NULL,
                        rel_path TEXT NOT NULL,
                        stats_hash TEXT NOT NULL,
                        PRIMARY KEY (root_dir, rel_path)
                    );
                """)
                conn.execute('CREATE INDEX IF NOT EXISTS idx_mirror_root ON mirror_cache(root_dir);')
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS mirror_metadata (
                        root_dir TEXT PRIMARY KEY,
                        exclusions_hash TEXT NOT NULL,
                        file_count INTEGER NOT NULL DEFAULT 0,
                        last_scanned REAL NOT NULL
                    );
                """)
                conn.commit()
            return True
        except Exception as e:
            logger.warning(f'Could not create database. Exception: {e}')
            return False

    def _enable_wal(self):
        """Enable WAL journal mode on the SQLite database."""
        try:
            with self._get_connection() as conn:
                conn.execute('PRAGMA journal_mode=WAL;')
                conn.commit()
        except Exception as e:
            logger.warning(f'Could not set SQLite WAL mode on {self.path}. Exception: {e}')

    def vacuum(self) -> bool:
        """Reclaim unused disk space and defragment SQLite database file."""
        try:
            logger.info(f'Running VACUUM on database <{self.path}>')
            with self._get_connection() as conn:
                conn.execute('VACUUM;')
                conn.commit()
            logger.info(f'VACUUM completed successfully on <{self.path}>')
            return True
        except Exception as e:
            logger.warning(f'Could not VACUUM database <{self.path}>. Exception: {e}')
            return False

    def _to_rel_path(self, root_dir: str | PathLike[str], path: CstmPathType) -> str:
        """Convert a path into a normalized relative path string without network I/O."""
        root_str = sanitize_path(root_dir).rstrip('\\')
        path_str = sanitize_path(path)

        # Direct root prefix match
        if path_str.lower().startswith(root_str.lower() + '\\'):
            return path_str[len(root_str) + 1 :]
        if path_str.lower() == root_str.lower():
            return ''

        # Check if already relative
        if not path_str.startswith('\\\\') and not (len(path_str) >= 2 and path_str[1] == ':'):
            return path_str.lstrip('\\')

        try:
            return str(Path(path_str).relative_to(Path(root_str)))
        except ValueError:
            return path_str

    def _to_full_path(self, root_dir: str | PathLike[str], rel_path: str) -> str:
        """Reconstruct a full path string from root_dir and rel_path."""
        root_str = sanitize_path(root_dir).rstrip('\\')
        clean_rel = rel_path.lstrip('\\')
        return f'{root_str}\\{clean_rel}' if clean_rel else root_str

    def _generate_table_name(self, root_dir: str | PathLike[str]) -> str:
        """
        Generate legacy table name based on root_dir and exclusions.
        Preserved for backwards compatibility with tests and legacy migration matching.
        """
        sanitized_root = sanitize_path(root_dir).replace(os.sep, '_').replace(':', '_')
        sanitized_exclusions = '_'.join(e.replace(os.sep, '_').replace(':', '_') for e in self.exclusions)
        allowed_pattern = r'[^a-zA-Z0-9_]'
        sanitized_root = re.sub(allowed_pattern, '_', sanitized_root)
        sanitized_exclusions = re.sub(allowed_pattern, '_', sanitized_exclusions)
        return f'{sanitized_root}__{sanitized_exclusions}'

    def _get_db(self, root_dir: str | PathLike[str]) -> '_LegacyDbAdapter':
        """Provide a dict-like adapter for test compatibility and direct key-value operations."""
        return _LegacyDbAdapter(self, root_dir)

    def exists_table(self, root_dir: str | PathLike[str]) -> bool:
        """Check if a valid mirror cache exists for the given root_dir with matching exclusions."""
        root_str = sanitize_path(root_dir)
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    'SELECT exclusions_hash, file_count FROM mirror_metadata WHERE root_dir = ?;',
                    (root_str,),
                ).fetchone()
                if not row:
                    return False
                saved_hash, file_count = row
                return saved_hash == self.exclusions_hash and file_count > 0
        except Exception as e:
            logger.warning(f'Could not check if table exists. Exception: {e}')
            return False

    def exists(self, root_dir: str | PathLike[str], path: CstmPathType) -> bool:
        """Check if the given path exists in the database for the specified root_dir."""
        root_str = sanitize_path(root_dir)
        rel_path = self._to_rel_path(root_str, path)
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    'SELECT 1 FROM mirror_cache WHERE root_dir = ? AND rel_path = ?;',
                    (root_str, rel_path),
                ).fetchone()
                return row is not None
        except Exception as e:
            logger.warning(f'Could not check if path exists. Exception: {e}')
            return False

    def size(self, root_dir: str | PathLike[str]) -> int:
        """Get the number of entries for root_dir in the mirror cache."""
        root_str = sanitize_path(root_dir)
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    'SELECT file_count FROM mirror_metadata WHERE root_dir = ?;',
                    (root_str,),
                ).fetchone()
                if row is not None:
                    return row[0]
                count_row = conn.execute(
                    'SELECT COUNT(*) FROM mirror_cache WHERE root_dir = ?;',
                    (root_str,),
                ).fetchone()
                return count_row[0] if count_row else 0
        except Exception as e:
            logger.warning(f'Could not get size of database. Exception: {e}')
            return 0

    def reset(self, root_dir: str | PathLike[str]) -> bool:
        """Reset the database for the given root_dir."""
        root_str = sanitize_path(root_dir)
        try:
            with self._get_connection() as conn:
                has_data = (
                    conn.execute(
                        'SELECT 1 FROM mirror_cache WHERE root_dir = ? LIMIT 1;',
                        (root_str,),
                    ).fetchone()
                    is not None
                )

                if has_data:
                    logger.info(f'Resetting mirror for <{root_dir}>')
                    conn.execute('DELETE FROM mirror_cache WHERE root_dir = ?;', (root_str,))
                    conn.execute('DELETE FROM mirror_metadata WHERE root_dir = ?;', (root_str,))
                    conn.commit()
                else:
                    logger.info(f'No mirror to reset for <{root_dir}>')
            return True
        except Exception as e:
            logger.warning(f'Could not reset database for <{root_dir}>. Exception: {e}')
            return False

    def get_table_as_dict(self, root_dir: str | PathLike[str]) -> dict[str, StatsHash]:
        """Retrieve all entries for root_dir as a dictionary {full_path: stats_hash}."""
        root_str = sanitize_path(root_dir)
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    'SELECT rel_path, stats_hash FROM mirror_cache WHERE root_dir = ?;',
                    (root_str,),
                )
                return {
                    self._to_full_path(root_str, rel_path): StatsHash(stats_hash) for rel_path, stats_hash in cursor
                }
        except Exception as e:
            logger.warning(f'Could not open DB to get table. Exception: {e}')
            return {}

    def get_paths(self, root_dir: str | PathLike[str]) -> set[CstmPath]:
        """Retrieve all paths for root_dir as a set of CstmPath objects."""
        root_str = sanitize_path(root_dir)
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    'SELECT rel_path, stats_hash FROM mirror_cache WHERE root_dir = ?;',
                    (root_str,),
                )
                return {
                    CstmPath(
                        self._to_full_path(root_str, rel_path),
                        root_dir=root_str,
                        stats_hash=StatsHash(stats_hash),
                    )
                    for rel_path, stats_hash in cursor
                }
        except Exception as e:
            logger.warning(f'Could not open DB to get keys. Exception: {e}')
            return set()

    def get_stat_hash(
        self, root_dir: str | PathLike[str], path: CstmPathType | list[CstmPathType]
    ) -> StatsHash | None | list[StatsHash | None]:
        """
        Retrieve the value(s) associated with the given path(s) from the database.

        :param root_dir: The root directory for which the table is being accessed.
        :param path: A single path or an iterable of paths.
        :return: A single value, None, or a list of values/None for multiple paths.
        """
        root_str = sanitize_path(root_dir)

        def get_single(conn: sqlite3.Connection, p: CstmPathType) -> StatsHash | None:
            rel = self._to_rel_path(root_str, p)
            row = conn.execute(
                'SELECT stats_hash FROM mirror_cache WHERE root_dir = ? AND rel_path = ?;',
                (root_str, rel),
            ).fetchone()
            if row is not None:
                return StatsHash(row[0])
            logger.warning(f'Key does not exist in database: {p}')
            return None

        try:
            with self._get_connection() as conn:
                if isinstance(path, list):
                    return [get_single(conn, p_single) for p_single in path]
                return get_single(conn, path)
        except Exception as e:
            logger.warning(f'Could not open DB to get keys {path}. Exception: {e}')
            return None

    def add_path(self, root_dir: str | PathLike[str], path: Iterable[CstmPathType] | CstmPathType):
        """Add or update paths in the mirror cache using optimized batch transactions."""
        root_str = sanitize_path(root_dir)
        items = list(path) if isinstance(path, Iterable) and not isinstance(path, str | bytes | PathLike) else [path]

        if not items:
            return

        start_time = time.time()
        number_files = len(items)
        rows: list[tuple[str, str, str]] = []

        for i, p in enumerate(items):
            try:
                rel = self._to_rel_path(root_str, p)
                # Reuse cached stats_hash if available to prevent redundant network I/O
                stats_hash = getattr(p, '_stats_hash', None) or getattr(p, 'stats_hash', None)
                if not stats_hash:
                    stats_hash = get_stats_hash(p)
                rows.append((root_str, rel, str(stats_hash)))
                if number_files > 10_000:
                    log_progress('Prepared', i, number_files, start_time, interval=10_000)
            except Exception as e:
                logger.error(f'Could not process file {p} for local mirror. Exception: {e}')

        try:
            with self._get_connection() as conn:
                saved_hash = conn.execute(
                    'SELECT exclusions_hash FROM mirror_metadata WHERE root_dir = ?;',
                    (root_str,),
                ).fetchone()
                if saved_hash and saved_hash[0] != self.exclusions_hash:
                    conn.execute('DELETE FROM mirror_cache WHERE root_dir = ?;', (root_str,))

                conn.executemany(
                    'INSERT OR REPLACE INTO mirror_cache (root_dir, rel_path, stats_hash) VALUES (?, ?, ?);',
                    rows,
                )
                count = conn.execute(
                    'SELECT COUNT(*) FROM mirror_cache WHERE root_dir = ?;',
                    (root_str,),
                ).fetchone()[0]
                conn.execute(
                    'INSERT OR REPLACE INTO mirror_metadata (root_dir, exclusions_hash, file_count, last_scanned) '
                    'VALUES (?, ?, ?, ?);',
                    (root_str, self.exclusions_hash, count, time.time()),
                )
                conn.commit()
        except Exception as e:
            logger.critical(f'Could not open DB to add file(s): {path} Exception: {e}')

    def remove_path(self, root_dir: str | PathLike[str], path: CstmPathType | Iterable[CstmPathType]) -> bool:
        """Remove path(s) from the mirror cache."""
        root_str = sanitize_path(root_dir)
        items = list(path) if isinstance(path, Iterable) and not isinstance(path, str | bytes | PathLike) else [path]

        if not items:
            return True

        rows = [(root_str, self._to_rel_path(root_str, p)) for p in items]

        try:
            with self._get_connection() as conn:
                deleted_count = 0
                for r_dir, rel in rows:
                    cur = conn.execute(
                        'DELETE FROM mirror_cache WHERE root_dir = ? AND rel_path = ?;',
                        (r_dir, rel),
                    )
                    if cur.rowcount > 0:
                        deleted_count += 1
                    else:
                        logger.warning(f'Key does not exist in database: {rel}')

                count = conn.execute(
                    'SELECT COUNT(*) FROM mirror_cache WHERE root_dir = ?;',
                    (root_str,),
                ).fetchone()[0]
                conn.execute(
                    'UPDATE mirror_metadata SET file_count = ?, last_scanned = ? WHERE root_dir = ?;',
                    (count, time.time(), root_str),
                )
                conn.commit()
                return deleted_count > 0 or len(rows) == 0
        except Exception as e:
            logger.warning(f'Could not open DB to remove file(s): {path} Exception: {e}')
            return False

    def replace_path(self, root_dir: str | PathLike[str], path: CstmPathType, new_path: CstmPathType):
        """Remove old path and add new_path to the database atomically."""
        root_str = sanitize_path(root_dir)
        old_rel = self._to_rel_path(root_str, path)
        new_rel = self._to_rel_path(root_str, new_path)
        new_hash = getattr(new_path, '_stats_hash', None) or getattr(new_path, 'stats_hash', None)
        if not new_hash:
            new_hash = get_stats_hash(new_path)

        try:
            with self._get_connection() as conn:
                conn.execute(
                    'DELETE FROM mirror_cache WHERE root_dir = ? AND rel_path = ?;',
                    (root_str, old_rel),
                )
                conn.execute(
                    'INSERT OR REPLACE INTO mirror_cache (root_dir, rel_path, stats_hash) VALUES (?, ?, ?);',
                    (root_str, new_rel, str(new_hash)),
                )
                conn.commit()
        except Exception as e:
            logger.warning(f'Could not replace path in database: {path} -> {new_path}. Exception: {e}')
