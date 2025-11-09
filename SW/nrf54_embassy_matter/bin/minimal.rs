#![no_std]
#![no_main]
#![recursion_limit = "256"]

use core::mem::MaybeUninit;
use core::ptr::addr_of_mut;

use embassy_executor::{InterruptExecutor, Spawner};
use embassy_nrf::interrupt;
use embassy_time::Timer;

use embedded_alloc::LlffHeap;

use defmt::{info, debug, unwrap};

use defmt_rtt as _;
use panic_probe as _;

use cortex_m as _;
use nrf_mpsl as _; // Force linking of critical-section implementation

#[global_allocator]
static HEAP: LlffHeap = LlffHeap::empty();

static RADIO_EXECUTOR: InterruptExecutor = InterruptExecutor::new();

#[interrupt]
unsafe fn SWI01() {
    unsafe { RADIO_EXECUTOR.on_interrupt() }
}

// Removed custom HardFault handler - panic_probe already provides one
// #[cortex_m_rt::exception]
// unsafe fn HardFault(ef: &cortex_m_rt::ExceptionFrame) -> ! {
//     defmt::error!("HardFault at PC={:#010x}", ef.pc());
//     defmt::error!("LR={:#010x}", ef.lr());
//     defmt::error!("PSR={:#010x}", ef.xpsr());

//     // Print stack pointer values if available
//     let sp: u32;
//     unsafe { core::arch::asm!("mrs {}, MSP", out(reg) sp) };
//     defmt::error!("MSP={:#010x}", sp);

//     panic!("HardFault");
// }

// macro_rules! mk_static {
//     ($t:ty) => {{
//         static STATIC_CELL: static_cell::StaticCell<$t> = static_cell::StaticCell::new();
//         STATIC_CELL.uninit()
//     }};
//     ($t:ty,$val:expr) => {{
//         mk_static!($t).write($val)
//     }};
// }

// bind_interrupts!(struct Irqs {
//     SWI00 => NrfThreadLowPrioInterruptHandler;
//     CLOCK_POWER => NrfThreadClockInterruptHandler;
//     RADIO_0 => NrfThreadHighPrioInterruptHandler;
//     TIMER10 => NrfThreadHighPrioInterruptHandler;
//     GRTC_3 => NrfThreadHighPrioInterruptHandler;
// });

// static RADIO_EXECUTOR: InterruptExecutor = InterruptExecutor::new();

// #[interrupt]
// unsafe fn SWI01() {
//     unsafe { RADIO_EXECUTOR.on_interrupt() }
// }

#[embassy_executor::task]
async fn test_radio_task() {
    info!("Test radio task started");
    loop {
        Timer::after_millis(1000).await;
        info!("Test radio task tick");
    }
}

#[embassy_executor::main]
async fn main(_spawner: Spawner) {
    info!("Starting...");

    debug!("Initializing heap...");
    {
        const HEAP_SIZE: usize = 8192;

        static mut HEAP_MEM: [MaybeUninit<u8>; HEAP_SIZE] = [MaybeUninit::uninit(); HEAP_SIZE];
        unsafe { HEAP.init(addr_of_mut!(HEAP_MEM) as usize, HEAP_SIZE) }
    }

    debug!("Initializing embassy-nrf...");
    let _p = embassy_nrf::init(Default::default());
    debug!("Initialized embassy-nrf");

    // Simple delay to test basic functionality
    Timer::after_millis(100).await;
    info!("Timer worked");

    debug!("Starting RADIO_EXECUTOR...");
    let spawner = RADIO_EXECUTOR.start(interrupt::SWI01);
    debug!("Spawning test task...");
    spawner.spawn(unwrap!(test_radio_task()));
    debug!("Test task spawned");

    Timer::after_millis(100).await;
    info!("Done");
}
