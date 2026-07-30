# License inventory

The inventory is the governed replacement for the manual master tracker. Every
record belongs to exactly one `legal_entity`, jurisdiction, and license type.
The active-record uniqueness control prevents accidental duplicate licenses for
the same scope while allowing historical surrendered, revoked, expired, or
not-required records.

`filing_channel` describes how work is performed (`NMLS`, state/local portal,
paper, email, vendor managed, multiple, or unknown). It does not determine
whether a license is required and it does not mean outside-NMLS supplements are
complete.

Status changes append `license_status_events`; callers do not overwrite history.
Renewed evidence may update expiration and renewal dates only through the
reviewer-controlled evidence operation. Source confidence and last verification
remain visible. Active records without governed evidence are data-quality
findings.

Tracker migration is dry-run first. Resolve every legal entity, jurisdiction,
and license type before applying. Verified evidence wins over conflicting
spreadsheet values; conflicts are never silently overwritten.
