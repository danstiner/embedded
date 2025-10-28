#![no_std]
#![no_main]

use defmt::info;
use embassy_executor::Spawner;
use embassy_nrf::gpio::{Level, Output, OutputDrive};
use embassy_time::Timer;
use nrf_pac as pac;
use {defmt_rtt as _, panic_probe as _};

#[defmt::panic_handler]
fn panic() -> ! {
    cortex_m::asm::udf()
}

/// Configure GRTC to wake from System OFF after specified ticks
/// GRTC runs at 1 MHz, so 1,000,000 ticks = 1 second
fn configure_grtc_wakeup(ticks: u64) {
    let grtc = &pac::GRTC_NS;

    // Start GRTC
    grtc.tasks_start().write_value(1);

    // Get current counter value using capture
    grtc.tasks_capture(0).write_value(1);
    let now_low = grtc.cc(0).ccl().read();
    let now_high = grtc.cc(0).cch().read().cch();  // Use cch() method
    let now = (now_high as u64) << 32 | now_low as u64;

    // Set compare value for wake (using CC[1])
    let wake_time = now.wrapping_add(ticks);
    let wake_low = wake_time as u32;
    let wake_high = (wake_time >> 32) as u32;

    grtc.cc(1).ccl().write_value(wake_low);
    grtc.cc(1).cch().modify(|w| w.set_cch(wake_high));  // Use set_cch()

    // Enable CC[1]
    grtc.cc(1).ccen().modify(|w| w.set_active(true));  // Use set_active()

    // Enable interrupt for CC[1] to wake from System OFF
    // intenset(0) controls interrupts for CC[0-15]
    grtc.intenset(0).modify(|w| w.set_compare1(true));

    info!("GRTC wakeup: now={}, wake={} (+{} ticks = {} sec)",
          now, wake_time, ticks, ticks / 1_000_000);
}

/// Enter System OFF mode - device will reset on wake!
fn system_off() -> ! {
    info!("Entering System OFF mode...");

    // Flush defmt messages
    cortex_m::asm::delay(100_000);

    let regulators = &pac::REGULATORS_NS;
    regulators.systemoff().write(|w| w.set_systemoff(true));

    // Will never reach here - device powers off
    loop {
        cortex_m::asm::wfi();
    }
}

#[embassy_executor::main]
async fn main(_spawner: Spawner) {
    let p = embassy_nrf::init(Default::default());

    info!("=== Deep Sleep with GRTC Wake ===");

    // LED for status indication
    let mut led = Output::new(p.P2_09, Level::Low, OutputDrive::Standard);

    // Flash LED to show we're alive
    for _ in 0..5 {
        led.set_high();
        Timer::after_millis(100).await;
        led.set_low();
        Timer::after_millis(100).await;
    }

    info!("Testing GRTC access...");

    // Test if we can access GRTC
    let grtc = &pac::GRTC_NS;
    info!("GRTC pointer: {:x}", grtc.as_ptr() as usize);

    // Try to start GRTC
    info!("Starting GRTC...");
    grtc.tasks_start().write_value(1);

    info!("GRTC started successfully!");
    Timer::after_millis(1000).await;

    // Configure GRTC to wake after 5 seconds (GRTC runs at 1 MHz)
    let wake_seconds = 5;
    info!("Configuring wake in {} seconds...", wake_seconds);
    configure_grtc_wakeup(wake_seconds * 1_000_000);

    // Short delay to see the message
    Timer::after_millis(1000).await;

    // Enter System OFF - device resets after GRTC timeout
    system_off();
}
