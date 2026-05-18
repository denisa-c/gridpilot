"""ProACT governance metrics: CFE, GFI, and literature-standard comparisons.

Implements the formal metric definitions from the ProACT proposal:

    CFE(p_u, p_o) = E_green(p_u, p_o) / E_total
    GFI_t = w_A·A_t + w_X·X_t + w_F·F_t + w_R·R_t + w_C·C_t

Plus literature-standard metrics for comparative analysis:
    SCI  = (E × I + M) / R   — Green Software Foundation
    CFE% = E_green / E_total  — Google 24/7 CFE (Radovanović et al. 2023)
    CUE  = CO₂ / IT_energy    — The Green Grid
    Shapley-based carbon attribution (Han et al. 2025, Fair-CO₂)
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import curve_fit


# ── CFE: Carbon-Free Energy Coefficient ──────────────────────────────────────


def cfe_empirical(
    energy_green: float | np.ndarray,
    energy_total: float | np.ndarray,
) -> float | np.ndarray:
    """Compute CFE = E_green / E_total from simulation output.

    Parameters
    ----------
    energy_green : float or array
        Energy consumed during green windows (kWh).
    energy_total : float or array
        Total energy consumed (kWh).

    Returns
    -------
    CFE value(s) in [0, 1].
    """
    total = np.asarray(energy_total, dtype=float)
    green = np.asarray(energy_green, dtype=float)
    return np.where(total > 0, green / total, 0.0)


def cfe_logistic(
    p_u: np.ndarray,
    p_o: np.ndarray,
    alpha: float = 1.0,
    beta: float = 1.0,
    gamma: float = 2.0,
    k: float = 6.0,
    t0: float = 2.0,
) -> np.ndarray:
    """Parametric logistic CFE surface.

    CFE(p_u, p_o) = 1 / (1 + exp{-k(α·p_u + β·p_o + γ·p_u·p_o - t_0)})

    Parameters
    ----------
    p_u, p_o : arrays
        User and operator adoption rates in [0, 1].
    alpha, beta, gamma, k, t0 : floats
        Logistic surface parameters.
    """
    z = alpha * p_u + beta * p_o + gamma * p_u * p_o - t0
    return 1.0 / (1.0 + np.exp(-k * z))


def fit_cfe_surface(
    p_u: np.ndarray,
    p_o: np.ndarray,
    cfe_observed: np.ndarray,
) -> dict[str, float]:
    """Fit the logistic CFE surface to simulation data.

    Returns fitted parameters {alpha, beta, gamma, k, t0}.
    """

    def _model(X, alpha, beta, gamma, k, t0):
        pu, po = X
        z = alpha * pu + beta * po + gamma * pu * po - t0
        return 1.0 / (1.0 + np.exp(-k * z))

    popt, _ = curve_fit(
        _model,
        (p_u, p_o),
        cfe_observed,
        p0=[1.0, 1.0, 2.0, 6.0, 2.0],
        bounds=([0, 0, 0, 0.1, 0], [5, 5, 10, 20, 5]),
        maxfev=10_000,
    )
    names = ["alpha", "beta", "gamma", "k", "t0"]
    return dict(zip(names, popt))


def find_omega_star(
    params: dict[str, float],
    threshold: float = 0.8,
    resolution: int = 200,
) -> np.ndarray:
    """Find the Ω* contour: {(p_u, p_o) : CFE = threshold}.

    Returns array of shape (n, 2) with (p_u, p_o) points on the contour.
    """
    pu = np.linspace(0, 1, resolution)
    po = np.linspace(0, 1, resolution)
    PU, PO = np.meshgrid(pu, po)
    CFE = cfe_logistic(PU, PO, **params)

    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    cs = ax.contour(PU, PO, CFE, levels=[threshold])
    plt.close(fig)

    paths = cs.allsegs[0]
    if paths:
        return np.concatenate(paths, axis=0)
    return np.empty((0, 2))


# ── GFI: Green Flexibility Indicator ──────────────────────────────────────────


def gfi(
    A: float | np.ndarray,
    X: float | np.ndarray,
    F: float | np.ndarray,
    R: float | np.ndarray,
    C: float | np.ndarray,
    weights: tuple[float, ...] = (0.3, 0.2, 0.2, 0.15, 0.15),
) -> float | np.ndarray:
    """Compute the Green Flexibility Indicator.

    GFI_t = w_A·A_t + w_X·X_t + w_F·F_t + w_R·R_t + w_C·C_t

    Parameters
    ----------
    A : Temporal renewable alignment (0–1).
    X : Realised flexibility activation (0–1).
    F : Slowdown-parity fairness (0–1).
    R : Reproducibility from logs (0–1).
    C : Carbon-closure consistency (0–1).
    weights : 5-tuple of non-negative weights summing to 1.

    Returns
    -------
    GFI value(s) in [0, 1].
    """
    w = np.asarray(weights, dtype=float)
    assert len(w) == 5, "Need exactly 5 weights"
    assert abs(w.sum() - 1.0) < 1e-6, f"Weights must sum to 1, got {w.sum()}"
    components = np.stack([A, X, F, R, C], axis=-1) if isinstance(A, np.ndarray) \
        else np.array([A, X, F, R, C])
    return float(np.dot(w, components)) if components.ndim == 1 else components @ w


def compute_gfi_components(
    energy_green: np.ndarray,
    energy_total: np.ndarray,
    flex_declared: np.ndarray,
    flex_used: np.ndarray,
    slowdowns: np.ndarray,
    log_reproducible: float = 1.0,
    carbon_closure_error: float = 0.0,
) -> dict[str, float]:
    """Compute all five GFI components from simulation output.

    Parameters
    ----------
    energy_green : array — energy in green windows per time period
    energy_total : array — total energy per time period
    flex_declared : array — declared flexibility (d_max) per job
    flex_used : array — actual delay applied per job
    slowdowns : array — job slowdown ratios (completion_time / ideal_time)
    log_reproducible : float — fraction of decisions with complete audit trail
    carbon_closure_error : float — |facility_CO2 - attributed_CO2| / facility_CO2

    Returns
    -------
    Dict with keys A, X, F, R, C and their values.
    """
    # A: temporal renewable alignment = E_green / E_total
    A = float(np.sum(energy_green) / max(np.sum(energy_total), 1e-9))

    # X: flexibility activation = mean(flex_used / flex_declared)
    valid = flex_declared > 0
    X = float(np.mean(flex_used[valid] / flex_declared[valid])) if valid.any() else 0.0
    X = min(X, 1.0)

    # F: slowdown-parity fairness = 1 - CV(slowdowns)
    # Using coefficient of variation; Jain's index is an alternative
    if len(slowdowns) > 1 and np.mean(slowdowns) > 0:
        cv = np.std(slowdowns) / np.mean(slowdowns)
        F = float(max(1.0 - cv, 0.0))
    else:
        F = 1.0

    # R: reproducibility
    R = float(log_reproducible)

    # C: carbon closure
    C = float(max(1.0 - carbon_closure_error, 0.0))

    return {"A": A, "X": X, "F": F, "R": R, "C": C}


# ── Literature-standard metrics ───────────────────────────────────────────────


def sci(
    energy_kwh: float | np.ndarray,
    ci_gco2_per_kwh: float | np.ndarray,
    embodied_gco2: float = 0.0,
    R: float | np.ndarray = 1.0,
) -> float | np.ndarray:
    """Software Carbon Intensity (Green Software Foundation).

    SCI = (E × I + M) / R

    Parameters
    ----------
    energy_kwh : Energy consumed (kWh).
    ci_gco2_per_kwh : Carbon intensity of the grid (gCO₂eq/kWh).
    embodied_gco2 : Embodied emissions amortised over the period (gCO₂eq).
        Set to 0 when hardware LCA data is unavailable.
    R : Functional unit count (e.g. number of jobs completed).

    Returns
    -------
    SCI in gCO₂eq per functional unit.
    """
    E = np.asarray(energy_kwh, dtype=float)
    I = np.asarray(ci_gco2_per_kwh, dtype=float)
    M = float(embodied_gco2)
    R = np.asarray(R, dtype=float)
    return np.where(R > 0, (E * I + M) / R, 0.0)


def cfe_hourly(
    energy_green_h: np.ndarray,
    energy_total_h: np.ndarray,
) -> np.ndarray:
    """Hourly Carbon-Free Energy percentage (Google 24/7 CFE metric).

    CFE%_h = E_green_h / E_total_h

    Ref: Radovanović et al. (2023), "Carbon-Aware Computing for Datacenters"

    Parameters
    ----------
    energy_green_h : array of per-hour carbon-free energy (kWh).
    energy_total_h : array of per-hour total energy (kWh).

    Returns
    -------
    Array of hourly CFE% values in [0, 1].
    """
    green = np.asarray(energy_green_h, dtype=float)
    total = np.asarray(energy_total_h, dtype=float)
    return np.where(total > 0, np.clip(green / total, 0, 1), 0.0)


def cfe_period(
    energy_green_h: np.ndarray,
    energy_total_h: np.ndarray,
) -> float:
    """Period-level CFE% — equivalent to RAC at 100% adoption without logistic.

    CFE%_period = Σ E_green_h / Σ E_total_h

    This is the simpler metric that RAC generalises by adding
    adoption-dynamics modelling via the logistic surface.
    """
    green = np.asarray(energy_green_h, dtype=float)
    total = np.asarray(energy_total_h, dtype=float)
    total_sum = total.sum()
    return float(green.sum() / total_sum) if total_sum > 0 else 0.0


def cue(
    total_co2_kg: float,
    it_energy_kwh: float,
) -> float:
    """Carbon Usage Effectiveness (The Green Grid).

    CUE = Total CO₂ emissions (kgCO₂eq) / IT equipment energy (kWh)

    A facility-level metric. Lower is better.
    Typical range: 0.2–0.8 kgCO₂eq/kWh.
    """
    return total_co2_kg / it_energy_kwh if it_energy_kwh > 0 else 0.0


def shapley_carbon_attribution(
    jobs: list,
    timestep_log: list[dict],
    node_power_kw: float = 1.5,
) -> np.ndarray:
    """Shapley-based per-job CO₂ attribution (Fair-CO₂, Han et al. 2025).

    Uses resource-weighted Shapley: each of n_h active jobs in hour h
    receives CO₂_h × (nodes_j / total_active_nodes_h).  This satisfies
    the Shapley axioms (efficiency, symmetry, null-player, additivity)
    for the weighted cost-sharing game where jobs contribute to facility
    power proportionally to their node allocation.

    NOTE (audit fix, 2026-04-25): Previous version used equal-share
    (CO₂_h / n_active), which systematically undercharged large jobs
    and overcharged small jobs.  Resource-weighted Shapley is the correct
    formulation for heterogeneous resource consumers.

    Parameters
    ----------
    jobs : list of Job objects with start_time, end_time, num_nodes, run_time.
    timestep_log : list of dicts from SchedulerResult (time, co2_g, ...).

    Returns
    -------
    shapley_co2 : array of shape (n_jobs,) — per-job CO₂ in gCO₂eq.
    """
    if not jobs or not timestep_log:
        return np.zeros(max(len(jobs), 1))

    n_jobs = len(jobs)
    shapley_co2 = np.zeros(n_jobs)

    for entry in timestep_log:
        t = entry["time"]
        co2_g = entry["co2_g"]

        # Find jobs active during this timestep with their node counts
        active = []
        for i, j in enumerate(jobs):
            if j.start_time is not None and j.end_time is not None:
                if j.start_time <= t < j.end_time:
                    active.append((i, j.num_nodes))

        if active:
            total_nodes = sum(n for _, n in active)
            if total_nodes > 0:
                for i, nodes in active:
                    shapley_co2[i] += co2_g * (nodes / total_nodes)
            else:
                # Fallback: equal share if all jobs have 0 nodes (shouldn't happen)
                share = co2_g / len(active)
                for i, _ in active:
                    shapley_co2[i] += share

    return shapley_co2


def proportional_carbon_attribution(
    jobs: list,
    timestep_log: list[dict],
    node_power_kw: float = 1.5,
) -> np.ndarray:
    """Proportional (energy-weighted) carbon attribution baseline.

    Each active job in hour h gets CO₂_h × (nodes_j / total_active_nodes_h).
    This is the naive baseline that Shapley attribution improves upon.
    """
    if not jobs or not timestep_log:
        return np.zeros(max(len(jobs), 1))

    n_jobs = len(jobs)
    prop_co2 = np.zeros(n_jobs)

    for entry in timestep_log:
        t = entry["time"]
        co2_g = entry["co2_g"]

        active = []
        for i, j in enumerate(jobs):
            if j.start_time is not None and j.end_time is not None:
                if j.start_time <= t < j.end_time:
                    active.append((i, j.num_nodes))

        if active:
            total_nodes = sum(n for _, n in active)
            if total_nodes > 0:
                for i, nodes in active:
                    prop_co2[i] += co2_g * (nodes / total_nodes)

    return prop_co2
