if(NOT DEFINED BOARD_REVISION)
  message(FATAL_ERROR
    "Board revision is required for ${BOARD}. "
    "Use one of: 2026v1, 2026v2"
  )
endif()

set(VALID_BOARD_REVISIONS 2026v1 2026v2)

if(NOT BOARD_REVISION IN_LIST VALID_BOARD_REVISIONS)
  message(FATAL_ERROR
    "Invalid board revision '${BOARD_REVISION}' for ${BOARD}. "
    "Valid revisions: ${VALID_BOARD_REVISIONS}"
  )
endif()
