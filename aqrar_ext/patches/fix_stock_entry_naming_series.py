"""CR-010 — realign the Stock Entry naming counter.

Documents imported or created outside the naming machinery can leave
`tabSeries.current` behind the highest name actually in use, so the next
Stock Entry collides with an existing one. Re-point the counter at the true
maximum for every Stock Entry series present.
"""

import re

import frappe

# MAT-STE-2026-00042 → 42; ignores amended suffixes such as "-1".
SERIES_NAME = re.compile(r"^(?P<prefix>.*?)(?P<counter>\d+)$")


def execute():
	prefixes = frappe.db.sql(
		"""
		SELECT DISTINCT SUBSTRING(name, 1, CHAR_LENGTH(name) - 5) AS prefix
		FROM `tabStock Entry`
		WHERE name REGEXP '[0-9]{5}$'
		""",
		as_dict=True,
	)

	for row in prefixes:
		prefix = row.prefix
		if not prefix:
			continue
		_sync_series(prefix)


def _sync_series(prefix):
	names = frappe.db.sql(
		"""
		SELECT name FROM `tabStock Entry`
		WHERE name LIKE %(like)s
		""",
		{"like": prefix + "%"},
		pluck=True,
	)

	highest = 0
	for name in names:
		match = SERIES_NAME.match(name[len(prefix) :])
		# Only names that are exactly prefix + digits count; amended documents
		# ("...-00042-1") must not be parsed as a counter.
		if match and not match.group("prefix"):
			highest = max(highest, int(match.group("counter")))

	if not highest:
		return

	# `tabSeries` is a framework table with no DocType, so query it directly.
	row = frappe.db.sql(
		"SELECT current FROM `tabSeries` WHERE name = %(name)s", {"name": prefix}
	)
	current = row[0][0] if row else None

	if current is not None and int(current) >= highest:
		return

	if current is None:
		frappe.db.sql(
			"INSERT INTO `tabSeries` (name, current) VALUES (%(name)s, %(current)s)",
			{"name": prefix, "current": highest},
		)
	else:
		frappe.db.sql(
			"UPDATE `tabSeries` SET current = %(current)s WHERE name = %(name)s",
			{"name": prefix, "current": highest},
		)
