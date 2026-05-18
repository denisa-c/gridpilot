/*
 * safety_island.c — Reference implementation skeleton for the FFR
 * safety-island controller. This is a STARTING POINT: production
 * deployment requires:
 *
 *   1. MISRA-C 2012 compliance verified by PC-lint Plus or Polyspace.
 *   2. WCET analysis using AbsInt aiT or Bound-T on the chosen target
 *      platform; report appended to the SIL-2 evidence package.
 *   3. Formal Property Verification (Cadence JasperGold or AdaCore SPARK)
 *      on the safety properties enumerated in SafetyIsland.tla.
 *   4. Constrained-random simulation in SystemVerilog UVM if running on
 *      FPGA, following the Ceesay-Seitz et al. 2020 CROME methodology.
 *   5. Hardware-in-the-loop test against the Statnett FFR pre-qualification
 *      protocol (programmable AC source + frequency injector).
 *
 * This file IS NOT YET CERTIFIED. The repository version is the architectural
 * skeleton that the WP3.5 deliverable of the ProACT proposal builds upon.
 */
#include "safety_island.h"
#include <string.h>

/* ====================================================================== */
/* Static state — single instance, allocated at .bss                       */
/* ====================================================================== */
static struct {
    bool             initialised;
    bool             armed;
    bool             bid_window_open;
    bool             table_loaded;
    bool             activation_in_progress;

    /* Active table; staged table is loaded into [STAGE] then swapped */
    table_entry_t    table[MAX_GPUS];
    uint8_t          n_table_entries;

    /* Bid parameters */
    int32_t          activation_threshold_mhz;
    uint32_t         contracted_capacity_w;

    /* Activation metrics */
    uint32_t         last_activation_id;
    uint32_t         last_activation_latency_us;
    uint32_t         wcet_observed_us;

    /* Fault state */
    fault_code_t     fault_code;
    uint32_t         fault_detail;

    /* Backend pointer */
    actuation_backend_t actuation_backend;

    /* Pending event buffer (single slot, written by activate, read by supervisor) */
    activation_event_t pending_event;
    bool              pending_event_valid;
} g_island;


/* ====================================================================== */
/* CRC-32 (Castagnoli polynomial 0x1EDC6F41) — table-driven, constant time */
/* ====================================================================== */
static uint32_t crc32_castagnoli(const uint8_t *data, size_t len)
{
    /* TODO: replace with the table-driven implementation. The polynomial
     * choice MUST match the supervisor; see protocol_spec.yaml. */
    (void)data;
    (void)len;
    return 0U;  /* placeholder */
}


/* ====================================================================== */
/* Public API implementation                                               */
/* ====================================================================== */

si_status_t si_init(void)
{
    memset(&g_island, 0, sizeof(g_island));
    g_island.initialised = true;
    return SI_OK;
}

si_status_t si_load_table(const table_entry_t *table, uint8_t n_entries,
                            uint32_t expected_crc32)
{
    if (!g_island.initialised) {
        return SI_INTERNAL_ERROR;
    }
    if (n_entries > MAX_GPUS) {
        return SI_RANGE_ERROR;
    }
    /* Validate every entry */
    for (uint8_t i = 0U; i < n_entries; i++) {
        if (table[i].normal_pcap_w < MIN_PCAP_W ||
            table[i].normal_pcap_w > MAX_PCAP_W) {
            return SI_RANGE_ERROR;
        }
        if (table[i].ffr_pcap_w >= table[i].normal_pcap_w) {
            return SI_RANGE_ERROR;
        }
    }
    /* CRC check */
    uint32_t computed_crc = crc32_castagnoli(
        (const uint8_t *)table, (size_t)n_entries * sizeof(table_entry_t));
    if (computed_crc != expected_crc32) {
        return SI_CRC_ERROR;
    }
    /* Atomic swap — disable preemption, copy, re-enable */
    /* TODO: on real hardware use __atomic_store_n with appropriate barriers */
    if (g_island.activation_in_progress) {
        return SI_BUSY;
    }
    memcpy(g_island.table, table, (size_t)n_entries * sizeof(table_entry_t));
    g_island.n_table_entries = n_entries;
    g_island.table_loaded = true;
    return SI_OK;
}

si_status_t si_open_bid_window(uint64_t bid_start_unix_us,
                                 uint64_t bid_end_unix_us,
                                 uint32_t contracted_capacity_w,
                                 int32_t  activation_threshold_mhz)
{
    (void)bid_start_unix_us;
    (void)bid_end_unix_us;
    if (!g_island.initialised) {
        return SI_INTERNAL_ERROR;
    }
    g_island.bid_window_open = true;
    g_island.contracted_capacity_w = contracted_capacity_w;
    g_island.activation_threshold_mhz = activation_threshold_mhz;
    return SI_OK;
}

si_status_t si_close_bid_window(void)
{
    g_island.bid_window_open = false;
    g_island.armed = false;
    return SI_OK;
}

si_status_t si_arm(void)
{
    if (!g_island.table_loaded) return SI_NO_TABLE;
    if (!g_island.bid_window_open) return SI_INTERNAL_ERROR;
    g_island.armed = true;
    return SI_OK;
}

si_status_t si_disarm(void)
{
    g_island.armed = false;
    return SI_OK;
}

/* THE ACTIVATION CRITICAL PATH — subject to WCET analysis. */
si_status_t si_inject_freq_sample(int32_t freq_signed_mhz, uint64_t t_unix_us)
{
    /* Constant-time threshold check */
    if (!g_island.armed) {
        return SI_NOT_ARMED;
    }
    if (g_island.activation_in_progress) {
        return SI_BUSY;
    }
    if (freq_signed_mhz <= g_island.activation_threshold_mhz) {
        return si_activate(t_unix_us, freq_signed_mhz);
    }
    return SI_OK;
}

si_status_t si_activate(uint64_t t_detection_unix_us,
                          int32_t  freq_at_detection_mhz)
{
    if (!g_island.table_loaded) return SI_NO_TABLE;
    if (g_island.actuation_backend == NULL) return SI_INTERNAL_ERROR;

    g_island.activation_in_progress = true;
    g_island.last_activation_id++;

    activation_event_t *ev = &g_island.pending_event;
    memset(ev, 0, sizeof(*ev));
    ev->activation_id = g_island.last_activation_id;
    ev->detection_unix_us = t_detection_unix_us;
    ev->freq_at_detection_mhz = freq_at_detection_mhz;
    ev->n_gpus = g_island.n_table_entries;

    /* Bounded loop — n_table_entries <= MAX_GPUS = 32 */
    uint32_t total_capacity = 0U;
    for (uint8_t i = 0U; i < g_island.n_table_entries; i++) {
        const table_entry_t *e = &g_island.table[i];
        si_status_t rc = g_island.actuation_backend(
            e->gpu_index, e->ffr_pcap_w, t_detection_unix_us);
        ev->gpu_status[i].gpu_index = e->gpu_index;
        ev->gpu_status[i].pcap_before_w = e->normal_pcap_w;
        ev->gpu_status[i].pcap_after_w = e->ffr_pcap_w;
        ev->gpu_status[i].actuation_rc = (int8_t)rc;
        total_capacity += (uint32_t)(e->normal_pcap_w - e->ffr_pcap_w);
    }
    /* TODO: read monotonic clock here for actuation_unix_us */
    ev->actuation_unix_us = t_detection_unix_us;  /* placeholder */
    ev->activation_latency_us = (uint32_t)(ev->actuation_unix_us - ev->detection_unix_us);
    ev->activated_capacity_w = total_capacity;

    if (ev->activation_latency_us > g_island.wcet_observed_us) {
        g_island.wcet_observed_us = ev->activation_latency_us;
    }
    if (ev->activation_latency_us > MAX_LATENCY_BUDGET_US) {
        g_island.fault_code = FAULT_WCET_VIOLATED;
        g_island.fault_detail = ev->activation_latency_us;
    }

    g_island.pending_event_valid = true;
    g_island.activation_in_progress = false;
    g_island.last_activation_latency_us = ev->activation_latency_us;
    return SI_OK;
}

si_status_t si_read_event(activation_event_t *out_event)
{
    if (!g_island.pending_event_valid) return SI_TIMEOUT;
    memcpy(out_event, &g_island.pending_event, sizeof(*out_event));
    g_island.pending_event_valid = false;
    return SI_OK;
}

health_flags_t si_get_health(void)
{
    health_flags_t h = { .raw = 0U };
    h.bits.freq_sensor_ok = 1U;  /* TODO: query the sensor */
    h.bits.actuation_backend_ok = (g_island.actuation_backend != NULL) ? 1U : 0U;
    h.bits.table_loaded = g_island.table_loaded ? 1U : 0U;
    h.bits.bid_window_open = g_island.bid_window_open ? 1U : 0U;
    return h;
}

fault_code_t si_get_fault(uint32_t *out_detail)
{
    if (out_detail != NULL) *out_detail = g_island.fault_detail;
    return g_island.fault_code;
}

uint32_t si_get_wcet_observed_us(void)
{
    return g_island.wcet_observed_us;
}

void si_register_actuation_backend(actuation_backend_t backend)
{
    g_island.actuation_backend = backend;
}
