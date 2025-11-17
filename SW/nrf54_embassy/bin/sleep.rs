#![no_std]
#![no_main]

use defmt::{info, debug, error};
use embassy_executor::Spawner;
use embassy_nrf::gpio::{Level, Output, OutputDrive};
use embassy_time::Timer;
use nrf_pac as pac;
use {defmt_rtt as _, panic_probe as _};

#[defmt::panic_handler]
fn panic() -> ! {
    cortex_m::asm::udf()
}

/// GRTC runs at 1 MHz, so 1,000,000 ticks = 1 second
const GRTC_CLOCK_FREQ: u64 = 1_000_000;

/// Configure GRTC to wake from System OFF after specified ticks
fn start_grtc() {
    let grtc = &pac::GRTC_S;

    // Enable SYSCOUNTER - this is required for the counter to actually run!
    grtc.mode().modify(|w| w.set_syscounteren(true));

    // Start GRTC
    grtc.tasks_start().write_value(1);
}

/// Configure GRTC to wake from System OFF after specified ticks
fn print_grtc() {
    let grtc = &pac::GRTC_S;

    // Get current counter value using capture
    grtc.tasks_capture(0).write_value(1);
    let now_low = grtc.cc(0).ccl().read();
    let now_high = grtc.cc(0).cch().read().cch(); // Use cch() method
    let now = (now_high as u64) << 32 | now_low as u64;

    debug!("GRTC now={}", now);
}

/// Configure GRTC to wake from System OFF after specified ticks
fn configure_grtc_wakeup(ticks: u64) {
    let grtc = &pac::GRTC_S;

    // Get current counter value using capture
    grtc.tasks_capture(0).write_value(1);
    let now_low = grtc.cc(0).ccl().read();
    let now_high = grtc.cc(0).cch().read().cch(); // Use cch() method
    let now = (now_high as u64) << 32 | now_low as u64;

    // Set compare value for wake (using CC[1])
    let wake_time = now.wrapping_add(ticks);
    let wake_low = wake_time as u32;
    let wake_high = (wake_time >> 32) as u32;

    grtc.cc(1).ccl().write_value(wake_low);
    grtc.cc(1)
        .cch()
        .write_value(pac::grtc::regs::Cch(wake_high));

    // Enable CC[1]
    grtc.cc(1).ccen().modify(|w| w.set_active(true));

    // Enable interrupt for CC[1] to wake from System OFF
    // intenset(0) controls interrupts for CC[0-15]
    grtc.intenset(0).modify(|w| w.set_compare1(true));

    debug!(
        "GRTC wakeup: now={}, wake={} (+{} ticks = {} sec)",
        now,
        wake_time,
        ticks,
        ticks / GRTC_CLOCK_FREQ
    );
}

/// Enter System OFF mode - device will reset on wake!
fn system_off() -> ! {
    let regulators = &pac::REGULATORS_S;

    // Try different ways to write systemoff
    info!("Attempting systemoff with write()...");
    regulators.systemoff().write(|w| w.set_systemoff(true));

    cortex_m::asm::delay(100_000);
    info!("Still alive after write(), trying write_value()...");

    regulators.systemoff().write_value(pac::regulators::regs::Systemoff(1));

    cortex_m::asm::delay(1_000_000);

    // Will never reach here - device powers off
    loop {
        error!("Will never reach here - device powers off");
        print_grtc();
        cortex_m::asm::wfi();
    }
}

#[embassy_executor::main]
async fn main(_spawner: Spawner) {
    // Configure to use external 32.768 kHz crystal (LFXO)
    // This is required for GRTC to wake from System OFF
    let mut config = embassy_nrf::config::Config::default();
    config.lfclk_source = embassy_nrf::config::LfclkSource::ExternalXtal;

    let p = embassy_nrf::init(config);

    debug!("=== Deep Sleep with GRTC Wake ===");

    // LED for status indication
    let mut led = Output::new(p.P2_09, Level::Low, OutputDrive::Standard);

    // Flash LED to show we're alive
    led.set_high();
    Timer::after_millis(50).await;
    led.set_low();

    debug!("Testing GRTC access...");

    // Test if we can access GRTC
    {
        let grtc = &pac::GRTC_S;
        debug!("GRTC pointer: 0x{:x}", grtc.as_ptr() as usize);
    }

    // Try to start GRTC
    debug!("Starting GRTC...");
    start_grtc();
    print_grtc();

    // Configure GRTC to wake after 5 seconds (GRTC runs at 1 MHz)
    let wake_seconds = 5;
    info!("Configuring wake in {} seconds...", wake_seconds);
    configure_grtc_wakeup(wake_seconds * GRTC_CLOCK_FREQ);

    // Enter System OFF - device resets after GRTC timeout
    debug!("Entering System OFF mode...");
    print_grtc();

    // Short delay to see the message
    Timer::after_millis(1).await;

    system_off();
}
