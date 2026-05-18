/*
 * safety_island.h — Header for the FFR safety-island controller.
 *
 * This is the production-grade C skeleton for the safety-certified domain.
 * Compile with strict MISRA-C 2012 compliance. No dynamic memory allocation,
 * no recursion, bounded loops, no heap. WCET-analysable on ARM Cortex-M7
 * (option 1) or x86-64 with isolcpus (option 2).
 *
 * Reference standards:
 *   IEC 61508-3 (functional safety, software requirements, SIL 2)
 *   IEC 61131-3 (PLC programming languages)
 *   IEC 61850-9-2 (sampled values for grid frequency front-end)
 *   ISO 26262 (functional safety, road vehicles - patterns reused for HPC)
 *
 * Reference implementations:
 *   Lauer et al. 2020 "Enabling SIL2 Safety Certified Applications" (Eaton)
 *   Ferron et al. 2022 Sensors "Python Modules in Real-Time Plasma Systems"
 *     (doi:10.3390/s22072887) - hybrid C++/Python protective-trip pattern
 *   Ceesay-Seitz et al. 2020 CERN CROME formal-property-verification methodology
 */
#ifndef GRIDPILOT_SAFETY_ISLAND_H
#define GRIDPILOT_SAFETY_ISLAND_H

#include <stdint.h>
#include <stdbool.h>

/* ====================================================================== */
/* Compile-time configuration                                              */
/* ====================================================================== */
#define MAX_GPUS                      32U
#define MAX_LATENCY_BUDGET_US     700000U  /* Nordic FFR worst-case 0.7 s */
#define MIN_PCAP_W                   100U
#define MAX_PCAP_W                  1000U
#define FREQ_SAMPLE_PERIOD_US        1000U /* 1 kHz */
#define HEARTBEAT_TIMEOUT_MS         5000U

/* Static assertions catch budget violations at compile time */
_Static_assert(MAX_LATENCY_BUDGET_US <= 1000000U,
               "Budget cannot exceed 1 s for Nordic FFR");
_Static_assert(MAX_GPUS <= 32U,
               "Protocol limits MAX_GPUS to 32");

/* ====================================================================== */
/* Public types                                                            */
/* ====================================================================== */

/* Activation table entry — one row per GPU under island control */
typedef struct {
    uint8_t  gpu_index;
    uint16_t normal_pcap_w;
    uint16_t ffr_pcap_w;
    uint16_t reserved;     /* alignment padding */
} table_entry_t;

/* Activation event — sent to supervisor after every activation */
typedef struct {
    uint32_t activation_id;
    uint64_t detection_unix_us;
    uint64_t actuation_unix_us;
    uint32_t activation_latency_us;
    uint32_t activated_capacity_w;
    int32_t  freq_at_detection_mhz;
    uint8_t  n_gpus;
    /* Per-GPU outcome encoded in fixed array (no malloc) */
    struct {
        uint8_t  gpu_index;
        uint16_t pcap_before_w;
        uint16_t pcap_after_w;
        int8_t   actuation_rc;
        uint32_t elapsed_us;
    } gpu_status[MAX_GPUS];
    uint32_t crc32;
} activation_event_t;

/* Health status flags */
typedef union {
    uint8_t raw;
    struct {
        uint8_t freq_sensor_ok       : 1;
        uint8_t actuation_backend_ok : 1;
        uint8_t table_loaded         : 1;
        uint8_t bid_window_open      : 1;
        uint8_t reserved             : 4;
    } bits;
} health_flags_t;

/* Fault codes */
typedef enum {
    FAULT_NONE                = 0,
    FAULT_FREQ_SENSOR_LOST    = 1,
    FAULT_FREQ_OUT_OF_RANGE   = 2,
    FAULT_ACTUATION_TIMEOUT   = 3,
    FAULT_TABLE_CORRUPT       = 4,
    FAULT_WCET_VIOLATED       = 5,
} fault_code_t;

/* Return codes for the activation API */
typedef enum {
    SI_OK             = 0,
    SI_NOT_ARMED      = -1,
    SI_NO_TABLE       = -2,
    SI_BUSY           = -3,
    SI_RANGE_ERROR    = -4,
    SI_CRC_ERROR      = -5,
    SI_TIMEOUT        = -6,
    SI_INTERNAL_ERROR = -7,
} si_status_t;

/* ====================================================================== */
/* Public API                                                              */
/* ====================================================================== */

/* Initialise the safety island. Must be called once at boot, before any
 * other API. Returns SI_OK or a fault code. */
si_status_t si_init(void);

/* Load an activation table. Atomic from the activation path's perspective:
 * the new table is staged and only swapped in after CRC32 validates.
 * This function may block briefly (<100 us) but does NOT pre-empt an
 * in-progress activation. */
si_status_t si_load_table(const table_entry_t *table, uint8_t n_entries,
                           uint32_t expected_crc32);

/* Open a bid window. The island will not arm until this is called. */
si_status_t si_open_bid_window(uint64_t bid_start_unix_us,
                                uint64_t bid_end_unix_us,
                                uint32_t contracted_capacity_w,
                                int32_t  activation_threshold_mhz);

/* Close the bid window and disarm. */
si_status_t si_close_bid_window(void);

/* Arm the FFR responder. Requires table loaded AND bid window open. */
si_status_t si_arm(void);

/* Disarm. Activation will not occur even if frequency drops. */
si_status_t si_disarm(void);

/* Inject a frequency sample (called by the PMU front-end at 1 kHz).
 * This is the entry to the activation critical path. The function:
 *   1. Reads the threshold (constant time, no locking on the hot path).
 *   2. Compares against threshold (constant time).
 *   3. If breached and armed: dispatches activation through si_activate().
 * Worst-case execution time is bounded; see WCET analysis report. */
si_status_t si_inject_freq_sample(int32_t freq_signed_mhz, uint64_t t_unix_us);

/* The activation path itself. Called only by si_inject_freq_sample().
 * Walks the loaded table and dispatches per-GPU pcap actuation through
 * the platform-specific backend. Bounded loop over n_entries. */
si_status_t si_activate(uint64_t t_detection_unix_us,
                          int32_t  freq_at_detection_mhz);

/* Read the latest activation event into the supervisor's buffer.
 * Returns SI_OK if an event is pending, SI_TIMEOUT if none. */
si_status_t si_read_event(activation_event_t *out_event);

/* Read current health and fault state. Constant time. */
health_flags_t si_get_health(void);
fault_code_t   si_get_fault(uint32_t *out_detail);
uint32_t       si_get_wcet_observed_us(void);

/* ====================================================================== */
/* Platform-specific backends — implemented per target                     */
/* ====================================================================== */

/* The actuation backend translates a (gpu_index, pcap_w) command into a
 * platform-specific action. On the V100 reference platform this calls
 * NVML or IPMI; on a certified platform it calls the OEM's verified API.
 * MUST return within MAX_PER_GPU_ACTUATION_US (default 50000 us). */
typedef si_status_t (*actuation_backend_t)(uint8_t  gpu_index,
                                             uint16_t target_pcap_w,
                                             uint64_t t_unix_us);

/* Register the backend at boot. */
void si_register_actuation_backend(actuation_backend_t backend);

/* The frequency-measurement backend pushes samples into si_inject_freq_sample
 * at FREQ_SAMPLE_PERIOD_US intervals. Implemented as a hardware interrupt
 * handler on the certified platform; as a polling thread on x86-64. */

#endif /* GRIDPILOT_SAFETY_ISLAND_H */
