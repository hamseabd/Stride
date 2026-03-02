import json

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response

from shared.tools import create_checkin, flag_blocker, get_cycle_data

logger = Logger()
tracer = Tracer()
app = APIGatewayHttpResolver()


def _bad_request(msg: str) -> Response:
    return Response(
        status_code=400,
        content_type="application/json",
        body=json.dumps({"error": msg}),
    )


def _server_error(msg: str) -> Response:
    return Response(
        status_code=500,
        content_type="application/json",
        body=json.dumps({"error": msg}),
    )


@app.post("/checkin")
def checkin():
    """
    POST /checkin
    Body: { user_id, did, doing, blocked, cycle_id? }

    Direct tool calls — no agent loop. Fast and cost-free.
    If blocked is non-empty and cycle_id is provided, flags the in_progress
    task as blocked automatically.
    """
    body     = app.current_event.json_body
    user_id  = body.get("user_id", "").strip()
    did      = body.get("did", "").strip()
    doing    = body.get("doing", "").strip()
    blocked  = body.get("blocked", "").strip()
    cycle_id = body.get("cycle_id", "").strip()

    if not user_id:
        return _bad_request("user_id is required")
    if not did or not doing:
        return _bad_request("did and doing are required")

    logger.info("Check-in received", user_id=user_id)

    result = create_checkin(user_id=user_id, did=did, doing=doing, blocked=blocked)
    if "error" in result:
        logger.error("create_checkin failed", user_id=user_id, error=result["error"])
        return _server_error(result["error"])

    blocker_result = None
    if blocked and cycle_id:
        cycle_data  = get_cycle_data(cycle_id=cycle_id)
        in_progress = [
            t for t in cycle_data.get("tasks", [])
            if t.get("status") == "in_progress"
        ]
        if in_progress:
            blocker_result = flag_blocker(
                task_id=in_progress[0]["task_id"],
                description=blocked,
                category="capacity",
            )
            if "error" in blocker_result:
                logger.warning(
                    "flag_blocker failed",
                    user_id=user_id,
                    error=blocker_result["error"],
                )
                blocker_result = None

    logger.info("Check-in saved", user_id=user_id, checkin_id=result["checkin_id"])
    return {
        "checkin_id": result["checkin_id"],
        "date":       result["date"],
        "blocker":    blocker_result,
        "message":    "Check-in saved",
    }


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    return app.resolve(event, context)
