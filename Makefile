.PHONY: up down build push deploy test eval-l1 eval-l2 eval-classifier chat logs-sms logs-scheduler feedback feedback-user deploy-site analyze analyze-cost analyze-quality analyze-week conversations conversations-user conversations-all

# ── Config ────────────────────────────────────────────────────────────────────
TABLE ?= stride-prod

# ── Local development ──────────────────────────────────────────────────────
up:
	docker compose up --build

down:
	docker compose down -v

test:
	cd scrumbot-app && .venv/bin/python -m pytest tests/ -v

eval-l1:
	cd scrumbot-app && .venv/bin/python -m pytest evals/l1/test_assertions.py evals/regression/ -v --tb=short -m "not integration"

# L2 judge runs on Amazon Nova Pro via Bedrock — needs AWS creds + Bedrock model
# access (resolved from the standard boto3 credential chain), not an Anthropic key.
eval-l2:
	cd scrumbot-app && .venv/bin/python -m pytest evals/l2/ -v -s -m nightly

eval-classifier:
	cd scrumbot-app && ANTHROPIC_API_KEY=$(ANTHROPIC_API_KEY) .venv/bin/python -m pytest evals/l1/test_classifier.py -v -m integration

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
logs-sms:
	aws logs tail /aws/lambda/stride-sms --follow

logs-scheduler:
	aws logs tail /aws/lambda/stride-scheduler --follow

# ── Analytics (queries CloudWatch Logs Insights) ─────────────────────────
analyze:
	cd scrumbot-app && PYTHONPATH=. .venv/bin/python ../scripts/analyze.py --all

analyze-cost:
	cd scrumbot-app && PYTHONPATH=. .venv/bin/python ../scripts/analyze.py --cost

analyze-quality:
	cd scrumbot-app && PYTHONPATH=. .venv/bin/python ../scripts/analyze.py --quality

analyze-week:
	cd scrumbot-app && PYTHONPATH=. .venv/bin/python ../scripts/analyze.py --all --hours 168

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

# ── Conversations (prompt review) ─────────────────────────────────────────────
conversations:
	cd scrumbot-app && PYTHONPATH=. .venv/bin/python ../scripts/conversations.py

conversations-user:
	@test -n "$(USER)" || (echo "Usage: make conversations-user USER=+16124014226" && exit 1)
	cd scrumbot-app && PYTHONPATH=. .venv/bin/python ../scripts/conversations.py --user $(USER)

conversations-all:
	cd scrumbot-app && PYTHONPATH=. .venv/bin/python ../scripts/conversations.py --all-users

# ── Site ──────────────────────────────────────────────────────────────────────
deploy-site:
	cd scrumbot-infra && terraform apply -auto-approve \
	  -target=aws_s3_bucket.site \
	  -target=aws_s3_bucket_website_configuration.site \
	  -target=aws_s3_bucket_public_access_block.site \
	  -target=aws_s3_bucket_policy.site
	bash scripts/deploy_site.sh
