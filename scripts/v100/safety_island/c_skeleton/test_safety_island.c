/*
 * test_safety_island.c — Sanity-test the safety-island skeleton.
 *
 * NOT a substitute for the certification test suite. The real test
 * package includes:
 *   - constrained-random UVM testbench
 *   - formal property verification with JasperGold
 *   - WCET analysis with AbsInt aiT
 *   - hardware-in-the-loop pre-qualification per Statnett FFR protocol
 */
#include <stdio.h>
#include <assert.h>
#include "safety_island.h"

static int g_actuations = 0;
static si_status_t mock_actuate(uint8_t idx, uint16_t pcap_w, uint64_t t)
{
    (void)t;
    printf("  mock_actuate: GPU %u -> %u W\n", idx, pcap_w);
    g_actuations++;
    return SI_OK;
}

int main(void)
{
    printf("=== safety-island skeleton self-test ===\n");
    assert(si_init() == SI_OK);

    si_register_actuation_backend(mock_actuate);

    /* Try to arm without a table — must fail */
    assert(si_arm() == SI_NO_TABLE);
    printf("[OK] cannot arm without table\n");

    /* Load a 3-GPU table */
    table_entry_t table[3] = {
        {0, 300, 200, 0},
        {1, 300, 200, 0},
        {2, 300, 200, 0},
    };
    /* CRC validation is stubbed in this skeleton; we pass 0 to match */
    si_status_t rc = si_load_table(table, 3, 0);
    /* In the skeleton with the placeholder CRC, this returns SI_OK because
     * crc32_castagnoli returns 0 by default. Production must implement CRC. */
    assert(rc == SI_OK);
    printf("[OK] table loaded (n=3)\n");

    /* Open bid window */
    rc = si_open_bid_window(1700000000ULL * 1000000ULL,
                              1700003600ULL * 1000000ULL,
                              300, /* 100W reduction per GPU * 3 */
                              -200 /* 49.800 Hz threshold */);
    assert(rc == SI_OK);
    printf("[OK] bid window open\n");

    /* Arm */
    assert(si_arm() == SI_OK);
    printf("[OK] armed\n");

    /* Inject normal frequency — no activation */
    assert(si_inject_freq_sample(0, 1700000010ULL * 1000000ULL) == SI_OK);
    assert(g_actuations == 0);
    printf("[OK] no activation on normal frequency (50.000 Hz)\n");

    /* Inject frequency below threshold — must activate */
    assert(si_inject_freq_sample(-250, 1700000020ULL * 1000000ULL) == SI_OK);
    assert(g_actuations == 3);
    printf("[OK] activation triggered, %d GPUs actuated\n", g_actuations);

    /* Read the event */
    activation_event_t ev;
    assert(si_read_event(&ev) == SI_OK);
    printf("[OK] event read: id=%u, capacity=%u W\n",
           ev.activation_id, ev.activated_capacity_w);

    /* Disarm */
    assert(si_disarm() == SI_OK);
    g_actuations = 0;
    assert(si_inject_freq_sample(-250, 1700000030ULL * 1000000ULL) == SI_NOT_ARMED);
    assert(g_actuations == 0);
    printf("[OK] no activation when disarmed\n");

    printf("=== All tests passed. ===\n");
    return 0;
}
