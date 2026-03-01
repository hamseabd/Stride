.PHONY: up down build push deploy logs-checkin logs-agent logs-sms

# ── Local development ──────────────────────────────────────────────────────
up:
	docker compose up --build

down:
	docker compose down -v

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
