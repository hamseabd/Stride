.PHONY: up down build push deploy test chat logs-checkin logs-agent logs-sms feedback feedback-user

# ── Config ────────────────────────────────────────────────────────────────────
TABLE ?= stride-prod

# ── Local development ──────────────────────────────────────────────────────
up:
	docker compose up --build

down:
	docker compose down -v

test:
	cd scrumbot-app && .venv/bin/python -m pytest tests/ -v

chat:
	cd scrumbot-app && PYTHONPATH=. .venv/bin/python chat.py

# ── Build + push images ─────────────────────────────────────────────────────
build:
	./scripts/build_and_push.sh latest

push:
	./scripts/build_and_push.sh sha-$(shell git rev-parse --short HEAD)

# ── Deploy to AWS ───────────────────────────────────────────────────────────
deploy: push
	cd scrumbot-infra && terraform apply \
	  -var="image_tag=sha-$(shell git rev-parse --short HEAD)"

# ── Logs ────────────────────────────────────────────────────────────────────
logs-checkin:
	aws logs tail /aws/lambda/stride-checkin --follow

logs-agent:
	aws logs tail /aws/lambda/stride-agent --follow

logs-sms:
	aws logs tail /aws/lambda/stride-sms --follow

# ── Feedback (dev tool — scan is acceptable here, not a Lambda path) ──────────
feedback:
	aws dynamodb scan \
	  --table-name $(TABLE) \
	  --filter-expression "begins_with(sk, :f)" \
	  --expression-attribute-values '{":f":{"S":"FEEDBACK#"}}' \
	  --query "Items[*].{user:pk.S,body:body.S,source:source.S,at:created_at.S}" \
	  --output table

feedback-user:
	@test -n "$(USER)" || (echo "Usage: make feedback-user USER=+15551234567" && exit 1)
	aws dynamodb query \
	  --table-name $(TABLE) \
	  --key-condition-expression "pk = :pk AND begins_with(sk, :f)" \
	  --expression-attribute-values '{":pk":{"S":"USER#$(USER)"},":f":{"S":"FEEDBACK#"}}' \
	  --query "Items[*].{body:body.S,source:source.S,at:created_at.S}" \
	  --output table
