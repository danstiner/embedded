#![no_std]
#![no_main]

use embassy_executor::Spawner;
use embassy_nrf::gpio::{Level, Output, OutputDrive};
use embassy_time::Timer;
use nrf_pac as pac;
use panic_reset as _;

/// GRTC runs at 1 MHz, so 1,000,000 ticks = 1 second
const GRTC_CLOCK_FREQ: u64 = 1_000_000;

/// Start GRTC and configure it to stay active in System OFF
fn start_grtc() {
    let grtc = &pac::GRTC_S;
    grtc.mode().modify(|w| w.set_syscounteren(true));
    grtc.tasks_start().write_value(1);

    // Try to set KEEPRUNNING to keep GRTC active during System OFF
    // This register might not be in the PAC yet, so use raw pointer
    unsafe {
        let grtc_base = 0x500E_2000 as *mut u32;
        // KEEPRUNNING register is typically at offset 0x704
        let keeprunning = grtc_base.add(0x704 / 4);
        // Set bit 0 to keep GRTC running in System OFF
        core::ptr::write_volatile(keeprunning, 0x1);
    }
}

/// Configure GRTC to wake from System OFF after specified ticks
fn configure_grtc_wakeup(ticks: u64) {
    let grtc = &pac::GRTC_S;

    // Disable ALL channels first (critical!)
    for i in 0..12 {
        grtc.cc(i).ccen().write(|w| w.set_active(false));
    }

    // Disable all interrupts
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

    // Clear all events
    for i in 0..12 {
        grtc.events_compare(i).write_value(0);
    }

    // Get current counter value using capture
    grtc.tasks_capture(0).write_value(1);
    let now_low = grtc.cc(0).ccl().read();
    let now_high = grtc.cc(0).cch().read().cch();
    let now = (now_high as u64) << 32 | now_low as u64;

    // Set compare value for wake (using CC[1])
    let wake_time = now.wrapping_add(ticks);
    let wake_low = wake_time as u32;
    let wake_high = (wake_time >> 32) as u32;

    grtc.cc(1).ccl().write_value(wake_low);
    grtc.cc(1).cch().write_value(pac::grtc::regs::Cch(wake_high));

    // Enable ONLY CC[1]
    grtc.cc(1).ccen().write(|w| w.set_active(true));

    // Enable interrupt for CC[1] to wake from System OFF
    grtc.intenset(0).write(|w| w.set_compare1(true));
}

/// Enter System OFF mode
fn system_off() -> ! {
    let regulators = &pac::REGULATORS_S;

    // Disable RTC30 (embassy time driver)
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

    // Clear RTC events
    rtc30.events_tick().write_value(0);
    rtc30.events_ovrflw().write_value(0);
    for i in 0..4 {
        rtc30.events_compare(i).write_value(0);
    }

    // Disable GPIOTE
    let gpiote = &pac::GPIOTE30_S;
    for i in 0..8 {
        gpiote.tasks_clr(i).write_value(1);
    }

    // Disable all GPIO sense
    let p0 = &pac::P0_S;
    let p1 = &pac::P1_S;
    let p2 = &pac::P2_S;
    for i in 0..32 {
        p0.pin_cnf(i).modify(|w| w.set_sense(pac::gpio::vals::Sense::DISABLED));
        p1.pin_cnf(i).modify(|w| w.set_sense(pac::gpio::vals::Sense::DISABLED));
        p2.pin_cnf(i).modify(|w| w.set_sense(pac::gpio::vals::Sense::DISABLED));
    }

    // Ensure all operations complete
    cortex_m::asm::dsb();
    cortex_m::asm::isb();

    // Disable interrupts globally
    cortex_m::interrupt::disable();

    // Write to SYSTEMOFF register
    regulators.systemoff().write(|w| w.set_systemoff(true));

    // Should never reach here - blink LED rapidly if we do
    loop {
        cortex_m::asm::nop();
    }
}

#[embassy_executor::main]
async fn main(_spawner: Spawner) {
    let mut config = embassy_nrf::config::Config::default();
    // Use internal RC oscillator instead of external crystal
    // The LFXO might not stay on during System OFF
    config.lfclk_source = embassy_nrf::config::LfclkSource::ExternalXtal;
    let p = embassy_nrf::init(config);

    let mut led = Output::new(p.P2_09, Level::Low, OutputDrive::Standard);

    // Check reset reason
    let reset_reason = pac::RESET_S.resetreas().read();

    // Indicate reset reason with LED blinks
    // RESETREAS bit 0 = RESETPIN
    // RESETREAS bit 18 = OFF (wakeup from System OFF by GRTC)
    // RESETREAS bit 19 = LPCOMP (wakeup from System OFF by LPCOMP)
    if reset_reason.0 & (1 << 18) != 0 {
        // Woke from System OFF via GRTC - blink 5 times (SUCCESS!)
        for _ in 0..5 {
            led.set_high();
            Timer::after_millis(50).await;
            led.set_low();
            Timer::after_millis(50).await;
        }
    } else {
        // Normal startup - blink 3 times fast
        for _ in 0..3 {
            led.set_high();
            Timer::after_millis(100).await;
            led.set_low();
            Timer::after_millis(100).await;
        }
    }

    // Clear reset reason
    pac::RESET_S.resetreas().write_value(pac::reset::regs::Resetreas(0xFFFFFFFF));

    // Wait a moment
    Timer::after_millis(500).await;

    // Start GRTC
    start_grtc();

    // Configure wake in 5 seconds
    configure_grtc_wakeup(5 * GRTC_CLOCK_FREQ);

    // Blink LED once slowly to show we're about to sleep
    led.set_high();
    Timer::after_millis(500).await;
    led.set_low();

    // Small delay
    Timer::after_millis(100).await;

    // Enter System OFF
    system_off();
}
