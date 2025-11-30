#define NRFX_GRTC_CONFIG_ALLOWED_CC_CHANNELS_MASK 0x00000f0f

/** @brief GRTC SYSCOUNTER sleep configuration structure. */
typedef struct
{
    uint32_t timeout;   /**< Delay in LFCLK cycles after the condition allowing SYSCOUNTER to go to sleep is met. */
    uint32_t waketime;  /**< Number of LFCLK cycles to wakeup the SYSCOUNTER before the wake-up event occured. */
    bool     auto_mode; /**< Enable automatic mode, which keeps the SYSCOUNTER active when any of the local CPUs is active. */
} nrfx_grtc_sleep_config_t;

/**
 * @brief GRTC sleep default configuration.
 *
 * This configuration sets up GRTC with the following options:
 * - sleep timeout: 5 LFCLK cycles
 * - wake time: 4 LFCLK cycles
 * - automatic mode: true
 */
#define NRFX_GRTC_SLEEP_DEFAULT_CONFIG \
{                                      \
    .timeout   = 5,                    \
    .waketime  = 4,                    \
    .auto_mode = true                  \


#if defined(CONFIG_POWEROFF) && defined(CONFIG_NRF_GRTC_START_SYSCOUNTER)
int z_nrf_grtc_wakeup_prepare(uint64_t wake_time_us)
{
	if (!nrfx_grtc_init_check()) {
		return -ENOTSUP;
	}

	nrfx_err_t err_code;
	static struct k_spinlock lock;
	static uint8_t systemoff_channel;
	uint64_t now = counter();
	nrfx_grtc_sleep_config_t sleep_cfg;
	/* Minimum time that ensures valid execution of system-off procedure. */
	uint32_t minimum_latency_us;
	uint32_t chan;
	int ret;

	nrfx_grtc_sleep_configuration_get(&sleep_cfg);
	minimum_latency_us = (sleep_cfg.waketime + sleep_cfg.timeout) *
		USEC_PER_SEC / LFCLK_FREQUENCY_HZ +
		CONFIG_NRF_GRTC_SYSCOUNTER_SLEEP_MINIMUM_LATENCY;
	sleep_cfg.auto_mode = false;
	nrfx_grtc_sleep_configure(&sleep_cfg);

	if (minimum_latency_us > wake_time_us) {
		return -EINVAL;
	}

	k_spinlock_key_t key = k_spin_lock(&lock);

	err_code = nrfx_grtc_channel_alloc(&systemoff_channel);
	if (err_code != NRFX_SUCCESS) {
		k_spin_unlock(&lock, key);
		return -ENOMEM;
	}
	(void)nrfx_grtc_syscounter_cc_int_disable(systemoff_channel);
	ret = compare_set(systemoff_channel,
			  now + wake_time_us * sys_clock_hw_cycles_per_sec() / USEC_PER_SEC, NULL,
			  NULL);
	if (ret < 0) {
		k_spin_unlock(&lock, key);
		return ret;
	}

	for (uint32_t grtc_chan_mask = NRFX_GRTC_CONFIG_ALLOWED_CC_CHANNELS_MASK;
	     grtc_chan_mask > 0; grtc_chan_mask &= ~BIT(chan)) {
		/* Clear all GRTC channels except the systemoff_channel. */
		chan = u32_count_trailing_zeros(grtc_chan_mask);
		if (chan != systemoff_channel) {
			nrfx_grtc_syscounter_cc_disable(chan);
		}
	}

	/* Make sure that wake_time_us was not triggered yet. */
	if (nrfx_grtc_syscounter_compare_event_check(systemoff_channel)) {
		k_spin_unlock(&lock, key);
		return -EINVAL;
	}

	/* This mechanism ensures that stored CC value is latched. */
	uint32_t wait_time =
		nrfy_grtc_timeout_get(NRF_GRTC) * CONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC /
		LFCLK_FREQUENCY_HZ + MAX_CC_LATCH_WAIT_TIME_US;
	k_busy_wait(wait_time);
	k_spin_unlock(&lock, key);
	return 0;
}
#endif /* CONFIG_POWEROFF */

uint64_t nrfx_grtc_syscounter_get(void)
{
    NRFX_ASSERT(m_cb.state == NRFX_DRV_STATE_INITIALIZED);
    uint64_t val;

#if !(NRFX_CHECK(ISA_ARM) && (__CORTEX_M == 33U))
    /* On ARM Cortex-M33 there is a double word read instruction so no need for locking. */
    NRFX_CRITICAL_SECTION_ENTER();
#endif
    val = nrfy_grtc_sys_counter_get(NRF_GRTC);
#if !(NRFX_CHECK(ISA_ARM) && (__CORTEX_M == 33U))
    NRFX_CRITICAL_SECTION_EXIT();
#endif

    return val;
}

NRFY_STATIC_INLINE uint64_t nrfy_grtc_sys_counter_get(NRF_GRTC_Type const * p_reg)
{
#if NRFX_CHECK(ISA_ARM) && (__CORTEX_M == 33U)
    uint64_t counter;

    do {
        counter = nrf_grtc_sys_counter_get(p_reg);
    } while (counter & NRFY_GRTC_SYSCOUNTER_RETRY_MASK);
#if NRFX_CHECK(NRFY_GRTC_HAS_SYSCOUNTER_LOADED)
    return counter & NRFY_GRTC_SYSCOUNTER_MASK;
#else
    return counter;
#endif
#else
    uint32_t counter_l, counter_h;

    do {
        counter_l = nrf_grtc_sys_counter_low_get(p_reg);
        nrf_barrier_r();
        counter_h = nrf_grtc_sys_counter_high_get(p_reg);
        nrf_barrier_r();
    } while (counter_h & NRFY_GRTC_SYSCOUNTER_RETRY_MASK);
#if NRFX_CHECK(NRFY_GRTC_HAS_SYSCOUNTER_LOADED)
    return (uint64_t)counter_l | ((uint64_t)(counter_h & NRF_GRTC_SYSCOUNTERH_VALUE_MASK) << 32);
#else
    return (uint64_t)counter_l | ((uint64_t)counter_h << 32);
#endif
#endif // NRFX_CHECK(ISA_ARM) && (__CORTEX_M == 33U)
}

NRF_STATIC_INLINE uint64_t nrf_grtc_sys_counter_get(NRF_GRTC_Type const * p_reg)
{
#if NRF_GRTC_HAS_SYSCOUNTER_ARRAY
    uintptr_t ptr = (uintptr_t)&p_reg->GRTC_SYSCOUNTER.SYSCOUNTERL;
#else
    uintptr_t ptr = (uintptr_t)&p_reg->SYSCOUNTERL;
#endif // NRF_GRTC_HAS_SYSCOUNTER_ARRAY
    return *(const uint64_t volatile *)ptr;
}

static int compare_set_nolocks(int32_t chan, uint64_t target_time,
			       z_nrf_grtc_timer_compare_handler_t handler, void *user_data)
{
	nrfx_err_t result;

	__ASSERT_NO_MSG(target_time < COUNTER_SPAN);
	nrfx_grtc_channel_t user_channel_data = {
		.handler = handler,
		.p_context = user_data,
		.channel = chan,
	};
	result = nrfx_grtc_syscounter_cc_absolute_set(&user_channel_data, target_time, true);
	if (result != NRFX_SUCCESS) {
		return -EPERM;
	}
	return 0;
}

nt nrfx_grtc_syscounter_cc_absolute_set(nrfx_grtc_channel_t * p_chan_data,
                                         uint64_t              val,
                                         bool                  enable_irq)
{
    NRFX_ASSERT(m_cb.state != NRFX_DRV_STATE_UNINITIALIZED);
    NRFX_ASSERT(p_chan_data);
    int err_code = syscounter_check(p_chan_data->channel);
    if (err_code != 0)
    {
        NRFX_LOG_WARNING("Function: %s, error code: %s.",
                         __func__,
                         NRFX_LOG_ERROR_STRING_GET(err_code));
        return err_code;
    }

    cc_channel_prepare(p_chan_data);
    NRFX_CRITICAL_SECTION_ENTER();
    nrfy_grtc_sys_counter_compare_event_clear(NRF_GRTC, p_chan_data->channel);
    nrfy_grtc_sys_counter_cc_set(NRF_GRTC, p_chan_data->channel, val);
    NRFX_CRITICAL_SECTION_EXIT();

    if (enable_irq)
    {
        NRFX_ATOMIC_FETCH_OR(&m_cb.read_cc_mask, NRFX_BIT(p_chan_data->channel));
        nrfy_grtc_int_enable(NRF_GRTC, GRTC_CHANNEL_TO_BITMASK(p_chan_data->channel));
    }

    NRFX_LOG_INFO("GRTC SYSCOUNTER absolute compare for channel %u set to %u.",
                  (uint32_t)p_chan_data->channel,
                  (uint32_t)nrfy_grtc_sys_counter_cc_get(NRF_GRTC, p_chan_data->channel));
    return err_code;
}

NRFY_STATIC_INLINE void nrfy_grtc_sys_counter_compare_event_clear(NRF_GRTC_Type * p_reg,
                                                                  uint8_t         cc_channel)
{
    nrf_grtc_event_clear(p_reg, nrf_grtc_sys_counter_compare_event_get(cc_channel));
    nrf_barrier_w();
}

NRF_STATIC_INLINE void nrf_grtc_event_clear(NRF_GRTC_Type * p_reg, nrf_grtc_event_t event)
{
#if NRF_GRTC_HAS_SYSCOUNTERVALID
    NRFX_ASSERT(event != NRF_GRTC_EVENT_SYSCOUNTERVALID);
#endif

    *((volatile uint32_t *)((uint8_t *)p_reg + (uint32_t)event)) = 0x0UL;
}

void nrfx_grtc_sleep_configure(nrfx_grtc_sleep_config_t const * p_sleep_cfg)
{
    NRFX_ASSERT(p_sleep_cfg);
    bool is_active;

    is_active = nrfy_grtc_sys_counter_check(NRF_GRTC);
    if (is_active)
    {
        nrfy_grtc_sys_counter_set(NRF_GRTC, false);
    }
    sleep_configure(p_sleep_cfg);
    if (is_active)
    {
        nrfy_grtc_sys_counter_set(NRF_GRTC, true);
    }
}


NRF_STATIC_INLINE bool nrf_grtc_sys_counter_check(NRF_GRTC_Type const * p_reg)
{
    return (p_reg->MODE & GRTC_MODE_SYSCOUNTEREN_Msk) ? true : false;
}

NRFY_STATIC_INLINE void nrfy_grtc_sys_counter_set(NRF_GRTC_Type * p_reg, bool enable)
{
    nrf_grtc_sys_counter_set(p_reg, enable);
    nrf_barrier_w();
}

NRF_STATIC_INLINE void nrf_grtc_sys_counter_set(NRF_GRTC_Type * p_reg, bool enable)
{
    p_reg->MODE = ((p_reg->MODE & ~GRTC_MODE_SYSCOUNTEREN_Msk) |
                  ((enable ? GRTC_MODE_SYSCOUNTEREN_Enabled :
                  GRTC_MODE_SYSCOUNTEREN_Disabled) << GRTC_MODE_SYSCOUNTEREN_Pos));
}

// Not relevant to nrf54L (ARM)
NRF_STATIC_INLINE void nrf_barrier_w(void)
{
#if defined(ISA_RISCV)
    RISCV_FENCE(ow, ow);
#endif
}

static void sleep_configure(nrfx_grtc_sleep_config_t const * p_sleep_cfg)
{
    nrfy_grtc_sys_counter_auto_mode_set(NRF_GRTC, p_sleep_cfg->auto_mode);
    nrfy_grtc_timeout_set(NRF_GRTC, p_sleep_cfg->timeout);
    nrfy_grtc_waketime_set(NRF_GRTC, p_sleep_cfg->waketime);
}

static void sleep_configuration_get(nrfx_grtc_sleep_config_t * p_sleep_cfg)
{
    p_sleep_cfg->auto_mode = nrfy_grtc_sys_counter_auto_mode_check(NRF_GRTC);
    p_sleep_cfg->timeout = nrfy_grtc_timeout_get(NRF_GRTC);
    p_sleep_cfg->waketime = nrfy_grtc_waketime_get(NRF_GRTC);
}
int nrfx_grtc_channel_alloc(uint8_t * p_channel)
{
    int rv = nrfx_flag32_alloc(&m_cb.available_channels);
    if (rv < 0)
    {
        return rv;
    }

    *p_channel = (uint8_t)rv;
    return 0;
}

int nrfx_grtc_syscounter_cc_int_disable(uint8_t channel)
{
    NRFX_ASSERT(m_cb.state != NRFX_DRV_STATE_UNINITIALIZED);
    int err_code = syscounter_check(channel);
    if (err_code != 0)
    {
        NRFX_LOG_WARNING("Function: %s, error code: %s.",
                         __func__,
                         NRFX_LOG_ERROR_STRING_GET(err_code));
        return err_code;
    }
    if (!is_channel_used(channel))
    {
        err_code = -EINVAL;
        NRFX_LOG_WARNING("Function: %s, error code: %s.",
                         __func__,
                         NRFX_LOG_ERROR_STRING_GET(err_code));
        return err_code;
    }

    nrfy_grtc_int_disable(NRF_GRTC, NRF_GRTC_CHANNEL_INT_MASK(channel));
    NRFX_LOG_INFO("GRTC SYSCOUNTER compare interrupt for channel %u disabled.", (uint32_t)channel);
    return err_code;
}

NRFY_STATIC_INLINE void nrfy_grtc_int_disable(NRF_GRTC_Type * p_reg, uint32_t mask)
{
    nrf_grtc_int_disable(p_reg, mask);
    nrf_barrier_w();
}
NRF_STATIC_INLINE void nrf_grtc_int_disable(NRF_GRTC_Type * p_reg, uint32_t mask)
{
    p_reg->GRTC_INTENCLR = mask;
}


int nrfx_grtc_syscounter_cc_disable(uint8_t channel)
{
    NRFX_ASSERT(m_cb.state != NRFX_DRV_STATE_UNINITIALIZED);
    uint32_t   int_mask = NRF_GRTC_CHANNEL_INT_MASK(channel);
    int err_code = syscounter_check(channel);
    if (err_code != 0)
    {
        NRFX_LOG_WARNING("Function: %s, error code: %s.",
                         __func__,
                         NRFX_LOG_ERROR_STRING_GET(err_code));
        return err_code;
    }
    if (!is_channel_used(channel))
    {
        err_code = -EINVAL;
        NRFX_LOG_WARNING("Function: %s, error code: %s.",
                         __func__,
                         NRFX_LOG_ERROR_STRING_GET(err_code));
        return err_code;
    }
    channel_used_unmark(channel);

    nrfy_grtc_sys_counter_compare_event_disable(NRF_GRTC, channel);

    if (nrfy_grtc_int_enable_check(NRF_GRTC, int_mask))
    {
        nrfy_grtc_int_disable(NRF_GRTC, int_mask);
        if (nrfy_grtc_sys_counter_compare_event_check(NRF_GRTC, channel))
        {
            nrfy_grtc_sys_counter_compare_event_clear(NRF_GRTC, channel);
            err_code = -ETIMEDOUT;
            NRFX_LOG_WARNING("Function: %s, error code: %s.",
                             __func__,
                             NRFX_LOG_ERROR_STRING_GET(err_code));
            return err_code;
        }
    }
    NRFX_LOG_INFO("GRTC SYSCOUNTER compare for channel %u disabled.", (uint32_t)channel);
    return err_code;
}


NRF_STATIC_INLINE void nrf_grtc_sys_counter_compare_event_disable(NRF_GRTC_Type * p_reg,
                                                                  uint8_t         cc_channel)
{
#if NRF_GRTC_HAS_EXTENDED
    NRFX_ASSERT(cc_channel < NRF_GRTC_SYSCOUNTER_CC_COUNT);
#else
    NRFX_ASSERT(cc_channel < NRF_GRTC_SYSCOUNTER_CC_COUNT &&
                cc_channel > NRF_GRTC_MAIN_CC_CHANNEL);
#endif
    p_reg->CC[cc_channel].CCEN = GRTC_CC_CCEN_ACTIVE_Disable;
}