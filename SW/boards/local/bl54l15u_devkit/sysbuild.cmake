# Disable npm1304 PMIC in MCUboot - the mfd_npm13xx driver requires kernel
# workqueue/mutex that are unavailable in MCUboot's minimal kernel.
list(APPEND mcuboot_EXTRA_DTC_OVERLAY_FILE ${CMAKE_CURRENT_LIST_DIR}/mcuboot.overlay)
set(mcuboot_EXTRA_DTC_OVERLAY_FILE ${mcuboot_EXTRA_DTC_OVERLAY_FILE}
    CACHE INTERNAL "Board-level MCUboot overlay" FORCE
)
