"""Natural-language stock screener (Track 2, Feature B) — a sibling of
quorum/strategy/, not an extension of it. A screen ranks a universe by a
weighted blend of metrics and returns a table; it never trades, never
writes to the decision log's run/signal/target chain, and never becomes
a bar-loop feature (see the plan's "Explicitly not doing" section for why
fundamentals stay out of quorum/strategy/schema.py entirely).
"""
