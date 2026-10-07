"""Custom source modules.

Add one module per source that a generic adapter cannot express, then point
new_business_sources.json at adapter "custom.<module>". The module must
define Adapter(entry) subclassing SourceAdapter.
"""
