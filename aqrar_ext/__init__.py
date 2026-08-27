__version__ = "0.0.1"

# NOTE: this module previously imported aqrar_ext.aqrar_ext.overrides.stock_ledger,
# which monkey-patched erpnext's Stock Ledger report at app-import time. The
# matching client script was never registered in hooks.py, so the extra filters
# it supported could not be set from the UI. CR-011 is served by this app's own
# "Stock Ledger Report" instead, so the patch has been removed rather than
# re-wired: patching another app's module globals on import breaks silently on
# every ERPNext upgrade.
