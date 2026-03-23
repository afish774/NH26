"""
Precision-Recall Calibration Service.

This module provides:
- Tag-specific threshold calibration
- Precision/recall optimization
- Threshold recommendations
- Calibration analysis

Calibration Goals:
- HIGH_PRECISION: Minimize false positives (e.g., "Billing Error" - avoid false alarms)
- HIGH_RECALL: Minimize false negatives (e.g., "Churn Risk" - catch all cases)
- BALANCED: F1-score optimization
"""

import os
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass
import logging

from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from database.models import Ticket, TagCalibration, SimulationRun, AiAuditLog

logger = logging.getLogger(__name__)

# Default deflection threshold
DEFAULT_THRESHOLD = float(os.getenv("DEFLECTION_THRESHOLD", "0.72"))


@dataclass
class CalibrationMetrics:
    """Metrics for a calibration analysis."""

    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    precision: float
    recall: float
    f1_score: float
    threshold: float
    sample_size: int


def calculate_metrics(
    predictions: List[Tuple[float, bool]], threshold: float
) -> CalibrationMetrics:
    """
    Calculate precision/recall metrics for a given threshold.

    Args:
        predictions: List of (confidence_score, actual_correct) tuples
        threshold: Confidence threshold for positive prediction

    Returns:
        CalibrationMetrics with all metrics calculated
    """
    tp = fp = tn = fn = 0

    for confidence, actual_correct in predictions:
        predicted_positive = confidence >= threshold

        if predicted_positive and actual_correct:
            tp += 1
        elif predicted_positive and not actual_correct:
            fp += 1
        elif not predicted_positive and actual_correct:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * (precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return CalibrationMetrics(
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1_score=f1,
        threshold=threshold,
        sample_size=len(predictions),
    )


def find_optimal_threshold(
    predictions: List[Tuple[float, bool]],
    goal: str = "balanced",
    target_precision: Optional[float] = None,
    target_recall: Optional[float] = None,
) -> Tuple[float, CalibrationMetrics]:
    """
    Find optimal threshold for a given calibration goal.

    Args:
        predictions: List of (confidence_score, actual_correct) tuples
        goal: "high_precision", "high_recall", or "balanced"
        target_precision: Target precision (for high_precision goal)
        target_recall: Target recall (for high_recall goal)

    Returns:
        Tuple of (optimal_threshold, metrics_at_threshold)
    """
    if not predictions:
        return DEFAULT_THRESHOLD, CalibrationMetrics(
            0, 0, 0, 0, 0.0, 0.0, 0.0, DEFAULT_THRESHOLD, 0
        )

    # Test thresholds from 0.5 to 0.95 in 0.01 increments
    best_threshold = DEFAULT_THRESHOLD
    best_score = -1.0
    best_metrics = None

    for threshold_int in range(50, 96):
        threshold = threshold_int / 100.0
        metrics = calculate_metrics(predictions, threshold)

        if goal == "high_precision":
            # Maximize precision while keeping recall above minimum
            min_recall = 0.5  # Don't let recall drop too low
            if metrics.recall >= min_recall:
                if target_precision and metrics.precision >= target_precision:
                    score = metrics.precision + metrics.recall * 0.2  # Bonus for recall
                else:
                    score = metrics.precision
                if score > best_score:
                    best_score = score
                    best_threshold = threshold
                    best_metrics = metrics

        elif goal == "high_recall":
            # Maximize recall while keeping precision above minimum
            min_precision = 0.4  # Don't let precision drop too low
            if metrics.precision >= min_precision:
                if target_recall and metrics.recall >= target_recall:
                    score = metrics.recall + metrics.precision * 0.2
                else:
                    score = metrics.recall
                if score > best_score:
                    best_score = score
                    best_threshold = threshold
                    best_metrics = metrics

        else:  # balanced
            score = metrics.f1_score
            if score > best_score:
                best_score = score
                best_threshold = threshold
                best_metrics = metrics

    return best_threshold, best_metrics or calculate_metrics(
        predictions, DEFAULT_THRESHOLD
    )


async def calibrate_tag(
    db: Session,
    tag: str,
    goal: str = "balanced",
    target_precision: Optional[float] = None,
    target_recall: Optional[float] = None,
    lookback_days: int = 30,
) -> Dict[str, Any]:
    """
    Calibrate threshold for a specific tag.

    Args:
        db: Database session
        tag: Tag to calibrate (e.g., "Billing Error", "Churn Risk")
        goal: Calibration goal
        target_precision: Target precision for high_precision goal
        target_recall: Target recall for high_recall goal
        lookback_days: Days of historical data to analyze

    Returns:
        Dict with calibration results
    """
    since = datetime.utcnow() - timedelta(days=lookback_days)

    # Get tickets with this tag that have feedback (for ground truth)
    # We use agent corrections as ground truth for "was AI correct?"
    from database.models import AgentFeedback

    # Query tickets with the tag
    tickets = (
        db.query(Ticket)
        .filter(
            Ticket.created_at >= since,
            Ticket.tags.contains([tag]),  # PostgreSQL JSONB contains
        )
        .all()
    )

    # Build predictions list
    predictions = []
    for ticket in tickets:
        confidence = ticket.ai_confidence or 0.0

        # Check if there was negative feedback or correction for this ticket
        feedback = (
            db.query(AgentFeedback).filter(AgentFeedback.ticket_id == ticket.id).first()
        )

        # If no feedback, assume AI was correct (optimistic)
        # If negative/correction feedback, AI was wrong
        if feedback:
            was_correct = feedback.feedback_type == "positive"
        else:
            # No explicit feedback - use deflection success as proxy
            # If ticket was resolved without escalation, AI was helpful
            was_correct = ticket.status in ["resolved", "closed"]

        predictions.append((confidence, was_correct))

    if not predictions:
        return {
            "tag": tag,
            "error": "No data available for calibration",
            "sample_size": 0,
        }

    # Find optimal threshold
    optimal_threshold, metrics = find_optimal_threshold(
        predictions, goal, target_precision, target_recall
    )

    # Calculate current metrics (with default threshold)
    current_metrics = calculate_metrics(predictions, DEFAULT_THRESHOLD)

    # Save or update calibration
    calibration = db.query(TagCalibration).filter(TagCalibration.tag == tag).first()
    if calibration:
        calibration.goal = goal
        calibration.current_threshold = optimal_threshold
        calibration.current_precision = metrics.precision
        calibration.current_recall = metrics.recall
        calibration.target_precision = target_precision
        calibration.target_recall = target_recall
        calibration.sample_size = metrics.sample_size
        calibration.last_calibrated = datetime.utcnow()
    else:
        calibration = TagCalibration(
            id=str(uuid.uuid4()),
            tag=tag,
            goal=goal,
            current_threshold=optimal_threshold,
            current_precision=metrics.precision,
            current_recall=metrics.recall,
            target_precision=target_precision,
            target_recall=target_recall,
            sample_size=metrics.sample_size,
            last_calibrated=datetime.utcnow(),
        )
        db.add(calibration)

    db.commit()

    return {
        "tag": tag,
        "goal": goal,
        "sample_size": metrics.sample_size,
        "default_threshold": DEFAULT_THRESHOLD,
        "recommended_threshold": optimal_threshold,
        "improvement": {
            "precision_change": metrics.precision - current_metrics.precision,
            "recall_change": metrics.recall - current_metrics.recall,
            "f1_change": metrics.f1_score - current_metrics.f1_score,
        },
        "at_recommended_threshold": {
            "precision": round(metrics.precision, 4),
            "recall": round(metrics.recall, 4),
            "f1_score": round(metrics.f1_score, 4),
        },
        "at_default_threshold": {
            "precision": round(current_metrics.precision, 4),
            "recall": round(current_metrics.recall, 4),
            "f1_score": round(current_metrics.f1_score, 4),
        },
    }


async def get_tag_calibrations(db: Session) -> List[Dict[str, Any]]:
    """Get all tag calibrations."""
    calibrations = db.query(TagCalibration).order_by(TagCalibration.tag).all()

    return [
        {
            "id": c.id,
            "tag": c.tag,
            "goal": c.goal,
            "current_threshold": c.current_threshold,
            "current_precision": c.current_precision,
            "current_recall": c.current_recall,
            "target_precision": c.target_precision,
            "target_recall": c.target_recall,
            "sample_size": c.sample_size,
            "last_calibrated": str(c.last_calibrated) if c.last_calibrated else None,
        }
        for c in calibrations
    ]


def get_effective_threshold(tag: str, db: Session) -> float:
    """
    Get the effective threshold for a tag.

    Returns tag-specific threshold if calibrated, otherwise default.

    Args:
        tag: The tag to get threshold for
        db: Database session

    Returns:
        Effective confidence threshold
    """
    calibration = db.query(TagCalibration).filter(TagCalibration.tag == tag).first()

    if calibration and calibration.current_threshold:
        return calibration.current_threshold

    return DEFAULT_THRESHOLD


async def run_simulation(
    db: Session,
    name: str,
    sample_size: int = 100,
    ticket_filter: Optional[Dict[str, Any]] = None,
    test_threshold: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Run AI simulation on historical tickets.

    This replays historical tickets through the AI and compares
    predictions against actual outcomes.

    Args:
        db: Database session
        name: Name for this simulation run
        sample_size: Number of tickets to simulate
        ticket_filter: Filter criteria for tickets
        test_threshold: Optional threshold to test

    Returns:
        Simulation results
    """
    # Create simulation run record
    sim_run = SimulationRun(
        id=str(uuid.uuid4()),
        name=name,
        status="running",
        started_at=datetime.utcnow(),
        parameters={
            "sample_size": sample_size,
            "ticket_filter": ticket_filter,
            "test_threshold": test_threshold,
        },
    )
    db.add(sim_run)
    db.commit()

    try:
        # Build ticket query
        query = db.query(Ticket).filter(Ticket.ai_confidence.isnot(None))

        if ticket_filter:
            if "category" in ticket_filter:
                query = query.filter(Ticket.category == ticket_filter["category"])
            if "priority" in ticket_filter:
                query = query.filter(Ticket.priority == ticket_filter["priority"])
            if "date_from" in ticket_filter:
                query = query.filter(Ticket.created_at >= ticket_filter["date_from"])
            if "date_to" in ticket_filter:
                query = query.filter(Ticket.created_at <= ticket_filter["date_to"])

        # Get sample tickets
        tickets = query.order_by(func.random()).limit(sample_size).all()

        if not tickets:
            sim_run.status = "completed"
            sim_run.completed_at = datetime.utcnow()
            sim_run.results = {"error": "No tickets matched criteria"}
            db.commit()
            return {"error": "No tickets matched criteria", "simulation_id": sim_run.id}

        # Analyze predictions
        threshold = test_threshold or DEFAULT_THRESHOLD
        predictions = []

        for ticket in tickets:
            confidence = ticket.ai_confidence or 0.0

            # Determine ground truth based on outcome
            # Resolved without escalation = AI was helpful
            # Had corrections = AI was wrong
            from database.models import AgentFeedback

            feedback = (
                db.query(AgentFeedback)
                .filter(AgentFeedback.ticket_id == ticket.id)
                .first()
            )

            if feedback:
                was_correct = feedback.feedback_type == "positive"
            else:
                was_correct = ticket.status in ["resolved", "closed"]

            predictions.append((confidence, was_correct))

        # Calculate metrics
        metrics = calculate_metrics(predictions, threshold)

        # Build confusion matrix
        confusion_matrix = {
            "true_positives": metrics.true_positives,
            "false_positives": metrics.false_positives,
            "true_negatives": metrics.true_negatives,
            "false_negatives": metrics.false_negatives,
        }

        # Update simulation run
        sim_run.status = "completed"
        sim_run.completed_at = datetime.utcnow()
        sim_run.total_tickets = len(tickets)
        sim_run.correct_predictions = metrics.true_positives + metrics.true_negatives
        sim_run.incorrect_predictions = (
            metrics.false_positives + metrics.false_negatives
        )
        sim_run.accuracy = (
            (sim_run.correct_predictions / len(tickets)) if tickets else 0.0
        )
        sim_run.precision = metrics.precision
        sim_run.recall = metrics.recall
        sim_run.f1_score = metrics.f1_score
        sim_run.confusion_matrix = confusion_matrix
        sim_run.results = {
            "threshold_tested": threshold,
            "default_threshold": DEFAULT_THRESHOLD,
        }

        db.commit()

        return {
            "simulation_id": sim_run.id,
            "name": name,
            "status": "completed",
            "total_tickets": sim_run.total_tickets,
            "accuracy": round(sim_run.accuracy, 4),
            "precision": round(sim_run.precision, 4),
            "recall": round(sim_run.recall, 4),
            "f1_score": round(sim_run.f1_score, 4),
            "confusion_matrix": confusion_matrix,
            "threshold_tested": threshold,
        }

    except Exception as e:
        sim_run.status = "failed"
        sim_run.completed_at = datetime.utcnow()
        sim_run.results = {"error": str(e)}
        db.commit()
        logger.error(f"Simulation failed: {e}")
        raise


async def get_calibration_dashboard(db: Session) -> Dict[str, Any]:
    """Get overview of calibration status."""
    # Get all calibrations
    calibrations = await get_tag_calibrations(db)

    # Get recent simulations
    recent_sims = (
        db.query(SimulationRun).order_by(SimulationRun.started_at.desc()).limit(5).all()
    )

    # Calculate overall metrics from recent tickets
    since = datetime.utcnow() - timedelta(days=30)

    from database.models import AgentFeedback

    total_with_feedback = (
        db.query(AgentFeedback).filter(AgentFeedback.created_at >= since).count()
    )

    positive_feedback = (
        db.query(AgentFeedback)
        .filter(
            AgentFeedback.created_at >= since, AgentFeedback.feedback_type == "positive"
        )
        .count()
    )

    overall_precision = (
        (positive_feedback / total_with_feedback) if total_with_feedback > 0 else 1.0
    )

    return {
        "default_threshold": DEFAULT_THRESHOLD,
        "total_calibrations": len(calibrations),
        "calibrations": calibrations,
        "overall_precision": round(overall_precision, 4),
        "overall_recall": None,  # Would need more complex calculation
        "recent_simulations": [
            {
                "id": s.id,
                "name": s.name,
                "status": s.status,
                "accuracy": s.accuracy,
                "started_at": str(s.started_at),
            }
            for s in recent_sims
        ],
    }
