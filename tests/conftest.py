import importlib.util

# Run the suite without wagtail-localize too (it's an optional extra).
collect_ignore = []
if importlib.util.find_spec("wagtail_localize") is None:
    collect_ignore.append("test_translations.py")
