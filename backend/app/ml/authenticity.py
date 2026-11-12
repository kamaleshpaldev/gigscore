"""Data Authenticity & Fraud Detection Engine for GigScore.

Prototype - synthetic data only. Not for real lending decisions.
"""
from typing import Any, Dict, Iterable, List, Optional
import math

from app.schemas.score import AuthenticityReport, AuthenticityStatusEnum


def evaluate_earnings_authenticity(
    monthly_records: Iterable[Dict[str, Any]],
    declared_tenure_months: Optional[int] = None,
    raw_transactions: Optional[Iterable[Dict[str, Any]]] = None,
) -> AuthenticityReport:
    """Evaluate bank-verified vs claimed earnings and transaction anomalies in memory.

    Checks performed:
    1. Claimed earnings vs. mock bank-credit comparison (bank_vs_claimed_ratio).
    2. Round-number detection (suspiciously exact multiples of 1,000 / 5,000).
    3. Duplicate transaction detection (identical amount + timestamp/reference/month-platform).
    4. Impossible income-jump detection (sudden >3.5x single-month spike above baseline).
    5. Tenure consistency checks (claimed tenure vs observed monthly history span).

    Raw records are processed strictly in memory and never persisted.
    """
    records: List[Dict[str, Any]] = []
    for r in monthly_records or []:
        if hasattr(r, "model_dump"):
            records.append(r.model_dump())
        elif isinstance(r, dict):
            records.append(dict(r))

    flags: List[str] = []

    if not records:
        flags.append("INSUFFICIENT_EARNINGS_DATA: No monthly earnings records provided.")
        return AuthenticityReport(
            status=AuthenticityStatusEnum.NEEDS_REVIEW,
            needs_review=True,
            flags=flags,
            bank_vs_claimed_ratio=0.0,
            round_number_ratio=0.0,
            duplicate_transaction_count=0,
            max_monthly_jump_ratio=1.0,
            tenure_consistent=False,
        )

    # 1. Bank-credit vs claimed-earnings comparison
    total_claimed = 0.0
    total_bank_verified = 0.0
    non_zero_amounts: List[float] = []
    monthly_verified_by_month: Dict[str, float] = {}

    for rec in records:
        claimed = max(0.0, float(rec.get("claimed_earnings_inr") or 0.0))
        verified = max(0.0, float(rec.get("bank_verified_credit_inr") or 0.0))
        total_claimed += claimed
        total_bank_verified += verified

        month_key = str(rec.get("month") or "0000-00")
        monthly_verified_by_month[month_key] = (
            monthly_verified_by_month.get(month_key, 0.0) + verified
        )

        if claimed > 0:
            non_zero_amounts.append(claimed)
        if verified > 0:
            non_zero_amounts.append(verified)

    if total_claimed > 0:
        bank_vs_claimed_ratio = round(total_bank_verified / total_claimed, 4)
    else:
        bank_vs_claimed_ratio = 1.0 if total_bank_verified > 0 else 0.0

    if total_claimed > 1000.0 and (
        bank_vs_claimed_ratio < 0.72 or bank_vs_claimed_ratio > 1.35
    ):
        flags.append(
            f"BANK_VS_CLAIMED_MISMATCH: Bank-verified credits to claimed earnings ratio is {bank_vs_claimed_ratio:.2f} (expected 0.72-1.35)."
        )

    # 2. Round-number detection (exact multiples of ₹500 or ₹1,000 across payouts)
    if len(non_zero_amounts) >= 4:
        round_count = sum(
            1
            for amt in non_zero_amounts
            if amt >= 1000.0 and math.isclose(amt % 1000.0, 0.0, abs_tol=1e-2)
        )
        round_number_ratio = round(round_count / len(non_zero_amounts), 4)
        if round_number_ratio >= 0.75:
            flags.append(
                f"ROUND_NUMBER_ANOMALY: {round_number_ratio * 100:.0f}% of payout figures are exact multiples of ₹1,000."
            )
    else:
        round_number_ratio = 0.0

    # 3. Duplicate transaction / payout detection
    duplicate_count = 0
    seen_payout_signatures: set[tuple[Any, ...]] = set()
    for rec in records:
        sig = (
            str(rec.get("month") or ""),
            str(rec.get("platform") or ""),
            round(float(rec.get("bank_verified_credit_inr") or 0.0), 2),
            round(float(rec.get("claimed_earnings_inr") or 0.0), 2),
            int(rec.get("trips_or_orders_completed") or 0),
        )
        # Only count positive-amount exact duplicates or explicit duplicate_tx_count
        if sig[2] > 0 and sig in seen_payout_signatures:
            duplicate_count += 1
        seen_payout_signatures.add(sig)
        if rec.get("duplicate_tx_count"):
            duplicate_count += int(rec["duplicate_tx_count"])

    if raw_transactions:
        seen_tx: set[tuple[Any, ...]] = set()
        for tx in raw_transactions:
            tx_sig = (
                str(tx.get("timestamp") or tx.get("date") or ""),
                str(tx.get("platform") or ""),
                round(float(tx.get("amount_inr") or 0.0), 2),
                str(tx.get("utr") or ""),
            )
            if tx_sig in seen_tx:
                duplicate_count += 1
            seen_tx.add(tx_sig)

    if duplicate_count > 0:
        flags.append(
            f"DUPLICATE_TRANSACTIONS: Detected {duplicate_count} duplicate payout or transaction record(s)."
        )

    # 4. Impossible income-jump detection
    sorted_months = sorted(monthly_verified_by_month.keys())
    chronological_totals = [monthly_verified_by_month[m] for m in sorted_months]
    max_jump_ratio = 1.0
    if len(chronological_totals) >= 3:
        for i in range(1, len(chronological_totals)):
            prev_vals = [v for v in chronological_totals[:i] if v > 500.0]
            curr_val = chronological_totals[i]
            if prev_vals and curr_val > 0:
                baseline = sum(prev_vals) / len(prev_vals)
                if baseline >= 2000.0:
                    jump = curr_val / baseline
                    if jump > max_jump_ratio:
                        max_jump_ratio = round(jump, 4)

    if max_jump_ratio > 3.8:
        flags.append(
            f"IMPOSSIBLE_INCOME_JUMP: Single-month verified income spiked {max_jump_ratio:.1f}x above prior baseline."
        )

    # 5. Tenure consistency checks
    observed_distinct_months = len(sorted_months)
    tenure_consistent = True
    if declared_tenure_months is not None:
        if declared_tenure_months < 0 or declared_tenure_months > 120:
            tenure_consistent = False
            flags.append(
                f"TENURE_INCONSISTENCY: Declared tenure ({declared_tenure_months} months) is outside valid operational bounds."
            )
        elif observed_distinct_months > declared_tenure_months + 2:
            tenure_consistent = False
            flags.append(
                f"TENURE_INCONSISTENCY: Observed {observed_distinct_months} months of earnings but declared tenure is only {declared_tenure_months} months."
            )
        elif declared_tenure_months >= 24 and observed_distinct_months < max(
            6, int(declared_tenure_months * 0.35)
        ):
            tenure_consistent = False
            flags.append(
                f"TENURE_INCONSISTENCY: Declared tenure is {declared_tenure_months} months but only {observed_distinct_months} months of bank history exist."
            )

    needs_review = len(flags) > 0
    status = (
        AuthenticityStatusEnum.NEEDS_REVIEW
        if needs_review
        else AuthenticityStatusEnum.VERIFIED
    )

    return AuthenticityReport(
        status=status,
        needs_review=needs_review,
        flags=flags,
        bank_vs_claimed_ratio=bank_vs_claimed_ratio,
        round_number_ratio=round_number_ratio,
        duplicate_transaction_count=duplicate_count,
        max_monthly_jump_ratio=max_jump_ratio,
        tenure_consistent=tenure_consistent,
    )

