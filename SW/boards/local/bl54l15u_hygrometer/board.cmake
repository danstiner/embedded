# SPDX-License-Identifier: Apache-2.0

board_runner_args(jlink "--device=nRF54L15_M33" "--speed=2000")

# Use jlink as default (listed first), nrfutil as fallback
include(${ZEPHYR_BASE}/boards/common/jlink.board.cmake)
include(${ZEPHYR_BASE}/boards/common/nrfutil.board.cmake)
