#![no_std]
#![no_main]

use defmt::{debug, error, info};
use embassy_executor::Spawner;
use embassy_nrf::gpio::{Level, Output, OutputDrive};
use embassy_time::{Duration, Timer};
use nrf_pac::{
    self as pac,
    grtc::vals::{Autoen, Busy},
};
use {defmt_rtt as _, panic_probe as _};

#[defmt::panic_handler]
fn panic() -> ! {
    cortex_m::asm::udf()
}

/// GRTC runs at 1 MHz, so 1,000,000 ticks = 1 second
const GRTC_CLOCK_FREQ: u64 = 1_000_000;

// Assumes 64Mhz clock
const CPU_CYCLE_PER_US: u32 = 64;

const NRF_GRTC: u64 = 1; // TODO

/// Configure GRTC to wake from System OFF after specified ticks
fn start_grtc() {
    let grtc = &pac::GRTC_S;

    // Enable SYSCOUNTER - this is required for the counter to actually run!
    grtc.mode().modify(|w| w.set_syscounteren(true));

    // Start GRTC
    grtc.tasks_start().write_value(1);
}

fn print_reset_reason() {
    match pac::RESET_S.resetreas().read() {
        r if r.lockup() => info!("Woke from reset for CPU lockup"),
        r if r.grtc() => info!("Woke from System OFF by GRTC"),
        r if r.sreq() => info!("Woke from soft reset"),
        r => todo!("Wake for {:?} not yet implemented", r),
    }
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

const WHATISTHIS: usize = 0;

/// Configure GRTC to wake from System OFF after specified ticks
fn configure_grtc_wakeup(sleep_duration: Duration) {
    let grtc = &pac::GRTC_S;
    // TODO accept duration to wake after
    // TODO check duration is at least minimum wakeup latency
    // TODO check grtc is initialized?

    debug!("Capturing current GRTC syscounter value...");
    let mut syscounter;
    loop {
        syscounter = grtc.syscounter(WHATISTHIS).syscounter().read();
        if syscounter.busy() == Busy::READY {
            break;
        }
    }
    let mode = grtc.mode().read();

    let now = syscounter.value();
    let enabled = mode.syscounteren();

    // Configure sleep
    if enabled {
        grtc.mode().write(|w| w.set_syscounteren(false));
    }
    const grtc_timeout: u16 = 5;
    grtc.mode().write(|w| w.set_autoen(Autoen::CPU_ACTIVE));
    grtc.timeout().write(|w| w.set_value(grtc_timeout));
    grtc.waketime().write(|w| w.set_value(4));
    if enabled {
        grtc.mode().write(|w| w.set_syscounteren(true));
    }

    // Channel alloc?
    let channel = 0;

    // Disable channel
    grtc.intenclr(WHATISTHIS).write(|w| w.set_compare0(true));
    debug!(
        "Disabled GRTC SYSCOUNTER compare interrupt for channel {}",
        channel
    );

    // Calculate wakeup
    let wake_at = now + sleep_duration.as_micros();
    // TODO assert wakeup < MAX syscounter value

    // Set wakeup
    // TODO clear any current compare event
    grtc.events_compare(channel).write_value(0);

    // TODO set counter cc value
    grtc.cc(channel).cc().write(|w| w.set_cc(wake_at));

    // TODO enable interrupt
    grtc.intenset(WHATISTHIS).write(|w| w.set_compare0(true));

    // Clear all GRTC channels except the systemoff_channel.
    // Channel mask: 0x00000f0f -> 0,1,2,3 and 8,9,10,11

    for i in 1..4 {
        grtc.cc(i).ccen().write(|w| w.set_active(false));
    }
    for i in 8..12 {
        grtc.cc(i).ccen().write(|w| w.set_active(false));
    }
    grtc.intenclr(WHATISTHIS).write(|w| {
        w.set_compare1(true);
        w.set_compare2(true);
        w.set_compare3(true);
        w.set_compare8(true);
        w.set_compare9(true);
        w.set_compare10(true);
        w.set_compare11(true);
    });
    for i in 1..4 {
        grtc.events_compare(i).write_value(0);
    }
    for i in 8..12 {
        grtc.events_compare(i).write_value(0);
    }

    // TODO Check compare event has not triggered yet

    // Wait for stored CC value to be latched
    // TODO nrfy_grtc_timeout_get(NRF_GRTC) * CONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC /
    //	LFCLK_FREQUENCY_HZ + MAX_CC_LATCH_WAIT_TIME_US (77);
    const CC_LATCH_WAIT_US: u32 = 77;
    let delay_us = grtc_timeout as u32 + CC_LATCH_WAIT_US;
    cortex_m::asm::delay(delay_us * CPU_CYCLE_PER_US);

    debug!(
        "GRTC wakeup: now={}, wake={}",
        now,
        wake_at
    );
}

/// Enter System OFF mode - device will reset on wake!
fn system_off(led: &mut Output) -> ! {
    let regulators = &pac::REGULATORS_S;

    info!("Preparing for System OFF...");

    // Disable RTC30 (embassy time driver) to prevent it from waking us
    let rtc30 = &pac::RTC30_S;
    rtc30.tasks_stop().write_value(1);

    // Disable all RTC interrupts
    rtc30.intenclr().write(|w| {
        w.set_tick(true);
        w.set_ovrflw(true);
        w.set_compare(0, true);
        w.set_compare(1, true);
        w.set_compare(2, true);
        w.set_compare(3, true);
    });

    // Clear all RTC events
    rtc30.events_tick().write_value(0);
    rtc30.events_ovrflw().write_value(0);
    for i in 0..4 {
        rtc30.events_compare(i).write_value(0);
    }

    // Disable GPIOTE (used by embassy-nrf)
    unsafe {
        let gpiote = &pac::GPIOTE30_S;

        // Disable all GPIOTE channels
        for i in 0..8 {
            gpiote.tasks_clr(i).write_value(1);
        }

        // Disable all GPIOTE interrupts (there are 2 interrupt registers)
        for i in 0..2 {
            gpiote.intenclr(i).write(|w| {
                for ch in 0..8 {
                    w.set_in_(ch, true);
                }
            });
        }
    }

    // Disable all GPIO sense (wake on pin change)
    unsafe {
        let p0 = &pac::P0_S;
        let p1 = &pac::P1_S;
        let p2 = &pac::P2_S;

        for i in 0..32 {
            // Set PIN_CNF.SENSE = 0 (disabled)
            p0.pin_cnf(i)
                .modify(|w| w.set_sense(pac::gpio::vals::Sense::DISABLED));
            p1.pin_cnf(i)
                .modify(|w| w.set_sense(pac::gpio::vals::Sense::DISABLED));
            p2.pin_cnf(i)
                .modify(|w| w.set_sense(pac::gpio::vals::Sense::DISABLED));
        }
    }

    // Double-check GRTC interrupt setup
    unsafe {
        let grtc = &pac::GRTC_S;

        // Clear any pending GRTC events (12 channels)
        // for i in 0..12 {
        //     grtc.events_compare(i).write_value(0);
        // }

        // Verify CC[0] is enabled and interrupt is set
        let cc1_enabled = grtc.cc(0).ccen().read().active();
        let int_enabled = grtc.inten(0).read().compare1();

        info!(
            "GRTC CC[0] enabled: {}, interrupt: {}",
            cc1_enabled, int_enabled
        );
    }

    info!("All peripherals disabled, entering System OFF...");

    // Small delay to ensure log message is transmitted
    cortex_m::asm::delay(100_000);

    // Disable RTT by clearing the control block
    // RTT control block is typically at the start of RAM
    unsafe {
        // The RTT control block signature "SEGGER RTT"
        // We'll just clear the first few bytes to invalidate it
        let rtt_control_block = 0x2000_0000 as *mut u32;
        core::ptr::write_volatile(rtt_control_block, 0);
        core::ptr::write_volatile(rtt_control_block.add(1), 0);
    }

    // Ensure all memory operations complete
    cortex_m::asm::dsb();
    cortex_m::asm::isb();

    // Disable interrupts globally
    cortex_m::interrupt::disable();

    // Write to SYSTEMOFF register
    regulators.systemoff().write(|w| w.set_systemoff(true));

    // Should never reach here - blink LED rapidly if we do
    error!("Still alive - System OFF failed!");
    loop {
        led.set_high();
        cortex_m::asm::delay(1_000_000);
        led.set_low();
        cortex_m::asm::delay(10_000_000);
    }
}

#[embassy_executor::main]
async fn main(_spawner: Spawner) {
    let mut config = embassy_nrf::config::Config::default();
    // External 32.768 kHz crystal (LFXO) is required for GRTC to wake from System OFF
    config.lfclk_source = embassy_nrf::config::LfclkSource::ExternalXtal;

    let p = embassy_nrf::init(config);

    debug!("=== Deep Sleep with GRTC Wake ===");

    print_reset_reason();

    // LED for status indication
    let mut led = Output::new(p.P2_09, Level::Low, OutputDrive::Standard);

    // Flash LED to show we're alive
    led.set_high();
    Timer::after_millis(100).await;
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

    // Configure GRTC to wake
    info!("Configuring wakeup...");
    configure_grtc_wakeup(Duration::from_secs(2));

    // Enter System OFF - device resets after GRTC timeout
    debug!("Entering System OFF mode...");
    print_grtc();

    // Short delay to see the message
    Timer::after_millis(1).await;

    system_off(&mut led);
}
