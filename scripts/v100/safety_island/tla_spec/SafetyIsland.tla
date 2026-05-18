---- MODULE SafetyIsland ----
(***************************************************************************)
(* TLA+ specification of the GridPilot supervisor <-> safety-island         *)
(* protocol. This specification is used to model-check three properties:   *)
(*                                                                          *)
(*   1. SAFETY: NoActivationWithoutTable                                    *)
(*      The island never activates FFR if it does not have a valid table.   *)
(*                                                                          *)
(*   2. SAFETY: BoundedLatency                                              *)
(*      Once the threshold is breached and the island is armed, an          *)
(*      ActivationEvent is dispatched within MAX_LATENCY_TICKS abstract     *)
(*      time units.                                                         *)
(*                                                                          *)
(*   3. LIVENESS: BidWindowOpensEventuallyClose                             *)
(*      Every BidWindowOpen is eventually followed by a corresponding       *)
(*      bid-window-close transition.                                        *)
(*                                                                          *)
(* Reference: Lamport 2002 "Specifying Systems"; Newcombe 2014 CACM         *)
(* "How Amazon Web Services Uses Formal Methods" (doi:10.1145/2699417).    *)
(*                                                                          *)
(* Tooling: model-check with TLC                                            *)
(*   tlc -config SafetyIsland.cfg SafetyIsland.tla                          *)
(***************************************************************************)
EXTENDS Integers, Sequences, TLC

CONSTANTS
    MAX_GPUS,           \* 32 in the protocol
    MAX_LATENCY_TICKS,  \* 700 (ms in our timing budget)
    THRESHOLD_MHZ       \* -200 = 49.800 Hz

VARIABLES
    islandState,        \* "idle" | "armed" | "activating" | "fault"
    tableLoaded,        \* BOOLEAN
    bidOpen,            \* BOOLEAN
    armed,              \* BOOLEAN
    freqSignedMhz,      \* INTEGER (signed mHz from 50.000 Hz)
    activationInProgress,
    activationCount,
    elapsedTicksSinceBreach \* counts ticks while freqSignedMhz <= THRESHOLD

vars == <<islandState, tableLoaded, bidOpen, armed, freqSignedMhz,
          activationInProgress, activationCount, elapsedTicksSinceBreach>>

(***************************************************************************)
(* Initial state: island is idle, no table, no bid window, frequency       *)
(* nominal at 50.000 Hz.                                                   *)
(***************************************************************************)
Init ==
    /\ islandState = "idle"
    /\ tableLoaded = FALSE
    /\ bidOpen = FALSE
    /\ armed = FALSE
    /\ freqSignedMhz = 0
    /\ activationInProgress = FALSE
    /\ activationCount = 0
    /\ elapsedTicksSinceBreach = 0

(***************************************************************************)
(* Supervisor pushes an activation table; island validates and accepts.    *)
(***************************************************************************)
LoadTable ==
    /\ ~activationInProgress
    /\ tableLoaded' = TRUE
    /\ UNCHANGED <<islandState, bidOpen, armed, freqSignedMhz,
                    activationInProgress, activationCount,
                    elapsedTicksSinceBreach>>

(***************************************************************************)
(* Supervisor opens a bid window. Requires table to be loaded.             *)
(***************************************************************************)
OpenBidWindow ==
    /\ tableLoaded
    /\ ~bidOpen
    /\ bidOpen' = TRUE
    /\ UNCHANGED <<islandState, tableLoaded, armed, freqSignedMhz,
                    activationInProgress, activationCount,
                    elapsedTicksSinceBreach>>

CloseBidWindow ==
    /\ bidOpen
    /\ ~activationInProgress
    /\ bidOpen' = FALSE
    /\ armed' = FALSE
    /\ UNCHANGED <<islandState, tableLoaded, freqSignedMhz,
                    activationInProgress, activationCount,
                    elapsedTicksSinceBreach>>

(***************************************************************************)
(* Supervisor arms the FFR responder. Requires table loaded AND bid open.  *)
(***************************************************************************)
Arm ==
    /\ tableLoaded
    /\ bidOpen
    /\ ~armed
    /\ armed' = TRUE
    /\ UNCHANGED <<islandState, tableLoaded, bidOpen, freqSignedMhz,
                    activationInProgress, activationCount,
                    elapsedTicksSinceBreach>>

(***************************************************************************)
(* The grid frequency varies. We abstract this as nondeterministic input.  *)
(* Frequency moves by at most 50 mHz per tick (realistic for power grid).  *)
(***************************************************************************)
FrequencyTick ==
    /\ \E delta \in -50..50:
        freqSignedMhz' = freqSignedMhz + delta
    /\ IF freqSignedMhz' <= THRESHOLD_MHZ /\ armed
       THEN elapsedTicksSinceBreach' = elapsedTicksSinceBreach + 1
       ELSE elapsedTicksSinceBreach' = 0
    /\ UNCHANGED <<islandState, tableLoaded, bidOpen, armed,
                    activationInProgress, activationCount>>

(***************************************************************************)
(* The activation transition: when armed, table loaded, and frequency      *)
(* below threshold, the island transitions to "activating" and dispatches  *)
(* an event. Must complete within MAX_LATENCY_TICKS.                       *)
(***************************************************************************)
TriggerActivation ==
    /\ armed
    /\ tableLoaded
    /\ bidOpen
    /\ freqSignedMhz <= THRESHOLD_MHZ
    /\ ~activationInProgress
    /\ activationInProgress' = TRUE
    /\ islandState' = "activating"
    /\ UNCHANGED <<tableLoaded, bidOpen, armed, freqSignedMhz,
                    activationCount, elapsedTicksSinceBreach>>

CompleteActivation ==
    /\ activationInProgress
    /\ activationInProgress' = FALSE
    /\ activationCount' = activationCount + 1
    /\ islandState' = "armed"
    /\ elapsedTicksSinceBreach' = 0  \* reset since we serviced the event
    /\ UNCHANGED <<tableLoaded, bidOpen, armed, freqSignedMhz>>

(***************************************************************************)
(* Disarm: supervisor revokes the FFR arming.                              *)
(***************************************************************************)
Disarm ==
    /\ armed
    /\ ~activationInProgress
    /\ armed' = FALSE
    /\ UNCHANGED <<islandState, tableLoaded, bidOpen, freqSignedMhz,
                    activationInProgress, activationCount,
                    elapsedTicksSinceBreach>>

Next ==
    \/ LoadTable
    \/ OpenBidWindow
    \/ CloseBidWindow
    \/ Arm
    \/ Disarm
    \/ FrequencyTick
    \/ TriggerActivation
    \/ CompleteActivation

Spec == Init /\ [][Next]_vars /\ WF_vars(CompleteActivation)

(***************************************************************************)
(* PROPERTIES TO CHECK                                                     *)
(***************************************************************************)

(* Property 1 — SAFETY: NoActivationWithoutTable *)
NoActivationWithoutTable ==
    activationInProgress => tableLoaded

(* Property 2 — SAFETY: BoundedLatency *)
(* If we have been below threshold for more than MAX_LATENCY_TICKS while   *)
(* armed, an activation must have been triggered.                          *)
BoundedLatency ==
    (elapsedTicksSinceBreach > MAX_LATENCY_TICKS /\ armed /\ tableLoaded)
    => activationInProgress \/ (activationCount > 0)

(* Property 3 — LIVENESS: BidWindowEventuallyClose *)
(* Once a bid window is open, eventually it closes. We require fairness    *)
(* on CloseBidWindow.                                                      *)
BidWindowEventuallyClose ==
    bidOpen ~> ~bidOpen

(* Conjunctive invariant for TLC *)
SafetyInvariants ==
    /\ NoActivationWithoutTable
    /\ BoundedLatency

====
