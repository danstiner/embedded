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
use embassy_time::Timer;

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
use rs_matter_embassy::rand::nrf::{nrf_init_rand, nrf_rand};
use rs_matter_embassy::stack::persist::DummyKvBlobStore;
use rs_matter_embassy::wireless::nrf::{
    NrfThreadClockInterruptHandler, NrfThreadDriver, NrfThreadHighPrioInterruptHandler,
    NrfThreadLowPrioInterruptHandler, NrfThreadRadioResources, NrfThreadRadioRunner,
};
use rs_matter_embassy::wireless::{EmbassyThread, EmbassyThreadMatterStack};

use defmt_rtt as _;
use panic_rtt_target as _;
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

macro_rules! mk_static {
    ($t:ty) => {{
        static STATIC_CELL: static_cell::StaticCell<$t> = static_cell::StaticCell::new();
        STATIC_CELL.uninit()
    }};
    ($t:ty,$val:expr) => {{
        mk_static!($t).write($val)
    }};
}

bind_interrupts!(struct Irqs {
    SWI00 => NrfThreadLowPrioInterruptHandler;
    CLOCK_POWER => NrfThreadClockInterruptHandler;
    RADIO_0 => NrfThreadHighPrioInterruptHandler;
    TIMER10 => NrfThreadHighPrioInterruptHandler;
    TIMER20 => NrfThreadHighPrioInterruptHandler;
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
/// Increased from 28000 -> 40000 -> 50000 (was using 21132/28000 = 75%)
const BUMP_SIZE: usize = 50000;

#[global_allocator]
static HEAP: LlffHeap = LlffHeap::empty();

#[embassy_executor::main]
async fn main(_s: Spawner) {
    // CRITICAL: First log to see if we even get to main()
    // This uses panic_rtt_target which should work even if defmt-rtt fails
    rtt_target::rprintln!("=== EARLY: Entered main() ===");

    info!("Starting...");

    // Necessary `nrf-hal` initialization boilerplate
    let mut config = embassy_nrf::config::Config::default();
    // Use Internal oscillator for now
    config.hfclk_source = embassy_nrf::config::HfclkSource::ExternalXtal;

    debug!("Initializing embassy-nrf...");
    let p = embassy_nrf::init(config);
    #[cfg(debug_assertions)]
    Timer::after_millis(100).await;

    // `rs-matter` uses the `x509` crate which (still) needs a few kilos of heap space
    {
        const HEAP_SIZE: usize = 8192;

        static mut HEAP_MEM: [MaybeUninit<u8>; HEAP_SIZE] = [MaybeUninit::uninit(); HEAP_SIZE];
        unsafe { HEAP.init(addr_of_mut!(HEAP_MEM) as usize, HEAP_SIZE) }
    }
    debug!("Initializing heap...");
    #[cfg(debug_assertions)]
    Timer::after_millis(100).await;

    // For nRF54L, use a fixed discriminator for now
    // TODO: Implement proper CRACEN RNG support for nRF54L
    let discriminator = 0x560u16;

    // TODO: Get proper IEEE EUI-64 from device
    let ieee_eui64 = [0x02, 0x05, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01];

    // To erase generics, `Matter` takes a rand `fn` rather than a trait or a closure,
    // so we need to initialize the global `rand` fn once
    // For nRF54L, this uses a placeholder PRNG for now
    debug!("Initializing RNG...");
    nrf_init_rand(0x12345678);

    // Allocate the Matter stack.
    // For MCUs, it is best to allocate it statically, so as to avoid program stack blowups (its memory footprint is ~ 35 to 50KB).
    // It is also (currently) a mandatory requirement when the wireless stack variation is used.
    debug!("Initializing Matter stack...");
    let stack = mk_static!(EmbassyThreadMatterStack<BUMP_SIZE, ()>).init_with(
        EmbassyThreadMatterStack::init(
            &TEST_BASIC_INFO,
            BasicCommData {
                password: TEST_DEV_COMM.password,
                discriminator,
            },
            &TEST_DEV_ATT,
            epoch,
            nrf_rand,
        ),
    );

    debug!("Initializing Thread driver...");
    #[cfg(debug_assertions)]
    Timer::after_millis(100).await;
    let (thread_driver, thread_radio_runner) = NrfThreadDriver::new(
        mk_static!(NrfThreadRadioResources, NrfThreadRadioResources::new()),
        p.RADIO,
        p.GRTC,
        p.TIMER10,
        p.TIMER20,
        p.TEMP,
        p.PPI00_CH1,
        p.PPI00_CH3,
        p.PPI10_CH0,
        p.PPI10_CH1,
        p.PPI10_CH2,
        p.PPI10_CH3,
        p.PPI10_CH4,
        p.PPI10_CH5,
        p.PPI10_CH6,
        p.PPI10_CH7,
        p.PPI10_CH8,
        p.PPI10_CH9,
        p.PPI10_CH10,
        p.PPI10_CH11,
        p.PPI20_CH1,
        p.PPIB00_CH1,
        p.PPIB00_CH2,
        p.PPIB00_CH3,
        p.PPIB10_CH1,
        p.PPIB10_CH2,
        p.PPIB10_CH3,
        p.PPIB11_CH0,
        p.PPIB21_CH0,
        stack.matter().rand(),
        Irqs,
    );

    // High-priority executor: SWI01, priority level 6
    debug!("Setting SWI01 priority to P6...");
    interrupt::SWI01.set_priority(Priority::P6);

    // The NRF radio needs to run in a high priority executor
    // because it is lacking hardware MAC-filtering and ACK caps,
    // hence these are emulated in software, so low latency is crucial
    debug!("Starting RADIO_EXECUTOR...");
    let spawner = RADIO_EXECUTOR.start(interrupt::SWI01);
    debug!("Spawning radio task...");
    spawner.spawn(unwrap!(run_radio(thread_radio_runner)));
    debug!("Radio executor running");

    // Our "light" on-off cluster.
    // It will toggle the light state every 5 seconds
    debug!("Creating on-off cluster...");
    let on_off = on_off::OnOffHandler::new_standalone(
        Dataver::new_rand(stack.matter().rand()),
        LIGHT_ENDPOINT_ID,
        TestOnOffDeviceLogic::new(true),
    );

    // Chain our endpoint clusters
    debug!("Creating handler chain...");
    let handler = EmptyHandler
        // Our on-off cluster, on Endpoint 1
        .chain(
            EpClMatcher::new(
                Some(LIGHT_ENDPOINT_ID),
                Some(TestOnOffDeviceLogic::CLUSTER.id),
            ),
            on_off::HandlerAsyncAdaptor(&on_off),
        )
        // Each Endpoint needs a Descriptor cluster too
        // Just use the one that `rs-matter` provides out of the box
        .chain(
            EpClMatcher::new(Some(LIGHT_ENDPOINT_ID), Some(desc::DescHandler::CLUSTER.id)),
            Async(desc::DescHandler::new(Dataver::new_rand(stack.matter().rand())).adapt()),
        );

    debug!("Creating persist...");
    #[cfg(debug_assertions)]
    Timer::after_millis(100).await;
    let persist = stack
        .create_persist_with_comm_window(DummyKvBlobStore)
        .await
        .unwrap();

    // Run the Matter stack with our handler
    // Using `pin!` is completely optional, but reduces the size of the final future
    //
    // This step can be repeated in that the stack can be stopped and started multiple times, as needed.
    debug!("Running Matter stack...");
    #[cfg(debug_assertions)]
    Timer::after_millis(100).await;
    let matter = pin!(stack.run(
        // The Matter stack needs to instantiate `openthread`
        EmbassyThread::new(thread_driver, ieee_eui64, persist.store(), stack),
        // The Matter stack needs a persister to store its state
        &persist,
        // Our `AsyncHandler` + `AsyncMetadata` impl
        (NODE, handler),
        // No user future to run
        (),
    ));

    // Run Matter
    unwrap!(matter.await);
}

/// Basic info about our device
/// Both the matter stack as well as our mDNS-to-SRP bridge need this, hence extracted out
const TEST_BASIC_INFO: BasicInfoConfig = BasicInfoConfig {
    sai: Some(500),
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

#[embassy_executor::task]
async fn run_radio(mut runner: NrfThreadRadioRunner<'static, 'static>) -> ! {
    debug!("Running radio task...");
    runner.run().await
}
