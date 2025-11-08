# nRF54L15 Embassy Matter Light

Matter Thread light example for nRF54L15 using embassy-nrf and rs-matter-embassy.

## Building

```bash
# Debug build (with verbose logging)
cargo build

# Release build
cargo build --release
```

## Flashing

```bash
# Flash and run with probe-rs
cargo run

# Or for release
DEFMT_LOG=error cargo run --release
```

## Hardware

- **Target**: nRF54L15 Development Kit
- **Radio**: IEEE 802.15.4 for Thread

## Architecture

- **Main executor**: Runs Matter stack and application logic
- **High-priority executor** (SWI01, Priority P6): Runs Thread radio driver for low-latency IEEE 802.15.4 MAC emulation