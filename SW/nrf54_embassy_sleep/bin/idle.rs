#![no_std]
#![no_main]

// use defmt::info;
use embassy_executor::Spawner;
use embassy_nrf::gpio::{Level, Output, OutputDrive};
use embassy_time::Timer;
use panic_reset as _;

const IDLE_SEC: u64 = 30;

#[embassy_executor::main]
async fn main(_spawner: Spawner) {
    let p = embassy_nrf::init(Default::default());

    // info!("Starting idle power usage example");

    let mut i = 0;
    loop {
        // info!("Iteration: {}, idling {} seconds", i, IDLE_SEC);
        Timer::after_secs(IDLE_SEC).await;

        i += 1;
    }
}
