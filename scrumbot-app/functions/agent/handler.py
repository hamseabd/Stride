import json

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response
from strands import Agent
from strands.models.anthropic import AnthropicModel

from shared.prompt import STRIDE_SYSTEM_PROMPT
from shared.tools import (
    create_project, update_project, create_work_cycle, list_active_projects,
    create_task, update_task_status, get_cycle_data,
    create_checkin, flag_blocker, get_pace_history, get_user_patterns,
    record_velocity, update_user_patterns, complete_onboarding,
    set_user_preference,
    create_habit, complete_habit, list_habits,
)

logger = Logger()
tracer = Tracer()
app = APIGatewayHttpResolver()

MAX_HISTORY_TURNS = 20

TOOLS = [
    create_project, update_project, create_work_cycle, list_active_projects,
    create_task, update_task_status, get_cycle_data,
    create_checkin, flag_blocker, get_pace_history, get_user_patterns,
    record_velocity, update_user_patterns, complete_onboarding,
    set_user_preference,
    create_habit, complete_habit, list_habits,
]


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


@app.post("/ceremony")
def ceremony():
    """
    POST /ceremony
    Body: { user_id, type, message, history }
    type: setup | planning | checkin | review | refinement
    """
    body    = app.current_event.json_body
    user_id = body.get("user_id", "").strip()
    message = body.get("message", "").strip()
    history = body.get("history", [])

    if not user_id:
        return _bad_request("user_id is required")
    if not message:
        return _bad_request("message is required")

    # Cap history — never let context grow unbounded
    if len(history) > MAX_HISTORY_TURNS:
        logger.warning("History truncated", original=len(history), cap=MAX_HISTORY_TURNS)
        history = history[-MAX_HISTORY_TURNS:]

    logger.info("Ceremony request", user_id=user_id, session_type=body.get("type"))

    system = STRIDE_SYSTEM_PROMPT.strip() + f"\n\nCurrent user_id: {user_id}"

    try:
        model  = AnthropicModel(model_id="claude-sonnet-4-6", max_tokens=1024)
        agent  = Agent(model=model, system_prompt=system, tools=TOOLS, messages=history)
        result = agent(message)

        logger.info("Ceremony complete", user_id=user_id)
        return {"reply": str(result), "history": agent.messages}

    except Exception as e:
        logger.exception("Agent call failed", user_id=user_id)
        return _server_error("Something went wrong — please try again")


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    return app.resolve(event, context)
