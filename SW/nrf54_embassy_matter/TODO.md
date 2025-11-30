# nRF54L15 Matter Device - Status

## Working
- BLE commissioning (PASE)
- Thread network joining
- Flash persistence (RRAMC)
- Device responds to Matter commands

## Active Issues

### Matter Setup Does Not Complete
Device visible in mDNS and pingable (inconsistent) but commissioning fails to complete.

**Root causes found via OpenThread example analysis** (examples/nrf/src/bin/srp.rs):

1. **Wrong wait method**: Using `srp_wait_changed()` instead of `wait_changed()` for SRP removal
   - OpenThread example uses general `wait_changed()` which triggers on any OT state change
   - We use `srp_wait_changed()` which only triggers on SRP-specific events
   - SRP waker may not trigger during network init when operations can't complete

2. **Wrong timing**: mdns.run() starts too late (rs-matter-stack/src/lib.rs:614)
   - Only runs when `cur_state.operational` is true (network fully joined)
   - OpenThread example does srp_remove_all() immediately after `enable_thread()`, during join
   - Potential deadlock: SRP needs mDNS server discovery, but mDNS only starts after network operational

3. **SRP registration not verified**: No wait for services to reach `SrpState::Registered` before controller connection

4. **IPv4 mDNS disabled**: Changed to `None` in `rs-matter-stack/src/mdns.rs:148`

**Fixes**:
- Change `srp_wait_changed()` to `wait_changed()` in rs-matter-embassy/src/ot.rs:457
- Consider moving srp_remove_all() earlier in initialization (before network fully operational)
- Add 10s timeout polling `srp_services()` until all reach `Registered` state
- Revert IPv4 mDNS to `Some(ipv4)`

### HardFault on First Boot After Erase (ACTIVE)
HardFault occurs only on first boot after full flash erase, works fine on subsequent boots without erase.

**Symptoms:**
- Fault at line 234 "Creating on-off cluster..." during `OnOffHandler::new_standalone()`
- PC: 0x2003fe14 (RAM address near top of 256KB, not valid code)
- CFSR: 0x00020000 (INVPC - Invalid PC loaded)
- LR: 0x000185d7 (OnOffHandler::validate in rs-matter/src/dm/clusters/on_off.rs:179)
- Changing BUMP_SIZE changes fault location (memory layout dependent)

**Root cause hypothesis:**
Uninitialized static data containing garbage function pointers/vtables. On first boot RAM is random, vtable pointer contains 0x2003fe14 instead of valid flash address. On subsequent boots RAM retains valid state from previous run.

**Related findings:**
- Moving heap init before embassy_nrf::init() fixed earlier fault (heap ordering issue)
- Reducing BUMP_SIZE from 50000→28000 changed fault from line 170 to 234 (got further)
- PC 0x2003fe14 = 261,652 bytes into RAM (near top, likely stack or high BSS)

**GDB Analysis Results:**
- Fault at `Dataver::new_rand(rand=0x2003fe14)` in rs-matter/src/dm/types/dataver.rs:31
- Called from line 236: `Dataver::new_rand(stack.matter().rand())`
- `nrf_rand` function pointer passed during stack init (line 180) but reads back as 0x2003fe14
- GDB `find` command located 0x2003fe14 in 15 RAM locations, mostly in STATIC_CELL areas
- Primary location: `light_thread::____embassy_main_task_inner_function::{{closure}}::STATIC_CELL`

**Root cause identified:**
Unsafe lifetime extension in `ProxyRadio::new()` (openthread/src/radio.rs:717-728) causes undefined behavior:

```rust
// ProxyRadio::new receives &'d mut ProxyRadioResources
// But transmutes buffers to &'static mut, extending lifetime
core::mem::transmute::<
    &mut [ProxyRadioRequest; 1],
    &'static mut [ProxyRadioRequest; 1],  // UB: 'd != 'static
>(request_buf)
```

Even though resources ARE 'static (via mk_static!), compiler doesn't know that at call site.
This allows compiler to make invalid optimizations that corrupt memory.

**Evidence:**
1. Adding `Dataver::new_rand(stack.matter().rand())` BEFORE mk_static! changes behavior
   - Changes stack layout / register allocation
   - Prevents corruption or moves it elsewhere
2. BSS zeroing in pre_init didn't fix it (not a BSS initialization issue)
3. Only fails on first boot (uninitialized stack/registers contain random data)
4. Subsequent boots work (memory retains "good" values from previous run)

**Attempted fixes:**
1. BSS zeroing in pre_init - no effect
2. Heap initialization ordering - fixed earlier fault but not this one
3. Changing BUMP_SIZE - changes fault location (memory layout dependent)

**Potential solutions:**
1. Modify ProxyRadio::new() to avoid unsafe transmute
2. Use proper 'static type at call site so 'd == 'static
3. Split ProxyRadioResources initialization to avoid lifetime issues

## Non-Critical Issues

### MPSL Shutdown Hangs
`mpsl_uninit()` never returns. Workaround: `mem::forget(mpsl)` in `rs-matter-embassy/src/wireless/thread/nrf.rs:458-463`. Need proper `sdc_disable()` -> `mpsl_uninit()` sequence.

### OtError(13) on mDNS Startup
Occasional error during SRP initialization, retries succeed.


4.2.6.2 Writing to RRAM
When writing is enabled in register CONFIG.WEN, and CONFIG.WRITEBUFSIZE is set to Unbuffered,
RRAM is written using any natural alignment (byte, half-word, 32-bit, or 64-bit).
RRAMC always writes full wordlines. When data is written to RRAM, the entire wordline is written and ECC
is updated, even if only a single bit is changed. This has an effect on the endurance of the RRAM, as each
write operation counts as a write to all bits in the wordline.
RRAMC is able to write both 0 and 1 to any bit in RRAM, even if that bit has been written before.
When writing with CONFIG.WRITEBUFSIZE set to Unbuffered, the written data (byte, half-word, 32-bit,
or 64-bit) is committed to RRAM immediately.