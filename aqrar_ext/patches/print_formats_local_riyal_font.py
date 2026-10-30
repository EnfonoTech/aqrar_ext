"""Point every print format's Saudi Riyal font link at the copy in this app, so
Download PDF no longer waits two minutes on the CDN. See utils/local_fonts.py."""

from aqrar_ext.aqrar_ext.utils.local_fonts import localise_all_print_formats


def execute():
	localise_all_print_formats()
