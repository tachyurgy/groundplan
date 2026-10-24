"""Synthetic Okafor-Lindqvist document set (SPEC §4.1).

reportlab's ASCII85 stream encoding is a process-wide switch; the scan writer needs it off (raw JPEG bytes), so it is
off for every PDF this package writes. Otherwise text-layer bytes would depend on whether a scan was written first.
"""

from reportlab import rl_config

rl_config.useA85 = 0
