import contextlib
import hashlib
import os
import sqlite3
import time
from collections.abc import Iterable
from os import PathLike
from pathlib import Path

from core.file import CstmPath, CstmPathType, Stats, StatsHash, get_stats_hash
from utils.constants import LOCAL_MIRROR_PATH
from utils.logger import logger
from utils.utils import log_progress, sanitize_path
from utils.volume import get_volume_info


def _compute_exclusions_hash(exclusions: list[str]) -> str:
    """Compute a deterministic 8-byte hash of the sanitized, sorted exclusions list."""
    cleaned = sorted({sanitize_path(e).strip().lower() for e in exclusions if e.strip()})
    payload = '\n'.join(cleaned).encode('utf-8')
    return hashlib.blake2b(payload, digest_size=8).hexdigest()


class MirrorDatabase:
    """
    A class to manage a local mirror database using SQLite.
    Stores cached file paths and their stats hashes in a normalized relational schema
    with exclusion fingerprint invalidation.
    """

    def __init__(self, path: str = LOCAL_MIRROR_PATH, exclusions: None | list[str] = None):
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
                        rel_path TEXT COLLATE NOCASE NOT NULL,
                        stats_hash TEXT NOT NULL,
                        size INTEGER,
                        mtime REAL,
                        PRIMARY KEY (root_dir, rel_path)
                    );
                """)
                conn.execute('CREATE INDEX IF NOT EXISTS idx_mirror_root ON mirror_cache(root_dir);')
                # Automatic column migration for existing databases
                columns = [col[1] for col in conn.execute('PRAGMA table_info(mirror_cache);').fetchall()]
                if 'size' not in columns:
                    conn.execute('ALTER TABLE mirror_cache ADD COLUMN size INTEGER;')
                if 'mtime' not in columns:
                    conn.execute('ALTER TABLE mirror_cache ADD COLUMN mtime REAL;')

                # Migrate existing table to COLLATE NOCASE if created with legacy case-sensitive schema
                table_sql_row = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='mirror_cache';"
                ).fetchone()
                if table_sql_row and 'collate nocase' not in table_sql_row[0].lower():
                    conn.execute('ALTER TABLE mirror_cache RENAME TO mirror_cache_legacy;')
                    conn.execute("""
                        CREATE TABLE mirror_cache (
                            root_dir TEXT NOT NULL,
                            rel_path TEXT COLLATE NOCASE NOT NULL,
                            stats_hash TEXT NOT NULL,
                            size INTEGER,
                            mtime REAL,
                            PRIMARY KEY (root_dir, rel_path)
                        );
                    """)
                    conn.execute("""
                        INSERT OR REPLACE INTO mirror_cache
                        SELECT root_dir, rel_path, stats_hash, size, mtime
                        FROM mirror_cache_legacy;
                    """)
                    conn.execute('DROP TABLE mirror_cache_legacy;')
                    conn.execute('CREATE INDEX IF NOT EXISTS idx_mirror_root ON mirror_cache(root_dir);')

                # Clean up legacy entries where size and mtime were artificially set to 0 by older migrations
                conn.execute(
                    'UPDATE mirror_cache SET size = NULL, mtime = NULL WHERE size = 0 AND (mtime = 0 OR mtime IS NULL);'
                )
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS mirror_metadata (
                        root_dir TEXT PRIMARY KEY,
                        exclusions_hash TEXT NOT NULL,
                        file_count INTEGER NOT NULL DEFAULT 0,
                        last_scanned REAL NOT NULL
                    );
                """)
                self._migrate_legacy_drive_roots(conn)
                conn.commit()
            return True
        except Exception as e:
            logger.warning(f'Could not create database. Exception: {e}')
            return False

    def _migrate_legacy_drive_roots(self, conn: sqlite3.Connection):
        r"""
        Migrate legacy drive letter root_dir entries (e.g. 'E:\...')
        to volume-keyed entries (e.g. '[SERIAL]\...').
        """
        try:
            cache_roots = [
                r[0]
                for r in conn.execute(
                    'SELECT DISTINCT root_dir FROM mirror_cache '
                    "WHERE root_dir NOT LIKE '[%]%' AND root_dir NOT LIKE '\\\\%';"
                ).fetchall()
            ]
            meta_roots = [
                r[0]
                for r in conn.execute(
                    'SELECT DISTINCT root_dir FROM mirror_metadata '
                    "WHERE root_dir NOT LIKE '[%]%' AND root_dir NOT LIKE '\\\\%';"
                ).fetchall()
            ]
            all_legacy = set(cache_roots + meta_roots)
            for legacy_root in all_legacy:
                vol_info = get_volume_info(legacy_root)
                if vol_info and vol_info.serial:
                    sub = legacy_root[2:].lstrip('\\')
                    new_key = f'[{vol_info.serial}]\\{sub}' if sub else f'[{vol_info.serial}]'
                    if new_key != legacy_root:
                        conn.execute(
                            'UPDATE OR REPLACE mirror_cache SET root_dir = ? WHERE root_dir = ?;',
                            (new_key, legacy_root),
                        )
                        conn.execute(
                            'UPDATE OR REPLACE mirror_metadata SET root_dir = ? WHERE root_dir = ?;',
                            (new_key, legacy_root),
                        )
                        logger.info(f"Migrated mirror cache root '{legacy_root}' -> '{new_key}'")
            conn.commit()
        except Exception as e:
            logger.debug(f'Legacy root migration skipped or failed: {e}')

    def _ensure_migrated(self, conn: sqlite3.Connection, db_key: str, mount_root: str):
        """Ensure any unmigrated records matching mount_root are promoted to db_key."""
        if db_key != mount_root:
            conn.execute(
                'UPDATE OR REPLACE mirror_cache SET root_dir = ? WHERE root_dir = ?;',
                (db_key, mount_root),
            )
            conn.execute(
                'UPDATE OR REPLACE mirror_metadata SET root_dir = ? WHERE root_dir = ?;',
                (db_key, mount_root),
            )

    def _resolve_keys(self, root_dir: str | PathLike[str], serial: str | None = None) -> tuple[str, str]:
        r"""
        Resolve (db_key, mount_root) for a root directory.
        - db_key is the persistent identifier stored in SQLite (e.g. '[A4B1-9C32]\Backup\Photos'
          or '\\nas\backup\Photos').
        - mount_root is the current local filesystem mount path (e.g. 'E:\Backup\Photos').
        """
        root_str = sanitize_path(root_dir).rstrip('\\')
        if len(root_str) == 2 and root_str[1] == ':':
            root_str += '\\'

        # UNC path: remote network shares use their UNC path directly
        if root_str.startswith('\\\\'):
            return root_str, root_str

        # Already a volume-keyed string (e.g. '[A4B1-9C32]\Backup'):
        if root_str.startswith('[') and ']' in root_str:
            return root_str, root_str

        # Local drive path: E:\Backup\Photos
        vol_serial = serial
        if not vol_serial:
            vol_info = get_volume_info(root_str)
            if vol_info and vol_info.serial:
                vol_serial = vol_info.serial

        if vol_serial:
            subpath = root_str[2:].lstrip('\\')
            db_key = f'[{vol_serial}]\\{subpath}' if subpath else f'[{vol_serial}]'
            return db_key, root_str

        return root_str, root_str

    def vacuum(self) -> bool:
        """Reclaim unused disk space and defragment SQLite database file."""
        try:
            logger.info(f"Running VACUUM on database '{self.path}'")
            with self._get_connection() as conn:
                conn.execute('VACUUM;')
                conn.commit()
            logger.info(f"VACUUM completed successfully on '{self.path}'")
            return True
        except Exception as e:
            logger.warning(f"Could not VACUUM database '{self.path}'. Exception: {e}")
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

    def exists_table(self, root_dir: str | PathLike[str], serial: str | None = None) -> bool:
        """Check if a valid mirror cache exists for the given root_dir with matching exclusions."""
        db_key, mount_root = self._resolve_keys(root_dir, serial)
        try:
            with self._get_connection() as conn:
                self._ensure_migrated(conn, db_key, mount_root)
                row = conn.execute(
                    'SELECT exclusions_hash, file_count FROM mirror_metadata WHERE root_dir = ?;',
                    (db_key,),
                ).fetchone()
                if not row:
                    return False
                saved_hash, file_count = row
                return saved_hash == self.exclusions_hash and file_count >= 0
        except Exception as e:
            logger.warning(f'Could not check if table exists. Exception: {e}')
            return False

    def exists(self, root_dir: str | PathLike[str], path: CstmPathType, serial: str | None = None) -> bool:
        """Check if the given path exists in the database for the specified root_dir."""
        db_key, mount_root = self._resolve_keys(root_dir, serial)
        rel_path = self._to_rel_path(mount_root, path)
        try:
            with self._get_connection() as conn:
                self._ensure_migrated(conn, db_key, mount_root)
                row = conn.execute(
                    'SELECT 1 FROM mirror_cache WHERE root_dir = ? AND rel_path = ? COLLATE NOCASE;',
                    (db_key, rel_path),
                ).fetchone()
                return row is not None
        except Exception as e:
            logger.warning(f'Could not check if path exists. Exception: {e}')
            return False

    def size(self, root_dir: str | PathLike[str], serial: str | None = None) -> int:
        """Get the number of entries for root_dir in the mirror cache."""
        db_key, mount_root = self._resolve_keys(root_dir, serial)
        try:
            with self._get_connection() as conn:
                self._ensure_migrated(conn, db_key, mount_root)
                row = conn.execute(
                    'SELECT file_count FROM mirror_metadata WHERE root_dir = ?;',
                    (db_key,),
                ).fetchone()
                if row is not None:
                    return row[0]
                count_row = conn.execute(
                    'SELECT COUNT(*) FROM mirror_cache WHERE root_dir = ?;',
                    (db_key,),
                ).fetchone()
                return count_row[0] if count_row else 0
        except Exception as e:
            logger.warning(f'Could not get size of database. Exception: {e}')
            return 0

    def reset(self, root_dir: str | PathLike[str], serial: str | None = None) -> bool:
        """Reset the database for the given root_dir."""
        db_key, mount_root = self._resolve_keys(root_dir, serial)
        try:
            with self._get_connection() as conn:
                self._ensure_migrated(conn, db_key, mount_root)
                conn.execute('DELETE FROM mirror_cache WHERE root_dir = ?;', (db_key,))
                conn.execute('DELETE FROM mirror_metadata WHERE root_dir = ?;', (db_key,))
                conn.commit()
                logger.info(f"Reset mirror cache for '{root_dir}' [{db_key}]")
            return True
        except Exception as e:
            logger.warning(f"Could not reset database for '{root_dir}'. Exception: {e}")
            return False

    def get_paths(self, root_dir: str | PathLike[str], serial: str | None = None) -> set[CstmPath]:
        """Retrieve all paths for root_dir as a set of CstmPath objects."""
        db_key, mount_root = self._resolve_keys(root_dir, serial)
        try:
            with self._get_connection() as conn:
                self._ensure_migrated(conn, db_key, mount_root)
                cursor = conn.execute(
                    'SELECT rel_path, stats_hash, size, mtime FROM mirror_cache WHERE root_dir = ?;',
                    (db_key,),
                )
                rows = cursor.fetchall()
                return {
                    CstmPath(
                        self._to_full_path(mount_root, rel_path),
                        root_dir=mount_root,
                        stats_hash=StatsHash(stats_hash),
                        stats=Stats(size, mtime) if (size is not None and mtime is not None and mtime > 0) else None,
                    )
                    for rel_path, stats_hash, size, mtime in rows
                }
        except Exception as e:
            logger.warning(f'Could not open DB to get keys. Exception: {e}')
            return set()

    def add_path(
        self,
        root_dir: str | PathLike[str],
        path: Iterable[CstmPathType] | CstmPathType,
        serial: str | None = None,
    ):
        """Add or update paths in the mirror cache using optimized batch transactions."""
        db_key, mount_root = self._resolve_keys(root_dir, serial)
        items = list(path) if isinstance(path, Iterable) and not isinstance(path, str | bytes | PathLike) else [path]

        if not items:
            try:
                with self._get_connection() as conn:
                    self._ensure_migrated(conn, db_key, mount_root)
                    conn.execute(
                        'INSERT OR REPLACE INTO mirror_metadata (root_dir, exclusions_hash, file_count, last_scanned) '
                        'VALUES (?, ?, ?, ?);',
                        (db_key, self.exclusions_hash, 0, time.time()),
                    )
                    conn.commit()
            except Exception as e:
                logger.critical(f"Could not open DB to record mirror metadata for '{root_dir}': {e}")
            return

        start_time = time.time()
        number_files = len(items)
        rows: list[tuple[str, str, str, int | None, float | None]] = []

        for i, p in enumerate(items):
            try:
                rel = self._to_rel_path(mount_root, p)
                # Reuse cached stats_hash if available to prevent redundant network I/O
                stats_hash = getattr(p, '_stats_hash', None) or getattr(p, 'stats_hash', None)
                if not stats_hash:
                    stats_hash = get_stats_hash(p)
                st = getattr(p, 'cached_stats', getattr(p, '_stats', None))
                is_unc = str(p).startswith('\\\\') or mount_root.startswith('\\\\')
                if st is None and not is_unc:
                    with contextlib.suppress(Exception):
                        st = getattr(p, 'stats', None)
                if st is None and not is_unc:
                    with contextlib.suppress(Exception):
                        os_st = os.stat(str(p))
                        st = Stats(os_st.st_size, os_st.st_mtime)
                size_val = st.st_size if st is not None else None
                mtime_val = st.st_mtime if st is not None else None
                rows.append((db_key, rel, str(stats_hash), size_val, mtime_val))
                if number_files > 10_000:
                    log_progress('Prepared', i, number_files, start_time, interval=10_000)
            except Exception as e:
                logger.error(f"Could not process file '{p}' for local mirror. Exception: {e}")

        try:
            with self._get_connection() as conn:
                self._ensure_migrated(conn, db_key, mount_root)
                saved_hash = conn.execute(
                    'SELECT exclusions_hash FROM mirror_metadata WHERE root_dir = ?;',
                    (db_key,),
                )
                saved_hash_row = saved_hash.fetchone() if saved_hash else None
                if saved_hash_row and saved_hash_row[0] != self.exclusions_hash:
                    conn.execute('DELETE FROM mirror_cache WHERE root_dir = ?;', (db_key,))

                conn.executemany(
                    'INSERT OR REPLACE INTO mirror_cache '
                    '(root_dir, rel_path, stats_hash, size, mtime) VALUES (?, ?, ?, ?, ?);',
                    rows,
                )
                count = conn.execute(
                    'SELECT COUNT(*) FROM mirror_cache WHERE root_dir = ?;',
                    (db_key,),
                ).fetchone()[0]
                conn.execute(
                    'INSERT OR REPLACE INTO mirror_metadata (root_dir, exclusions_hash, file_count, last_scanned) '
                    'VALUES (?, ?, ?, ?);',
                    (db_key, self.exclusions_hash, count, time.time()),
                )
                conn.commit()
                with contextlib.suppress(Exception):
                    conn.execute('PRAGMA wal_checkpoint(PASSIVE);')
        except Exception as e:
            logger.critical(f"Could not open DB to add file(s): '{path}'. Exception: {e}")

    def remove_path(
        self,
        root_dir: str | PathLike[str],
        path: CstmPathType | Iterable[CstmPathType],
        serial: str | None = None,
    ) -> bool:
        """Remove path(s) from the mirror cache."""
        db_key, mount_root = self._resolve_keys(root_dir, serial)
        items = list(path) if isinstance(path, Iterable) and not isinstance(path, str | bytes | PathLike) else [path]

        if not items:
            return True

        rows = [(db_key, self._to_rel_path(mount_root, p)) for p in items]

        try:
            with self._get_connection() as conn:
                self._ensure_migrated(conn, db_key, mount_root)
                deleted_count = 0
                for r_dir, rel in rows:
                    cur = conn.execute(
                        'DELETE FROM mirror_cache WHERE root_dir = ? AND rel_path = ? COLLATE NOCASE;',
                        (r_dir, rel),
                    )
                    if cur.rowcount > 0:
                        deleted_count += 1
                    else:
                        logger.warning(f"Key does not exist in database: '{rel}'")

                count = conn.execute(
                    'SELECT COUNT(*) FROM mirror_cache WHERE root_dir = ?;',
                    (db_key,),
                ).fetchone()[0]
                conn.execute(
                    'UPDATE mirror_metadata SET file_count = ?, last_scanned = ? WHERE root_dir = ?;',
                    (count, time.time(), db_key),
                )
                conn.commit()
                return deleted_count > 0 or len(rows) == 0
        except Exception as e:
            logger.warning(f"Could not open DB to remove file(s): '{path}'. Exception: {e}")
            return False

    def replace_path(
        self,
        root_dir: str | PathLike[str],
        path: CstmPathType,
        new_path: CstmPathType,
        serial: str | None = None,
    ):
        """Remove old path and add new_path to the database atomically."""
        db_key, mount_root = self._resolve_keys(root_dir, serial)
        old_rel = self._to_rel_path(mount_root, path)
        new_rel = self._to_rel_path(mount_root, new_path)
        new_hash = getattr(new_path, '_stats_hash', None) or getattr(new_path, 'stats_hash', None)
        if not new_hash:
            new_hash = get_stats_hash(new_path)
        new_st = getattr(new_path, 'cached_stats', getattr(new_path, '_stats', None))
        if new_st is None:
            with contextlib.suppress(Exception):
                new_st = getattr(new_path, 'stats', None)
        if new_st is None:
            with contextlib.suppress(Exception):
                os_st = os.stat(str(new_path))
                new_st = Stats(os_st.st_size, os_st.st_mtime)
        new_size = new_st.st_size if new_st is not None else None
        new_mtime = new_st.st_mtime if new_st is not None else None

        try:
            with self._get_connection() as conn:
                self._ensure_migrated(conn, db_key, mount_root)
                if new_size is None and new_mtime is None:
                    old_row = conn.execute(
                        'SELECT size, mtime FROM mirror_cache WHERE root_dir = ? AND rel_path = ? COLLATE NOCASE;',
                        (db_key, old_rel),
                    ).fetchone()
                    if old_row:
                        new_size, new_mtime = old_row[0], old_row[1]

                conn.execute(
                    'DELETE FROM mirror_cache WHERE root_dir = ? AND rel_path = ? COLLATE NOCASE;',
                    (db_key, old_rel),
                )
                conn.execute(
                    'INSERT OR REPLACE INTO mirror_cache '
                    '(root_dir, rel_path, stats_hash, size, mtime) VALUES (?, ?, ?, ?, ?);',
                    (db_key, new_rel, str(new_hash), new_size, new_mtime),
                )
                conn.commit()
        except Exception as e:
            logger.warning(f"Could not replace path in database: '{path}' -> '{new_path}'. Exception: {e}")
