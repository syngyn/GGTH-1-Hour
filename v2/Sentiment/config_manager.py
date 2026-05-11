"""
GGTH Predictor Configuration Manager v2.2
Handles loading and saving configuration, especially MT5 Files path.

Fixes v2.1 → v2.2:
  - Unknown keys in config.json now produce a warning (was silently ignored).
    A typo like "mt5files_path" used to be dropped on load with no feedback.
  - Replaced print() with logger so warnings/errors land in ggth_predictor.log
    alongside output from the rest of the system.
  - Header version aligned with the rest of the GGTH stack (v2.x for support
    modules, v9.5 for predictor, v1.17 for EA).

Fixes v2.0 → v2.1:
  - set() renamed to set_value() — 'set' shadowed the Python built-in
  - get_default_models() fallback now references DEFAULT_CONFIG instead of a
    hardcoded list that contradicted it (was all-5 models vs 3 in DEFAULT_CONFIG)
  - auto_detect_mt5_path() sorts candidates by mtime so the most-recently-used
    terminal wins when multiple MT5 installations exist
  - __file__ wrapped in os.path.abspath() so the config path is stable
    regardless of the working directory at launch time
  - Singleton exposes reload() so callers can refresh after an on-disk change
  - _load_config() surfaces a clear ValueError on malformed JSON instead of
    silently falling back to defaults and masking the real problem
"""

import os
import glob
import json
from typing import Optional, Dict, Any

try:
    from logger import get_logger
    _log = get_logger("ggth.config")
except ImportError:
    # logger module unavailable (e.g. running config_manager standalone before
    # the rest of the package is on sys.path). Fall back to a print shim with
    # the same .info/.warning/.error surface so call sites don't change.
    class _PrintLogger:
        def info(self,    msg, *a): print(("[CFG] " + msg) % a if a else "[CFG] " + msg)
        def warning(self, msg, *a): print(("[CFG WARN] " + msg) % a if a else "[CFG WARN] " + msg)
        def error(self,   msg, *a): print(("[CFG ERR] "  + msg) % a if a else "[CFG ERR] "  + msg)
    _log = _PrintLogger()

# Stable path to this file's directory — safe regardless of CWD at launch time
_HERE = os.path.dirname(os.path.abspath(__file__))

# Public schema version for config.json. Bump this only when the on-disk
# config schema changes (new required keys, type changes, etc.) — NOT for
# every release. Importable by other modules (e.g. ggth_gui.py's raw-JSON
# fallback path) so the version field never has to be hardcoded twice.
CONFIG_SCHEMA_VERSION = "2.3"


class ConfigManager:
    """Manages configuration for GGTH Predictor."""

    DEFAULT_CONFIG: Dict[str, Any] = {
        "mt5_files_path":             "",
        "version":                    CONFIG_SCHEMA_VERSION,
        # v2.3 cleanup: removed 6 unused keys that nothing in the codebase
        # ever read: models_dir, use_kalman (GUI uses its own checkbox state),
        # default_symbol (--symbol CLI arg drives this), prediction_interval_minutes
        # (--interval CLI arg), default_models, available_models. They survived
        # in DEFAULT_CONFIG / CONFIG_SCHEMA from earlier versions where a
        # config-driven model registry was planned but never wired up.
        # The "unknown key warning" in _validate_config will surface these
        # keys if they still exist in a user's config.json on next load,
        # which is the right place for the operator to learn they're stale.
    }

    # Expected types for every key in DEFAULT_CONFIG.
    # _load_config() validates the on-disk JSON against this schema so a
    # hand-edited config.json with wrong types raises a clear error at startup
    # rather than a confusing TypeError deep inside the predictor.
    CONFIG_SCHEMA: Dict[str, type] = {
        "mt5_files_path":             str,
        "version":                    str,
    }

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialise the config manager.

        Args:
            config_path: Path to config.json.
                         Defaults to config.json in the same directory as this
                         script (resolved with abspath, so CWD doesn't matter).
        """
        if config_path is None:
            config_path = os.path.join(_HERE, "config.json")

        self.config_path = config_path
        self.config = self._load_config()

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------
    def _validate_config(self, cfg: Dict[str, Any]) -> None:
        """
        Type-check every key in cfg against CONFIG_SCHEMA.

        Raises ValueError with a clear, actionable message if any value has the
        wrong type (e.g. "prediction_interval_minutes" stored as a string).
        Unknown keys (not in CONFIG_SCHEMA) produce a warning so typos like
        "mt5files_path" (missing underscore) are surfaced rather than silently
        dropped on merge with DEFAULT_CONFIG.
        """
        # v2.2: surface unknown keys (typos, abandoned-feature config).
        # Skip private keys starting with _ so callers can stash debugging
        # state in the file without triggering noise.
        unknown = [k for k in cfg.keys()
                   if k not in self.CONFIG_SCHEMA and not k.startswith('_')]
        if unknown:
            _log.warning(
                "config.json has unknown key(s): %s — typo, "
                "or stale from an older version? They will be loaded but "
                "ignored by this build.", unknown,
            )

        errors = []
        for key, expected_type in self.CONFIG_SCHEMA.items():
            if key not in cfg:
                continue
            val = cfg[key]
            # bool is a subclass of int in Python — treat separately
            if expected_type is bool:
                if not isinstance(val, bool):
                    errors.append(
                        f"  '{key}': expected bool, "
                        f"got {type(val).__name__} ({val!r})"
                    )
            elif not isinstance(val, expected_type):
                errors.append(
                    f"  '{key}': expected {expected_type.__name__}, "
                    f"got {type(val).__name__} ({val!r})"
                )
        if errors:
            raise ValueError(
                "config.json has type errors — fix and restart:\n"
                + "\n".join(errors)
            )

    def _load_config(self) -> Dict[str, Any]:
        """
        Load configuration from disk and merge with defaults.

        Raises:
            ValueError: If the file exists but contains invalid JSON.
                        (Callers should catch this and report it clearly rather
                        than silently falling back to defaults.)
        """
        if not os.path.exists(self.config_path):
            return self.DEFAULT_CONFIG.copy()

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                on_disk = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"config.json is malformed and cannot be parsed.\n"
                f"File: {self.config_path}\n"
                f"Detail: {exc}\n\n"
                "Fix or delete config.json, then restart."
            ) from exc
        except OSError as exc:
            _log.warning("could not read %s: %s. Using default configuration.",
                         self.config_path, exc)
            return self.DEFAULT_CONFIG.copy()

        # Merge: defaults first so new keys added to DEFAULT_CONFIG are picked up
        merged = self.DEFAULT_CONFIG.copy()
        merged.update(on_disk)
        self._validate_config(merged)
        return merged

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------
    def reload(self) -> None:
        """Re-read config.json from disk. Useful when the file may have changed."""
        self.config = self._load_config()

    def save_config(self) -> bool:
        """
        Persist the current in-memory config to disk.

        Returns:
            True on success, False on failure (error is printed).
        """
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
            return True
        except OSError as exc:
            _log.error("could not save config to %s: %s", self.config_path, exc)
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """Return a configuration value."""
        return self.config.get(key, default)

    def set_value(self, key: str, value: Any) -> None:
        """
        Set a configuration value in memory.
        Call save_config() afterwards to persist.

        Note: previously named set(), which shadowed the Python built-in.
        """
        self.config[key] = value

    # -------------------------------------------------------------------------
    # MT5 path helpers
    # -------------------------------------------------------------------------
    def get_mt5_files_path(self) -> str:
        """
        Return the validated MT5 Files directory path.

        Raises:
            ValueError: If the path is not configured or does not exist on disk.
        """
        path = self.config.get("mt5_files_path", "")

        if not path:
            raise ValueError(
                "MT5 Files path is not configured.\n\n"
                "Run setup_wizard.bat, or manually create config.json with:\n"
                "{\n"
                '  "mt5_files_path": "C:\\\\Users\\\\YourName\\\\AppData\\\\Roaming\\\\'
                'MetaQuotes\\\\Terminal\\\\HASH\\\\MQL5\\\\Files"\n'
                "}"
            )

        if not os.path.exists(path):
            raise ValueError(
                f"MT5 Files path does not exist: {path}\n\n"
                "Please update config.json with the correct path."
            )

        return path

    def set_mt5_files_path(self, path: str) -> bool:
        """
        Validate, set, and immediately persist the MT5 Files directory path.

        Args:
            path: Absolute path to the MT5 Files directory.

        Returns:
            True if the path exists and was saved, False otherwise.
        """
        if not os.path.exists(path):
            _log.error("directory does not exist: %s", path)
            return False

        self.config["mt5_files_path"] = path
        return self.save_config()

    def auto_detect_mt5_path(self) -> Optional[str]:
        """
        Attempt to auto-detect the MT5 Files directory.

        When multiple Terminal installations exist (e.g. demo + live accounts),
        the one modified most recently is returned — that is most likely the
        active one.

        Returns:
            Absolute path if found, None otherwise.
        """
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            terminal_base = os.path.join(appdata, "MetaQuotes", "Terminal")
            if os.path.exists(terminal_base):
                matches = glob.glob(
                    os.path.join(terminal_base, "*", "MQL5", "Files")
                )
                if matches:
                    # Sort by directory mtime descending — most recently used first
                    matches.sort(key=os.path.getmtime, reverse=True)
                    return matches[0]

        # Fallback: standard Program Files installation
        program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        pf_path = os.path.join(program_files, "MetaTrader 5", "MQL5", "Files")
        if os.path.exists(pf_path):
            return pf_path

        return None

    # v2.3 cleanup: removed get_default_models() / get_available_models().
    # Both were public methods but no callsite anywhere in the codebase
    # invoked them. Their underlying config keys (default_models /
    # available_models) were also removed from DEFAULT_CONFIG above.
    # If the model registry is ever wired up via config, the right place
    # would be in model_builders.py — not here.

    # -------------------------------------------------------------------------
    # Diagnostics
    # -------------------------------------------------------------------------
    def print_config(self) -> None:
        """Print the current configuration to stdout."""
        print("\n" + "=" * 50)
        print("  GGTH Predictor Configuration v2.2")
        print("=" * 50)
        print(f"Config file: {self.config_path}")
        print("\nSettings:")
        for key, value in self.config.items():
            print(f"  {key}: {value}")
        print("=" * 50 + "\n")


# =============================================================================
# Singleton
# =============================================================================
_config_instance: Optional[ConfigManager] = None


def get_config() -> ConfigManager:
    """
    Return the global ConfigManager instance (singleton).

    Call get_config().reload() if you need to pick up on-disk changes made
    after the first call.
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = ConfigManager()
    return _config_instance


def get_mt5_files_path() -> str:
    """Convenience wrapper: return the validated MT5 Files path."""
    return get_config().get_mt5_files_path()


# =============================================================================
# CLI utility
# =============================================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="GGTH Predictor Configuration Utility v2.2"
    )
    parser.add_argument("--set-mt5-path",  help="Set MT5 Files directory path")
    parser.add_argument("--auto-detect",   action="store_true",
                        help="Auto-detect MT5 path (picks most-recently-used terminal)")
    parser.add_argument("--show",          action="store_true",
                        help="Show current configuration")
    parser.add_argument("--reload",        action="store_true",
                        help="Force re-read of config.json (useful after manual edits)")

    args = parser.parse_args()

    try:
        config = get_config()
    except ValueError as e:
        print(f"[ERROR] {e}")
        raise SystemExit(1)

    if args.reload:
        config.reload()
        print("Configuration reloaded from disk.")

    if args.set_mt5_path:
        if config.set_mt5_files_path(args.set_mt5_path):
            print(f"✓ MT5 path set to: {args.set_mt5_path}")
        else:
            print("✗ Failed to set MT5 path")

    if args.auto_detect:
        path = config.auto_detect_mt5_path()
        if path:
            print(f"Found MT5 installation at: {path}")
            response = input("Use this path? (y/n): ")
            if response.lower() == "y":
                if config.set_mt5_files_path(path):
                    print("✓ MT5 path configured successfully")
        else:
            print("Could not auto-detect MT5 installation.")

    if args.show or not any(
        [args.set_mt5_path, args.auto_detect, args.reload]
    ):
        config.print_config()