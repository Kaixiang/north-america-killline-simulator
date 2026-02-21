# -*- coding: utf-8 -*-
"""
Kill Line: North America - Annual simulator prototype

Usage:
  python annual_sim.py --years 25 --seed 42
"""
from __future__ import annotations

import argparse
import random
from dataclasses import dataclass, field
from enum import Enum


class MacroCycle(str, Enum):
    BOOM = "Boom"
    TIGHTENING = "Tightening"
    RECESSION = "Recession"


MACRO_PARAMS = {
    MacroCycle.BOOM: {
        "income_mult": 1.08,
        "asset_return": 0.11,
        "risk_base": 0.08,
    },
    MacroCycle.TIGHTENING: {
        "income_mult": 0.98,
        "asset_return": 0.03,
        "risk_base": 0.16,
    },
    MacroCycle.RECESSION: {
        "income_mult": 0.85,
        "asset_return": -0.10,
        "risk_base": 0.30,
    },
}

CYCLE_TRANSITION = {
    MacroCycle.BOOM: [
        (MacroCycle.BOOM, 0.62),
        (MacroCycle.TIGHTENING, 0.33),
        (MacroCycle.RECESSION, 0.05),
    ],
    MacroCycle.TIGHTENING: [
        (MacroCycle.TIGHTENING, 0.48),
        (MacroCycle.BOOM, 0.20),
        (MacroCycle.RECESSION, 0.32),
    ],
    MacroCycle.RECESSION: [
        (MacroCycle.RECESSION, 0.56),
        (MacroCycle.TIGHTENING, 0.31),
        (MacroCycle.BOOM, 0.13),
    ],
}


@dataclass
class Portfolio:
    index_funds: float = 20000.0
    tech_stocks: float = 15000.0
    leveraged_etf: float = 3000.0
    passive_income_assets: float = 6000.0
    real_estate: float = 0.0
    debt: float = 4000.0


@dataclass
class PlayerState:
    cash: float = 20000.0
    income_power: float = 75000.0
    mental: float = 62.0
    stability: float = 55.0
    career_risk: float = 0.46
    portfolio: Portfolio = field(default_factory=Portfolio)

    bankrupt_streak: int = 0
    max_drawdown: float = 0.0
    peak_net_worth: float = 0.0
    risk_exposure_sum: float = 0.0


@dataclass
class YearResult:
    year: int
    cycle: MacroCycle
    income: float
    expenses: float
    asset_delta: float
    risk_triggered: str | None
    fragility: float
    volatility: float
    net_worth: float
    cash: float


class AnnualSimulator:
    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self.state = PlayerState()
        self.current_cycle = MacroCycle.BOOM

    def choose_next_cycle(self) -> MacroCycle:
        transitions = CYCLE_TRANSITION[self.current_cycle]
        r = self.rng.random()
        acc = 0.0
        for cycle, prob in transitions:
            acc += prob
            if r <= acc:
                return cycle
        return transitions[-1][0]

    def volatility(self) -> float:
        p = self.state.portfolio
        invest_total = max(1.0, p.index_funds + p.tech_stocks + p.leveraged_etf + p.passive_income_assets)
        weighted_invest_risk = (
            p.index_funds * 0.12 + p.tech_stocks * 0.22 + p.leveraged_etf * 0.45 + p.passive_income_assets * 0.08
        ) / invest_total
        return min(0.95, weighted_invest_risk + self.state.career_risk * 0.45)

    def fragility(self, annual_expenses: float) -> float:
        p = self.state.portfolio
        assets_total = max(1.0, p.index_funds + p.tech_stocks + p.leveraged_etf + p.passive_income_assets + p.real_estate)
        leverage_ratio = max(0.0, p.debt / assets_total)
        high_vol_ratio = (p.tech_stocks + p.leveraged_etf) / max(1.0, p.index_funds + p.tech_stocks + p.leveraged_etf)

        yearly_passive_income = p.passive_income_assets * 0.12
        net_income = max(1.0, self.state.income_power + yearly_passive_income)
        cashflow_pressure = max(0.0, (annual_expenses - net_income) / annual_expenses)

        value = (
            leverage_ratio * 0.4
            + high_vol_ratio * 0.3
            + cashflow_pressure * 0.2
            + self.state.career_risk * 0.1
        )
        return max(0.0, min(1.5, value))

    def annual_expenses(self) -> float:
        p = self.state.portfolio
        base_living = 38000.0
        mortgage = p.real_estate * 0.045
        health = 7000.0
        education = 2500.0
        debt_cost = p.debt * 0.09
        return base_living + mortgage + health + education + debt_cost

    def annual_asset_change(self, cycle: MacroCycle, vol: float) -> float:
        p = self.state.portfolio
        params = MACRO_PARAMS[cycle]

        market_shock = self.rng.uniform(-1.0, 1.0) * vol
        base_return = params["asset_return"]

        index_delta = p.index_funds * (base_return * 0.75 + market_shock * 0.35)
        tech_delta = p.tech_stocks * (base_return * 1.25 + market_shock * 0.75)
        lev_delta = p.leveraged_etf * (base_return * 2.0 + market_shock * 1.25)
        passive_delta = p.passive_income_assets * (0.04 + market_shock * 0.12)
        house_delta = p.real_estate * (base_return * 0.55 + market_shock * 0.22)

        p.index_funds += index_delta
        p.tech_stocks += tech_delta
        p.leveraged_etf += lev_delta
        p.passive_income_assets += passive_delta
        p.real_estate += house_delta

        p.index_funds = max(0.0, p.index_funds)
        p.tech_stocks = max(0.0, p.tech_stocks)
        p.leveraged_etf = max(0.0, p.leveraged_etf)
        p.passive_income_assets = max(0.0, p.passive_income_assets)
        p.real_estate = max(0.0, p.real_estate)

        return index_delta + tech_delta + lev_delta + passive_delta + house_delta

    def risk_check(self, cycle: MacroCycle, fragility: float) -> str | None:
        params = MACRO_PARAMS[cycle]
        mental_multiplier = 1.0 + max(0.0, (55.0 - self.state.mental) / 120.0)
        risk_rate = params["risk_base"] * fragility * mental_multiplier
        if fragility > 0.85:
            risk_rate *= 2.0

        if self.rng.random() > risk_rate:
            return None

        events = ["Layoff", "Medical Shock", "Market Crash", "Startup Failure"]
        event = self.rng.choice(events)
        if event == "Layoff":
            self.state.cash -= 12000
            self.state.income_power *= 0.86
            self.state.mental -= 8
            self.state.career_risk = min(0.95, self.state.career_risk + 0.08)
        elif event == "Medical Shock":
            self.state.cash -= 18000
            self.state.mental -= 12
            self.state.stability -= 4
        elif event == "Market Crash":
            p = self.state.portfolio
            p.tech_stocks *= 0.83
            p.leveraged_etf *= 0.70
            self.state.mental -= 9
        elif event == "Startup Failure":
            self.state.cash -= 22000
            self.state.income_power *= 0.90
            self.state.stability -= 7
            self.state.career_risk = min(0.98, self.state.career_risk + 0.12)
        return event

    def net_worth(self) -> float:
        p = self.state.portfolio
        assets = p.index_funds + p.tech_stocks + p.leveraged_etf + p.passive_income_assets + p.real_estate
        return assets + self.state.cash - p.debt

    def run_year(self, year: int) -> YearResult:
        self.current_cycle = self.choose_next_cycle()
        annual_expenses = self.annual_expenses()
        vol = self.volatility()
        frag = self.fragility(annual_expenses)

        yearly_income = self.state.income_power * MACRO_PARAMS[self.current_cycle]["income_mult"]
        yearly_income += self.state.portfolio.passive_income_assets * 0.12
        self.state.cash += yearly_income

        self.state.cash -= annual_expenses
        asset_delta = self.annual_asset_change(self.current_cycle, vol)

        risk_event = self.risk_check(self.current_cycle, frag)

        if self.state.cash < 0:
            self.state.bankrupt_streak += 1
        else:
            self.state.bankrupt_streak = 0

        self.state.mental = max(0.0, min(100.0, self.state.mental + self.rng.uniform(-2.5, 2.5)))
        self.state.stability = max(0.0, min(100.0, self.state.stability + self.rng.uniform(-1.8, 1.8)))

        nw = self.net_worth()
        self.state.peak_net_worth = max(self.state.peak_net_worth, nw)
        if self.state.peak_net_worth > 0:
            dd = (self.state.peak_net_worth - nw) / self.state.peak_net_worth
            self.state.max_drawdown = max(self.state.max_drawdown, dd)

        self.state.risk_exposure_sum += frag

        return YearResult(
            year=year,
            cycle=self.current_cycle,
            income=yearly_income,
            expenses=annual_expenses,
            asset_delta=asset_delta,
            risk_triggered=risk_event,
            fragility=frag,
            volatility=vol,
            net_worth=nw,
            cash=self.state.cash,
        )

    def is_failed(self) -> bool:
        return self.state.bankrupt_streak >= 2


def grade_endgame(sim: AnnualSimulator, years_survived: int) -> tuple[bool, str]:
    s = sim.state
    nw = sim.net_worth()
    frag_est = min(1.5, s.risk_exposure_sum / max(1, years_survived))

    safe_dims = 0
    if s.cash > 8000:
        safe_dims += 1
    if nw > 120000:
        safe_dims += 1
    if s.mental > 45:
        safe_dims += 1
    if s.stability > 45:
        safe_dims += 1

    win = years_survived >= 25 and safe_dims >= 2 and frag_est < 0.75
    score = (
        f"max_drawdown={s.max_drawdown:.2%}, "
        f"avg_risk={frag_est:.3f}, "
        f"stability={s.stability:.1f}, "
        f"net_worth={nw:,.0f}"
    )
    return win, score


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=25)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    sim = AnnualSimulator(seed=args.seed)
    results: list[YearResult] = []

    for y in range(1, args.years + 1):
        res = sim.run_year(y)
        results.append(res)
        event_txt = res.risk_triggered if res.risk_triggered else "-"
        print(
            f"Y{y:02d} {res.cycle.value:<10} "
            f"income={res.income:>10.0f} exp={res.expenses:>9.0f} "
            f"assetΔ={res.asset_delta:>9.0f} frag={res.fragility:.3f} "
            f"cash={res.cash:>10.0f} nw={res.net_worth:>11.0f} risk={event_txt}"
        )
        if sim.is_failed():
            print("\n[DEFEAT] Cash < 0 for 2 consecutive years -> bankruptcy risk triggered.")
            break

    win, score = grade_endgame(sim, len(results))
    print("\n=== ENDGAME ===")
    print(f"Survived years: {len(results)}")
    print(f"Result: {'VICTORY' if win else 'DEFEAT'}")
    print(f"Score: {score}")


if __name__ == "__main__":
    main()
