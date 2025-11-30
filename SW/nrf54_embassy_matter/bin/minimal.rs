//! An example utilizing the `EmbassyThreadMatterStack` struct.
//!
//! As the name suggests, this Matter stack assembly uses Thread as the main transport,
//! and thus BLE for commissioning, in non-concurrent commissioning mode
//! (the IEEE802.15.4 radio and BLE cannot not run at the same time with `embassy-nrf` and `nrf-sdc`).
//!
//! The example implements a fictitious Light device (an On-Off Matter cluster).
#![no_std]
#![no_main]
#![recursion_limit = "256"]

use core::mem::MaybeUninit;
use core::pin::pin;
use core::ptr::addr_of_mut;

use embassy_nrf::interrupt;
use embassy_nrf::interrupt::{InterruptExt, Priority};
use embassy_nrf::bind_interrupts;

use embassy_executor::{InterruptExecutor, Spawner};

use embedded_alloc::LlffHeap;

use defmt::{info, debug, unwrap};

use rs_matter_embassy::epoch::epoch;
use rs_matter_embassy::matter::dm::clusters::basic_info::BasicInfoConfig;
use rs_matter_embassy::matter::dm::clusters::desc::{self, ClusterHandler as _};
use rs_matter_embassy::matter::dm::clusters::on_off::test::TestOnOffDeviceLogic;
use rs_matter_embassy::matter::dm::clusters::on_off::{self, OnOffHooks};
use rs_matter_embassy::matter::dm::devices::test::{TEST_DEV_ATT, TEST_DEV_COMM, TEST_DEV_DET};
use rs_matter_embassy::matter::dm::devices::DEV_TYPE_ON_OFF_LIGHT;
use rs_matter_embassy::matter::dm::{Async, Dataver, EmptyHandler, Endpoint, EpClMatcher, Node};
use rs_matter_embassy::matter::utils::init::InitMaybeUninit;
use rs_matter_embassy::matter::{clusters, devices, BasicCommData};
use rs_matter_embassy::rand::nrf::{nrf54_init_rand, nrf54_rand};
use rs_matter_embassy::wireless::nrf::{
    NrfThreadClockInterruptHandler, NrfThreadDriver, NrfThreadHighPrioInterruptHandler,
    NrfThreadLowPrioInterruptHandler, NrfThreadRadioResources, NrfThreadRadioRunner,
};
use rs_matter_embassy::wireless::{EmbassyThread, EmbassyThreadMatterStack};

use defmt_rtt as _;
use panic_probe as _;
use static_cell::StaticCell;
use tinyrlibc as _;
use cortex_m as _;

#[cortex_m_rt::exception]
unsafe fn BusFault() {
    defmt::panic!("BusFault!");
}

#[cortex_m_rt::exception]
unsafe fn UsageFault() {
    defmt::error!("UsageFault!");
    let cfsr = unsafe { (*cortex_m::peripheral::SCB::PTR).cfsr.read() };
    defmt::error!("CFSR: {:#010x}", cfsr);
    defmt::panic!("UsageFault!");
}

#[cortex_m_rt::exception]
unsafe fn HardFault(ef: &cortex_m_rt::ExceptionFrame) -> ! {
    defmt::error!("HardFault!");
    defmt::error!("PC: {:#010x}", ef.pc());
    defmt::error!("LR: {:#010x}", ef.lr());

    let scb = cortex_m::peripheral::SCB::PTR;
    let cfsr = unsafe { (*scb).cfsr.read() };
    let hfsr = unsafe { (*scb).hfsr.read() };
    let mmfar = unsafe { (*scb).mmfar.read() };
    let bfar = unsafe { (*scb).bfar.read() };
    defmt::error!("CFSR: {:#010x}", cfsr);
    defmt::error!("HFSR: {:#010x}", hfsr);
    defmt::error!("MMFAR: {:#010x}", mmfar);
    defmt::error!("BFAR: {:#010x}", bfar);

    // Print stack pointer values if available
    let sp: u32;
    unsafe { core::arch::asm!("mrs {}, MSP", out(reg) sp) };
    defmt::error!("MSP={:#010x}", sp);

    panic!("HardFault");
}

bind_interrupts!(struct Irqs {
    SWI00 => NrfThreadLowPrioInterruptHandler;
    CLOCK_POWER => NrfThreadClockInterruptHandler;
    RADIO_0 => NrfThreadHighPrioInterruptHandler;
    TIMER10 => NrfThreadHighPrioInterruptHandler;
    GRTC_3 => NrfThreadHighPrioInterruptHandler;
});

#[interrupt]
unsafe fn SWI01() {
    unsafe { RADIO_EXECUTOR.on_interrupt() }
}

static RADIO_EXECUTOR: InterruptExecutor = InterruptExecutor::new();

/// The amount of memory for allocating all `rs-matter-stack` futures created during
/// the execution of the `run*` methods.
/// This does NOT include the rest of the Matter stack.
///
/// The futures of `rs-matter-stack` created during the execution of the `run*` methods
/// are allocated in a special way using a small bump allocator which results
/// in a much lower memory usage by those.
///
/// If - for your platform - this size is not enough, increase it until
/// the program runs without panics during the stack initialization.
const BUMP_SIZE: usize = 24000;
const HEAP_SIZE: usize = 16384;

static mut HEAP_MEM: [MaybeUninit<u8>; HEAP_SIZE] = [MaybeUninit::zeroed(); HEAP_SIZE];
static MATTER_STACK: StaticCell<EmbassyThreadMatterStack<BUMP_SIZE, ()>> = StaticCell::new();
static THREAD_RESOURCES: StaticCell<NrfThreadRadioResources> = StaticCell::new();

#[global_allocator]
static HEAP: LlffHeap = LlffHeap::empty();

#[embassy_executor::main]
async fn main(_s: Spawner) {

    info!("Starting...");

    // Initialize heap FIRST before any other initialization that might allocate
    debug!("Initializing heap...");
    {
        unsafe { HEAP.init(addr_of_mut!(HEAP_MEM) as usize, HEAP_SIZE) }
    }

    // Necessary `nrf-hal` initialization boilerplate
    let mut config = embassy_nrf::config::Config::default();
    // TODO #[cfg(feature = "nrf54l")]
    {
        config.clock_speed = embassy_nrf::config::ClockSpeed::CK128;
    }

    debug!("Initializing embassy-nrf...");
    let p = embassy_nrf::init(config);

    info!("CRACEN start");
    // For nRF54L, use a fixed discriminator for now
    // TODO: Implement proper CRACEN RNG support for nRF54L
    let discriminator = 0x570u16;

    // TODO: Get proper IEEE EUI-64 from device
    let ieee_eui64 = [0x02, 0x05, 0x02, 0x00, 0x00, 0x00, 0x00, 0x01];

    // To erase generics, `Matter` takes a rand `fn` rather than a trait or a closure,
    // so we need to initialize the global `rand` fn once
    // For nRF54L, this uses a placeholder PRNG for now
    debug!("Initializing RNG...");
    // nrf54_init_rand(0x12345678);

    // Allocate the Matter stack.
    // For MCUs, it is best to allocate it statically, so as to avoid program stack blowups (its memory footprint is ~ 35 to 50KB).
    // It is also (currently) a mandatory requirement when the wireless stack variation is used.
    // debug!("Initializing Matter stack...");
    // let stack = MATTER_STACK.uninit().init_with(
    //     EmbassyThreadMatterStack::init(
    //         &TEST_BASIC_INFO,
    //         BasicCommData {
    //             password: TEST_DEV_COMM.password,
    //             discriminator,
    //         },
    //         &TEST_DEV_ATT,
    //         epoch,
    //         nrf54_rand,
    //     )
    // );

    debug!("Creating settings store...");

    // Setup RRAM region for Matter settings persistence
    // NVS region: last 24KB of RRAM (see memory.x)
    const NVS_START: u32 = 0x00000000 + (1524 * 1024) - (24 * 1024);
    const NVS_END: u32 = 0x00000000 + (1524 * 1024);

    // use embassy_embedded_hal::adapter::BlockingAsync;
    // let rramc = embassy_nrf::rramc::Rramc::new(p.RRAMC);
    // let flash_async = BlockingAsync::new(rramc);
    // let flash_store = rs_matter_embassy::persist::EmbassyKvBlobStore::new(
    //     flash_async,
    //     NVS_START..NVS_END,
    // );

    // let persist = unwrap!(stack
    //     .create_persist_with_comm_window(flash_store)
    //     .await);
    // debug!("Persist created successfully");

    // // Run the Matter stack with our handler
    // // Using `pin!` is completely optional, but reduces the size of the final future
    // //
    // // This step can be repeated in that the stack can be stopped and started multiple times, as needed.
    // debug!("Running Matter stack...");
    // let matter = pin!(stack.run(
    //     // The Matter stack needs to instantiate `openthread`
    //     EmbassyThread::new(thread_driver, ieee_eui64, persist.store(), stack),
    //     // The Matter stack needs a persister to store its state
    //     &persist,
    //     // Our `AsyncHandler` + `AsyncMetadata` impl
    //     (NODE, handler),
    //     // No user future to run
    //     (),
    // ));

    // // Run Matter
    // unwrap!(matter.await);

    // Sleep in a loop so the executor doesn't exit
    loop {
        info!("Done, sleeping...");
        embassy_time::Timer::after(embassy_time::Duration::from_secs(3600)).await;
    }
}

#[embassy_executor::task]
async fn run_radio(mut runner: NrfThreadRadioRunner<'static, 'static>) -> ! {
    debug!("Running radio task...");
    runner.run().await
}

/// Basic info about our device
/// Both the matter stack as well as our mDNS-to-SRP bridge need this, hence extracted out
const TEST_BASIC_INFO: BasicInfoConfig = BasicInfoConfig {
    // Increase Session Active Interval to 5000ms to accommodate slower crypto operations
    // The default SPAKE2+ handshake can take several seconds on resource-constrained devices
    sai: Some(5000),
    ..TEST_DEV_DET
};

/// Endpoint 0 (the root endpoint) always runs
/// the hidden Matter system clusters, so we pick ID=1
const LIGHT_ENDPOINT_ID: u16 = 1;

/// The Matter Light device Node
const NODE: Node = Node {
    id: 0,
    endpoints: &[
        EmbassyThreadMatterStack::<0, ()>::root_endpoint(),
        Endpoint {
            id: LIGHT_ENDPOINT_ID,
            device_types: devices!(DEV_TYPE_ON_OFF_LIGHT),
            clusters: clusters!(desc::DescHandler::CLUSTER, TestOnOffDeviceLogic::CLUSTER),
        },
    ],
};
