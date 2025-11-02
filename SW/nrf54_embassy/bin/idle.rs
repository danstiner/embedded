#![no_std]
#![no_main]

use defmt::info;
use embassy_executor::Spawner;
use embassy_nrf::gpio::{Level, Output, OutputDrive};
use embassy_time::Timer;
use {defmt_rtt as _, panic_probe as _};

#[embassy_executor::main]
async fn main(_spawner: Spawner) {
    let p = embassy_nrf::init(Default::default());

    info!("Starting idle power usage example");

    loop {
        info!("on");
        Timer::after_millis(100).await;
        info!("off, idling 5s");
        Timer::after_millis(4900).await;
    }
}
