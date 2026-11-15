# Board revision validation for bl54l15u_hygrometer.
#
# When no revision is given on the command line, board.yml's `default: 2026v4`
# already populates BOARD_REVISION, so plain builds target the current 2026v4
# hardware. This file just guards against typos in an explicit @revision.

if(NOT DEFINED BOARD_REVISION)
  set(BOARD_REVISION 2026v4)
endif()

set(VALID_BOARD_REVISIONS 2026v3 2026v4)

if(NOT BOARD_REVISION IN_LIST VALID_BOARD_REVISIONS)
  message(FATAL_ERROR
    "Invalid board revision '${BOARD_REVISION}' for ${BOARD}. "
    "Valid revisions: ${VALID_BOARD_REVISIONS}"
  )
endif()
