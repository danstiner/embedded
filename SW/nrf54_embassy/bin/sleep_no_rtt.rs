#![no_std]
#![no_main]

use embassy_executor::Spawner;
use embassy_nrf::gpio::{Level, Output, OutputDrive};
use embassy_time::Timer;
use nrf_pac as pac;
use {defmt_rtt as _, panic_probe as _};

/// GRTC runs at 1 MHz, so 1,000,000 ticks = 1 second
const GRTC_CLOCK_FREQ: u64 = 1_000_000;

/// CPU frequency for delay calculations (128 MHz for nRF54L15)
const CPU_FREQ_MHZ: u32 = 128;

/// Maximum time to wait for CC latch (from Zephyr: MAX_CC_LATCH_WAIT_TIME_US)
/// This is the time needed for the compare value to be properly latched in hardware
const CC_LATCH_WAIT_US: u32 = 77;

/// Start GRTC and configure it for System OFF wakeup
///
/// Based on Zephyr nrf_grtc_timer.c implementation and nrfx HAL documentation.
/// The GRTC (Global Real-Time Counter) is a 52-bit counter running at 1 MHz that can
/// wake the system from System OFF mode when a compare event occurs.
fn start_grtc() {
    let grtc = &pac::GRTC_S;

    // ===== SLEEP CONFIGURATION REGISTERS =====
    // These registers control how GRTC behaves when the system enters sleep/System OFF.
    // Values are from Zephyr's default sleep configuration (drivers/timer/nrf_grtc_timer.c):
    // - Default: 5 LFCLK cycles delay, 4 LFCLK cycles pre-wakeup, automatic mode enabled

    // TIMEOUT: Number of LFCLK (32.768 kHz) cycles to wait after all CPUs sleep before
    // stopping SYSCOUNTER. This allows pending operations to complete.
    // Default from Zephyr: 5 cycles = ~152 microseconds
    grtc.timeout().write(|w| w.set_value(5));

    // WAKETIME: Number of LFCLK cycles before the scheduled EVENTS_COMPARE event to
    // wake up the APB registers. This ensures the peripheral is ready when the event fires.
    // Default from Zephyr: 4 cycles = ~122 microseconds
    grtc.waketime().write(|w| w.set_value(4));

    // ===== CLOCK SOURCE CONFIGURATION =====
    // CRITICAL: Must explicitly select LFXO as the clock source for GRTC!
    // The CLKCFG register selects which low-frequency clock drives the GRTC SYSCOUNTER.
    // For System OFF wakeup, LFXO (external 32.768 kHz crystal) is REQUIRED because
    // it's the only clock that remains active in System OFF mode.
    //
    // Options:
    // - LFXO: External 32.768 kHz crystal (only clock running in System OFF)
    // - SYSTEM_LFCLK: Use the system's configured LFCLK source
    // - LFLPRC: Low-power RC oscillator (stops in System OFF)
    grtc.clkcfg().write(|w| w.set_clksel(pac::grtc::vals::Clksel::LFXO));

    // ===== MODE REGISTER CONFIGURATION =====
    // The MODE register controls SYSCOUNTER enable and automatic sleep/wake behavior.
    grtc.mode().write(|w| {
        // SYSCOUNTEREN: Enable the GRTC SYSCOUNTER to start counting
        w.set_syscounteren(true);

        // AUTOEN: Automatic mode for keeping SYSCOUNTER active.
        // DEFAULT mode: SYSCOUNTER stays active based on ACTIVE register requests from domains.
        // This is the correct mode for System OFF wakeup - the ACTIVE register request
        // (set below) keeps SYSCOUNTER running even when all CPUs are sleeping.
        //
        // Note: CPU_ACTIVE mode would STOP the counter in System OFF since all CPUs sleep!
        w.set_autoen(pac::grtc::vals::Autoen::DEFAULT);
    });

    // ===== SYSCOUNTER ACTIVE REQUEST (KEEPRUNNING) =====
    // Request from domain 0 to keep SYSCOUNTER active during System OFF.
    // This is the documented way to access what was previously the undocumented
    // "KEEPRUNNING" register at offset 0x704.
    //
    // The nRF54L15 has 4 SYSCOUNTER domains (0-3), each can request the counter
    // to stay active. Domain 0 is typically used for the main application CPU.
    grtc.syscounter(0).active().write(|w| w.set_active(true));

    // ===== START THE COUNTER =====
    // Trigger the TASKS_START to begin counting from current value
    grtc.tasks_start().write_value(1);
}

/// Configure GRTC to wake from System OFF after specified ticks
///
/// This function implements the documented GRTC wakeup procedure based on:
/// - Zephyr z_nrf_grtc_wakeup_prepare() in drivers/timer/nrf_grtc_timer.c
/// - nrfx GRTC driver in hal_nordic/nrfx
/// - Nordic nRF54L15 Product Specification
///
/// Critical requirements:
/// 1. All other CC channels must be disabled to prevent spurious wakes
/// 2. The wakeup channel interrupt must be DISABLED (hardware wakes directly)
/// 3. Wake time must be ABSOLUTE (current time + delay), not relative
/// 4. Must wait for CC value to latch in hardware (~77us busy wait)
fn configure_grtc_wakeup(ticks: u64) {
    let grtc = &pac::GRTC_S;

    // ===== STEP 1: DISABLE ALL CHANNELS =====
    // Critical: All 12 compare/capture channels must be disabled before configuring
    // the wakeup channel. Any active channel could cause unwanted wakeup or prevent
    // System OFF entry. The nRF54L15 GRTC has 12 CC channels (0-11).
    for i in 0..12 {
        grtc.cc(i).ccen().write(|w| w.set_active(false));
    }

    // ===== STEP 2: DISABLE ALL INTERRUPTS =====
    // Clear interrupt enable for all compare channels. For System OFF wakeup,
    // interrupts are not needed - the hardware compare event triggers wake directly.
    grtc.intenclr(0).write(|w| {
        w.set_compare0(true);
        w.set_compare1(true);
        w.set_compare2(true);
        w.set_compare3(true);
        w.set_compare4(true);
        w.set_compare5(true);
        w.set_compare6(true);
        w.set_compare7(true);
        w.set_compare8(true);
        w.set_compare9(true);
        w.set_compare10(true);
        w.set_compare11(true);
    });

    // ===== STEP 3: CLEAR ALL PENDING EVENTS =====
    // Clear any pending compare events that might trigger false wakeups
    for i in 0..12 {
        grtc.events_compare(i).write_value(0);
    }

    // ===== STEP 4: CAPTURE CURRENT TIME =====
    // Use CC[0] as a capture channel to atomically read the current 52-bit counter value.
    // The capture task writes the current SYSCOUNTER to CC[0].
    grtc.tasks_capture(0).write_value(1);

    // Read the 64-bit compare value (only lower 52 bits are valid)
    let now_low = grtc.cc(0).ccl().read();
    let now_high = grtc.cc(0).cch().read().cch();
    let now = (now_high as u64) << 32 | now_low as u64;

    // ===== STEP 5: CALCULATE ABSOLUTE WAKE TIME =====
    // CRITICAL: The GRTC compare channels expect ABSOLUTE time, not relative delay!
    // Common mistake: passing a delay like "5000000" is interpreted as an absolute
    // timestamp, which is likely in the past if the counter has been running.
    //
    // Correct: Read current time and add the delay to get future absolute time.
    // Use wrapping_add to handle 64-bit overflow correctly.
    let wake_time = now.wrapping_add(ticks);
    let wake_low = wake_time as u32;
    let wake_high = (wake_time >> 32) as u32;

    // ===== STEP 6: SET COMPARE VALUE FOR WAKEUP =====
    // Use CC[1] as the wakeup channel. Write both low and high 32-bit parts.
    grtc.cc(1).ccl().write_value(wake_low);
    grtc.cc(1).cch().write_value(pac::grtc::regs::Cch(wake_high));

    // ===== STEP 7: ENABLE ONLY THE WAKEUP CHANNEL =====
    // Enable CC[1] to generate compare events. All other channels remain disabled.
    grtc.cc(1).ccen().write(|w| w.set_active(true));

    // ===== STEP 8: ENSURE INTERRUPT STAYS DISABLED =====
    // Explicitly disable interrupt for CC[1]. In System OFF mode, the compare event
    // wakes the device via hardware mechanism, NOT via interrupt routing.
    // This is confirmed by Zephyr implementation: nrfx_grtc_syscounter_cc_int_disable()
    grtc.intenclr(0).write(|w| w.set_compare1(true));

    // ===== STEP 9: WAIT FOR CC VALUE TO LATCH =====
    // CRITICAL: After writing the compare value, we must wait for it to be latched
    // into the hardware comparison logic. This is documented in Zephyr as
    // MAX_CC_LATCH_WAIT_TIME_US (77 microseconds).
    //
    // Without this wait, the compare value may not be properly set before entering
    // System OFF, causing the device to never wake up.
    //
    // The delay is in CPU cycles: 77us * 128 MHz = ~9856 cycles
    cortex_m::asm::delay(CC_LATCH_WAIT_US * CPU_FREQ_MHZ);
}

/// Enter System OFF mode
///
/// System OFF is the deepest sleep mode on nRF54L15:
/// - All peripherals stopped except GRTC (if configured) and GPIO SENSE
/// - RAM not retained (device resets on wake)
/// - Minimal power consumption (~0.5 uA with GRTC running)
/// - Wake sources: GRTC compare, GPIO SENSE, NFC field detect, LPCOMP
///
/// The device will perform a full reset on wake, so execution starts from main().
fn system_off(led: &mut Output) -> ! {
    let regulators = &pac::REGULATORS_S;

    // ===== DISABLE EMBASSY TIME DRIVER (RTC30) =====
    // RTC30 is used by embassy-time for async delays. It must be stopped and
    // all interrupts disabled to prevent it from keeping the system awake.
    let rtc30 = &pac::RTC30_S;
    rtc30.tasks_stop().write_value(1);
    rtc30.intenclr().write(|w| {
        w.set_tick(true);
        w.set_ovrflw(true);
        w.set_compare(0, true);
        w.set_compare(1, true);
        w.set_compare(2, true);
        w.set_compare(3, true);
    });

    // Clear all RTC30 events
    rtc30.events_tick().write_value(0);
    rtc30.events_ovrflw().write_value(0);
    for i in 0..4 {
        rtc30.events_compare(i).write_value(0);
    }

    // ===== DISABLE GPIOTE (GPIO TASKS AND EVENTS) =====
    // GPIOTE is used by embassy-nrf for async GPIO. Clear all channels.
    let gpiote = &pac::GPIOTE30_S;
    for i in 0..8 {
        gpiote.tasks_clr(i).write_value(1);
    }

    // ===== DISABLE ALL GPIO SENSE (PIN CHANGE WAKE) =====
    // GPIO SENSE allows pins to wake from System OFF. We disable all pins to
    // ensure ONLY GRTC can wake the device (for this test).
    // In a real application, you might configure specific pins for wake.
    let p0 = &pac::P0_S;
    let p1 = &pac::P1_S;
    let p2 = &pac::P2_S;
    for i in 0..32 {
        p0.pin_cnf(i).modify(|w| w.set_sense(pac::gpio::vals::Sense::DISABLED));
        p1.pin_cnf(i).modify(|w| w.set_sense(pac::gpio::vals::Sense::DISABLED));
        p2.pin_cnf(i).modify(|w| w.set_sense(pac::gpio::vals::Sense::DISABLED));
    }

    // ===== MEMORY BARRIERS =====
    // Ensure all peripheral register writes complete before entering System OFF
    cortex_m::asm::dsb(); // Data Synchronization Barrier
    cortex_m::asm::isb(); // Instruction Synchronization Barrier

    // ===== ENTER SYSTEM OFF =====
    // Writing SYSTEMOFF.SYSTEMOFF=1 triggers immediate System OFF entry.
    // Execution stops here. On wake (via GRTC), the device resets and boots from main().
    regulators.systemoff().write(|w| w.set_systemoff(true));

    // ===== SHOULD NEVER REACH HERE =====
    // If we reach this code, System OFF failed. Blink LED rapidly to indicate error.
    loop {
        led.set_high();
        cortex_m::asm::delay(1_000_000);
        led.set_low();
        cortex_m::asm::delay(1_000_000);
    }
}

#[embassy_executor::main]
async fn main(_spawner: Spawner) {
    // ===== INITIALIZE EMBASSY WITH LFXO =====
    // CRITICAL: External 32.768 kHz crystal (LFXO) is REQUIRED for GRTC System OFF wakeup.
    // The internal RC oscillator (LFRC) stops in System OFF, so GRTC would have no clock.
    // This is documented in nRF54L15 specification: "LFXO is the only clock source
    // running in the System OFF mode, and it is the recommended SoC configuration."
    let mut config = embassy_nrf::config::Config::default();
    config.lfclk_source = embassy_nrf::config::LfclkSource::ExternalXtal;
    let p = embassy_nrf::init(config);

    let mut led = Output::new(p.P2_09, Level::Low, OutputDrive::Standard);

    // ===== CHECK RESET REASON =====
    // The RESETREAS register indicates why the device reset.
    // Bit 18 (OFF) = wakeup from System OFF by designated wake source (GRTC in our case)
    // Bit 0 (RESETPIN) = external reset pin
    // Bit 16 (GPIO) = GPIO SENSE wakeup
    let reset_reason = pac::RESET_S.resetreas().read();

    // ===== INDICATE RESET REASON WITH LED =====
    if reset_reason.0 & (1 << 18) != 0 {
        // SUCCESS! Woke from System OFF via GRTC wakeup
        // Blink 5 times fast to celebrate
        for _ in 0..5 {
            led.set_high();
            Timer::after_millis(50).await;
            led.set_low();
            Timer::after_millis(50).await;
        }
    } else {
        // Normal power-on or reset - blink 3 times
        for _ in 0..3 {
            led.set_high();
            Timer::after_millis(100).await;
            led.set_low();
            Timer::after_millis(100).await;
        }
    }

    // Clear reset reason for next boot
    pac::RESET_S.resetreas().write_value(pac::reset::regs::Resetreas(0xFFFFFFFF));

    // Wait a moment before starting test
    Timer::after_millis(50).await;

    // ===== CONFIGURE GRTC FOR SYSTEM OFF WAKEUP =====
    // Initialize GRTC with sleep configuration, auto mode, and SYSCOUNTER active request
    start_grtc();

    // Set wakeup time to 5 seconds from now
    // GRTC runs at 1 MHz, so 5 seconds = 5,000,000 ticks
    configure_grtc_wakeup(5 * GRTC_CLOCK_FREQ);

    // ===== VISUAL INDICATION BEFORE SLEEP =====
    // Blink LED once slowly to show we're about to enter System OFF
    led.set_high();
    Timer::after_millis(500).await;
    led.set_low();
    Timer::after_millis(100).await;

    // ===== ENTER SYSTEM OFF =====
    // Device should wake after 5 seconds and reboot, showing 5 fast blinks
    system_off(&mut led);
}
