"""
Simulation & Calibration Router.

Provides endpoints for:
- Running AI simulations on historical data
- Tag-specific precision-recall calibration
- Viewing calibration dashboard
- Testing different thresholds
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import SimulationRun, TagCalibration
from schemas.models import (
    SimulationRunRequest,
    SimulationRunResponse,
    TagCalibrationRequest,
    TagCalibrationResponse,
    CalibrationDashboardResponse,
)
from ai.calibration import (
    calibrate_tag,
    run_simulation,
    get_tag_calibrations,
    get_calibration_dashboard,
    get_effective_threshold,
    DEFAULT_THRESHOLD,
)
from utils.exceptions import ValidationError, DatabaseError
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


# =============================================================================
# Simulation Endpoints
# =============================================================================


@router.post("/run", response_model=SimulationRunResponse)
async def start_simulation(
    req: SimulationRunRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Run AI simulation on historical ticket data.

    This tests how the AI would perform on past tickets,
    allowing you to evaluate accuracy before changing settings.

    The simulation:
    1. Samples historical tickets matching the filter
    2. Compares AI predictions against actual outcomes
    3. Calculates precision, recall, and F1 scores
    4. Generates confusion matrix
    """
    try:
        result = await run_simulation(
            db=db,
            name=req.name,
            sample_size=req.sample_size,
            ticket_filter=req.ticket_filter,
            test_threshold=req.test_new_threshold,
        )

        return SimulationRunResponse(
            id=result["simulation_id"],
            name=result["name"],
            status=result["status"],
            started_at=str(datetime.utcnow()),
            completed_at=str(datetime.utcnow()),
            total_tickets=result.get("total_tickets", 0),
            correct_predictions=result.get("accuracy", 0)
            * result.get("total_tickets", 0),
            incorrect_predictions=(1 - result.get("accuracy", 0))
            * result.get("total_tickets", 0),
            accuracy=result.get("accuracy", 0),
            precision=result.get("precision", 0),
            recall=result.get("recall", 0),
            f1_score=result.get("f1_score", 0),
            confusion_matrix=result.get("confusion_matrix", {}),
        )
    except Exception as e:
        logger.error(f"Simulation failed: {e}")
        raise DatabaseError(f"Simulation failed: {e}")


@router.get("/runs", response_model=List[SimulationRunResponse])
async def list_simulations(
    db: Session = Depends(get_db),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
):
    """Get list of simulation runs."""
    query = db.query(SimulationRun)

    if status:
        query = query.filter(SimulationRun.status == status)

    runs = query.order_by(SimulationRun.started_at.desc()).limit(limit).all()

    return [
        SimulationRunResponse(
            id=r.id,
            name=r.name,
            status=r.status,
            started_at=str(r.started_at),
            completed_at=str(r.completed_at) if r.completed_at else None,
            total_tickets=r.total_tickets or 0,
            correct_predictions=r.correct_predictions or 0,
            incorrect_predictions=r.incorrect_predictions or 0,
            accuracy=r.accuracy or 0,
            precision=r.precision or 0,
            recall=r.recall or 0,
            f1_score=r.f1_score or 0,
            confusion_matrix=r.confusion_matrix or {},
        )
        for r in runs
    ]


@router.get("/runs/{simulation_id}", response_model=SimulationRunResponse)
async def get_simulation(
    simulation_id: str,
    db: Session = Depends(get_db),
):
    """Get details for a specific simulation run."""
    run = db.query(SimulationRun).filter(SimulationRun.id == simulation_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Simulation not found")

    return SimulationRunResponse(
        id=run.id,
        name=run.name,
        status=run.status,
        started_at=str(run.started_at),
        completed_at=str(run.completed_at) if run.completed_at else None,
        total_tickets=run.total_tickets or 0,
        correct_predictions=run.correct_predictions or 0,
        incorrect_predictions=run.incorrect_predictions or 0,
        accuracy=run.accuracy or 0,
        precision=run.precision or 0,
        recall=run.recall or 0,
        f1_score=run.f1_score or 0,
        confusion_matrix=run.confusion_matrix or {},
    )


# =============================================================================
# Calibration Endpoints
# =============================================================================


@router.post("/calibrate", response_model=TagCalibrationResponse)
async def calibrate_tag_threshold(
    req: TagCalibrationRequest,
    db: Session = Depends(get_db),
):
    """
    Calibrate threshold for a specific tag.

    Calibration goals:
    - high_precision: Minimize false positives (e.g., "Billing Error")
    - high_recall: Minimize false negatives (e.g., "Churn Risk")
    - balanced: Optimize F1 score

    The system analyzes historical data to find the optimal threshold
    for your specified goal.
    """
    result = await calibrate_tag(
        db=db,
        tag=req.tag,
        goal=req.goal.value,
        target_precision=req.target_precision,
        target_recall=req.target_recall,
    )

    if "error" in result:
        raise ValidationError("tag", result["error"])

    return TagCalibrationResponse(
        id=result.get("calibration_id", ""),
        tag=req.tag,
        goal=req.goal.value,
        current_precision=result["at_recommended_threshold"]["precision"],
        current_recall=result["at_recommended_threshold"]["recall"],
        current_threshold=result["recommended_threshold"],
        recommended_threshold=result["recommended_threshold"],
        sample_size=result["sample_size"],
        last_calibrated=str(datetime.utcnow()),
    )


@router.get("/calibrations", response_model=List[TagCalibrationResponse])
async def list_calibrations(db: Session = Depends(get_db)):
    """Get all tag calibrations."""
    calibrations = await get_tag_calibrations(db)

    return [
        TagCalibrationResponse(
            id=c["id"],
            tag=c["tag"],
            goal=c["goal"],
            current_precision=c["current_precision"] or 0,
            current_recall=c["current_recall"] or 0,
            current_threshold=c["current_threshold"] or DEFAULT_THRESHOLD,
            recommended_threshold=c["current_threshold"] or DEFAULT_THRESHOLD,
            sample_size=c["sample_size"] or 0,
            last_calibrated=c["last_calibrated"] or "",
        )
        for c in calibrations
    ]


@router.get("/calibrations/{tag}")
async def get_tag_calibration(
    tag: str,
    db: Session = Depends(get_db),
):
    """Get calibration for a specific tag."""
    calibration = db.query(TagCalibration).filter(TagCalibration.tag == tag).first()
    if not calibration:
        # Return default values if not calibrated
        return {
            "tag": tag,
            "is_calibrated": False,
            "effective_threshold": DEFAULT_THRESHOLD,
            "goal": "balanced",
            "message": "Tag not yet calibrated. Using default threshold.",
        }

    return {
        "id": calibration.id,
        "tag": calibration.tag,
        "is_calibrated": True,
        "goal": calibration.goal,
        "effective_threshold": calibration.current_threshold,
        "current_precision": calibration.current_precision,
        "current_recall": calibration.current_recall,
        "target_precision": calibration.target_precision,
        "target_recall": calibration.target_recall,
        "sample_size": calibration.sample_size,
        "last_calibrated": str(calibration.last_calibrated),
    }


@router.delete("/calibrations/{tag}")
async def delete_calibration(
    tag: str,
    db: Session = Depends(get_db),
):
    """Remove calibration for a tag (revert to default threshold)."""
    calibration = db.query(TagCalibration).filter(TagCalibration.tag == tag).first()
    if not calibration:
        raise HTTPException(status_code=404, detail="Calibration not found")

    db.delete(calibration)
    db.commit()

    logger.info(f"Calibration deleted for tag: {tag}")

    return {"success": True, "tag": tag, "message": "Reverted to default threshold"}


# =============================================================================
# Dashboard
# =============================================================================


@router.get("/dashboard", response_model=CalibrationDashboardResponse)
async def get_dashboard(db: Session = Depends(get_db)):
    """
    Get calibration dashboard overview.

    Shows:
    - Default threshold
    - All tag calibrations
    - Overall precision/recall
    - Recent simulations
    """
    dashboard = await get_calibration_dashboard(db)

    calibrations = [
        TagCalibrationResponse(
            id=c["id"],
            tag=c["tag"],
            goal=c["goal"],
            current_precision=c["current_precision"] or 0,
            current_recall=c["current_recall"] or 0,
            current_threshold=c["current_threshold"] or DEFAULT_THRESHOLD,
            recommended_threshold=c["current_threshold"] or DEFAULT_THRESHOLD,
            sample_size=c["sample_size"] or 0,
            last_calibrated=c["last_calibrated"] or "",
        )
        for c in dashboard.get("calibrations", [])
    ]

    recent_sims = [
        SimulationRunResponse(
            id=s["id"],
            name=s["name"],
            status=s["status"],
            started_at=s["started_at"],
            completed_at=None,
            total_tickets=0,
            correct_predictions=0,
            incorrect_predictions=0,
            accuracy=s.get("accuracy", 0) or 0,
            precision=0,
            recall=0,
            f1_score=0,
            confusion_matrix={},
        )
        for s in dashboard.get("recent_simulations", [])
    ]

    return CalibrationDashboardResponse(
        default_threshold=dashboard["default_threshold"],
        tag_calibrations=calibrations,
        overall_precision=dashboard.get("overall_precision", 0) or 0,
        overall_recall=dashboard.get("overall_recall", 0) or 0,
        recent_simulations=recent_sims,
    )


# =============================================================================
# Threshold Testing
# =============================================================================


@router.post("/test-threshold")
async def test_threshold(
    threshold: float = Query(..., ge=0.5, le=0.99, description="Threshold to test"),
    sample_size: int = Query(100, ge=10, le=1000),
    category: Optional[str] = Query(None, description="Filter by category"),
    db: Session = Depends(get_db),
):
    """
    Quick test of a threshold value.

    Runs a mini-simulation to see how the threshold would perform.
    """
    ticket_filter = {"category": category} if category else None

    result = await run_simulation(
        db=db,
        name=f"Threshold test: {threshold}",
        sample_size=sample_size,
        ticket_filter=ticket_filter,
        test_threshold=threshold,
    )

    return {
        "threshold_tested": threshold,
        "default_threshold": DEFAULT_THRESHOLD,
        "sample_size": result.get("total_tickets", 0),
        "accuracy": result.get("accuracy", 0),
        "precision": result.get("precision", 0),
        "recall": result.get("recall", 0),
        "f1_score": result.get("f1_score", 0),
        "recommendation": _get_threshold_recommendation(
            result.get("precision", 0),
            result.get("recall", 0),
            threshold,
        ),
    }


def _get_threshold_recommendation(
    precision: float, recall: float, threshold: float
) -> str:
    """Generate recommendation based on test results."""
    f1 = (
        2 * (precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0
    )

    if f1 >= 0.8:
        return f"Good performance. Consider using threshold {threshold} if it meets your goals."
    elif precision >= 0.8 and recall < 0.6:
        return "High precision but low recall. Consider lowering threshold to catch more cases."
    elif recall >= 0.8 and precision < 0.6:
        return "High recall but low precision. Consider raising threshold to reduce false positives."
    else:
        return "Mixed results. Consider adjusting threshold or reviewing training data."
