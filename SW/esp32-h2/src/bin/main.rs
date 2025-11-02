#![no_std]
#![no_main]
#![deny(
    clippy::mem_forget,
    reason = "mem::forget is generally not safe to do with esp_hal types, especially those \
    holding buffers for the duration of a data transfer."
)]

use bleps::ad_structure::{
    create_advertising_data, AdStructure, BR_EDR_NOT_SUPPORTED, LE_GENERAL_DISCOVERABLE,
};
use bleps::asynch::Ble;
use defmt::info;
use embassy_executor::Spawner;
use embassy_time::{Duration, Timer};
use esp_hal::clock::CpuClock;
use esp_hal::timer::systimer::SystemTimer;
use esp_hal::timer::timg::TimerGroup;
use esp_wifi::ble::controller::BleConnector;
use {esp_backtrace as _, esp_println as _};

extern crate alloc;

// This creates a default app-descriptor required by the esp-idf bootloader.
// For more information see: <https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/system/app_image_format.html#application-description>
esp_bootloader_esp_idf::esp_app_desc!();

#[esp_hal_embassy::main]
async fn main(_spawner: Spawner) {
    let config = esp_hal::Config::default().with_cpu_clock(CpuClock::max());
    let peripherals = esp_hal::init(config);

    esp_alloc::heap_allocator!(size: 64 * 1024);

    let timer0 = SystemTimer::new(peripherals.SYSTIMER);
    esp_hal_embassy::init(timer0.alarm0);

    info!("Embassy initialized!");

    let rng = esp_hal::rng::Rng::new(peripherals.RNG);
    let timer1 = TimerGroup::new(peripherals.TIMG0);
    let wifi_init =
        esp_wifi::init(timer1.timer0, rng).expect("Failed to initialize BLE controller");
    let connector = BleConnector::new(&wifi_init, peripherals.BT);

    let mut ble = Ble::new(connector, || embassy_time::Instant::now().as_millis());
    info!("BLE initialized!");

    // Initialize BLE
    ble.init().await.unwrap();
    ble.cmd_set_le_advertising_parameters().await.unwrap();

    let mut counter: u16 = 0;

    loop {
        info!("Counter: {}", counter);

        // Create advertising data with device name and counter value in manufacturer data
        let manufacturer_data = [
            0xFF, 0xFF, // Company ID (0xFFFF = test/debug)
            (counter & 0xFF) as u8,
            ((counter >> 8) & 0xFF) as u8,
        ];

        let adv_data = create_advertising_data(&[
            AdStructure::Flags(LE_GENERAL_DISCOVERABLE | BR_EDR_NOT_SUPPORTED),
            AdStructure::CompleteLocalName("ESP32-H2-Beacon"),
            AdStructure::ManufacturerSpecificData {
                company_identifier: 0xFFFF,
                payload: &manufacturer_data[2..],
            },
        ])
        .unwrap();

        info!("Starting advertising...");
        ble.cmd_set_le_advertising_data(adv_data)
            .await
            .unwrap();
        ble.cmd_set_le_advertise_enable(true).await.unwrap();

        // Advertise for 5 seconds
        Timer::after(Duration::from_secs(5)).await;

        ble.cmd_set_le_advertise_enable(false).await.unwrap();

        counter = counter.wrapping_add(1);

        // Wait before next advertisement
        Timer::after(Duration::from_secs(2)).await;
    }
}
