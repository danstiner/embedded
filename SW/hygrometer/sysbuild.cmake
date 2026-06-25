# Stock nrf54l15dk only: hand MCUboot the shared 48 KiB partition layout.
#
# A board overlay reaches only the application image; MCUboot is a separate sysbuild
# image. The custom boards bake bl54l15u_partitions.dtsi into their board DTS, so their
# MCUboot image inherits it and needs nothing here. The stock DK ships a 64 KiB
# boot_partition that MCUboot's nRF54L FPROTECT rejects (>62 KiB), so feed our layout to
# its MCUboot image too. (A board-extension overlay can't do this — board dirs only apply
# revision-suffixed overlays — so the per-image hook is the idiomatic route; see the
# bl54l15u_devkit board's sysbuild.cmake for the same pattern.)
if(BOARD MATCHES "nrf54l15dk")
  list(APPEND mcuboot_EXTRA_DTC_OVERLAY_FILE
       ${CMAKE_CURRENT_LIST_DIR}/boards/nrf54l15dk_mcuboot.overlay)
  set(mcuboot_EXTRA_DTC_OVERLAY_FILE ${mcuboot_EXTRA_DTC_OVERLAY_FILE}
      CACHE INTERNAL "nrf54l15dk MCUboot partition overlay" FORCE
  )
endif()
