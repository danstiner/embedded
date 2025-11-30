#![no_std]
#![no_main]

use embassy_executor::Spawner;
use embassy_nrf::gpio::{Input, Level, Output, OutputDrive, Pull};
use embassy_time::Timer;
use nrf_pac as pac;
use {defmt_rtt as _, panic_probe as _};

#[embassy_executor::main]
async fn main(_spawner: Spawner) {
    let mut config = embassy_nrf::config::Config::default();
    config.lfclk_source = embassy_nrf::config::LfclkSource::InternalRC;
    let p = embassy_nrf::init(config);

    let mut led = Output::new(p.P2_09, Level::Low, OutputDrive::Standard);

    // Check reset reason
    let reset_reason = pac::RESET_S.resetreas().read();

    // Check if we woke from GPIO (SENSE bit)
    if reset_reason.0 & (1 << 16) != 0 {
        // Woke from GPIO! Blink 5 times
        for _ in 0..5 {
            led.set_high();
            Timer::after_millis(50).await;
            led.set_low();
            Timer::after_millis(50).await;
        }
    } else {
        // Normal startup - blink 3 times
        for _ in 0..3 {
            led.set_high();
            Timer::after_millis(100).await;
            led.set_low();
            Timer::after_millis(100).await;
        }
    }

    // Clear reset reason
    pac::RESET_S.resetreas().write_value(pac::reset::regs::Resetreas(0xFFFFFFFF));

    Timer::after_millis(500).await;

    // Configure button0 as wake source (P1.13 on Nordic DK)
    let _button = Input::new(p.P1_13, Pull::Up);

    // Enable SENSE on the button pin for low level detection
    unsafe {
        pac::P1_S.pin_cnf(13).modify(|w| w.set_sense(pac::gpio::vals::Sense::LOW));
    }

    // Blink once slowly
    led.set_high();
    Timer::after_millis(500).await;
    led.set_low();
    Timer::after_millis(100).await;

    // Enter System OFF
    let regulators = &pac::REGULATORS_S;

    // Disable RTC30
    let rtc30 = &pac::RTC30_S;
    rtc30.tasks_stop().write_value(1);

    cortex_m::asm::dsb();
    cortex_m::asm::isb();

    regulators.systemoff().write(|w| w.set_systemoff(true));

    loop {
        cortex_m::asm::nop();
    }
}
