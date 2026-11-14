# Stock nrf54l15dk: feed MCUboot the shared partition layout. MCUboot is a separate
# sysbuild image that a board/app overlay doesn't reach, and the stock 64K boot trips its
# nRF54L FPROTECT 62K cap. Custom boards bake the layout into their board DTS (MCUboot
# inherits it), so this is guarded to the stock DK — applying it there too would
# double-include the dtsi (ninja: defined as an output multiple times).
if(BOARD MATCHES "nrf54l15dk")
  set(mcuboot_EXTRA_DTC_OVERLAY_FILE
      ${CMAKE_CURRENT_LIST_DIR}/../boards/local/bl54l15u_partitions.dtsi CACHE INTERNAL "")
endif()
