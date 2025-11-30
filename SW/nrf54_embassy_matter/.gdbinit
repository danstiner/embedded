target extended-remote :1337
file target/thumbv8m.main-none-eabihf/release/light_thread
set print pretty on

# Step 1: Break before OnOffHandler creation (where it will crash)
break light_thread.rs:255

# Commands when hitting line 255 (before crash)
commands 1
  silent
  printf "\n=== About to create OnOffHandler ===\n"
  printf "Checking what the rand pointer contains NOW...\n"
  printf "If it's already bad (0x2003fe14), something corrupted it earlier.\n"
  printf "If it's still good, corruption happens during Dataver::new_rand.\n"
  # Try to examine stack memory - this might not work depending on type visibility
  printf "Searching for the BAD pointer value 0x2003fe14...\n"
  find /w 0x20000000, 0x20040000, 0x2003fe14
  printf "\nType 'continue' to proceed to crash, or 'next' to step through.\n"
end

# Step 2: Also catch the HardFault if it still happens
break HardFault

commands 2
  backtrace
  info registers
  printf "\nSearching for bad pointer 0x2003fe14...\n"
  find /w 0x20000000, 0x20040000, 0x2003fe14
end

echo \n=== Memory Corruption Debugger ===\n
echo 1. Will break after stack init at line 203\n
echo 2. Will show where the good function pointer is stored\n
echo 3. Set a watchpoint on that address to catch corruption\n
echo 4. Type 'continue' to start\n\n
