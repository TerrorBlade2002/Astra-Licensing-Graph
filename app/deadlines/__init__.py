"""Deadline and escalation engine.

Statutory dates come from source-backed rules; internal target dates are derived
from configurable lead times. No universal 30-day window and no blanket
weekend/holiday shifting: every rule carries its own adjustment policy because
many regulators do not move a statutory date off a weekend.
"""
