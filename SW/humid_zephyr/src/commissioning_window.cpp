#include <zephyr/kernel.h>

#ifdef CONFIG_SHELL

#include <app/server/CommissioningWindowManager.h>
#include <app/server/Server.h>
#include <lib/core/CHIPError.h>
#include <lib/support/CodeUtils.h>
#include <platform/CHIPDeviceLayer.h>

#include <zephyr/logging/log.h>
#include <zephyr/shell/shell.h>

LOG_MODULE_REGISTER(commissioning_window, CONFIG_CHIP_APP_LOG_LEVEL);

using namespace chip;
using namespace chip::DeviceLayer;

namespace {

static int OpenCommissioningWindowCommand(const struct shell *shell, size_t argc, char **argv)
{
	// Default timeout: 180 seconds (3 minutes)
	uint16_t timeout_seconds = 180;

	if (argc > 1) {
		timeout_seconds = static_cast<uint16_t>(atoi(argv[1]));
		if (timeout_seconds == 0 || timeout_seconds > 900) {
			shell_error(shell, "Invalid timeout. Use 1-900 seconds.");
			return -EINVAL;
		}
	}

	PlatformMgr().LockChipStack();

	auto &commissionMgr = Server::GetInstance().GetCommissioningWindowManager();

	// Open a basic commissioning window (uses existing device credentials)
	// This is simpler than enhanced mode and works well for multi-admin
	CHIP_ERROR err = commissionMgr.OpenBasicCommissioningWindow(
		System::Clock::Seconds16(timeout_seconds),
		CommissioningWindowAdvertisement::kDnssdOnly);

	PlatformMgr().UnlockChipStack();

	if (err == CHIP_NO_ERROR) {
		shell_print(shell, "Commissioning window opened for %d seconds", timeout_seconds);
		shell_print(shell, "Use existing device credentials to pair:");
		shell_print(shell, "  Setup PIN: 20202021");
		shell_print(shell, "  Discriminator: 3840");
		shell_print(shell, "");
		shell_print(shell, "From chip-tool, run:");
		shell_print(shell, "  chip-tool pairing onnetwork-long <node-id> 20202021 3840");
	} else {
		shell_error(shell, "Failed to open commissioning window: %" CHIP_ERROR_FORMAT, err.Format());
		return -EIO;
	}

	return 0;
}

SHELL_STATIC_SUBCMD_SET_CREATE(
	commissioning_cmds,
	SHELL_CMD_ARG(open, NULL,
		"Open commissioning window for multi-admin\n"
		"Usage: commissioning open [timeout_seconds]\n"
		"  timeout_seconds: 1-900 (default: 180)",
		OpenCommissioningWindowCommand, 1, 1),
	SHELL_SUBCMD_SET_END
);

SHELL_CMD_REGISTER(commissioning, &commissioning_cmds, "Commissioning window commands", NULL);

} // namespace

#endif // CONFIG_SHELL
