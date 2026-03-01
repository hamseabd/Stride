#!/usr/bin/env bash
set -euo pipefail

AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION="us-east-1"
REGISTRY="${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"
TAG="${1:-latest}"

echo "Building images for Linux ARM64 → ECR"
echo "Registry : ${REGISTRY}"
echo "Tag      : ${TAG}"
echo ""

# Authenticate Docker with ECR
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${REGISTRY}"

# Build and push each function
for FUNCTION in checkin agent sms; do
  IMAGE="${REGISTRY}/stride-${FUNCTION}"

  echo "→ Building stride-${FUNCTION}..."
  docker build \
    --platform linux/arm64 \
    --provenance=false \
    --build-arg FUNCTION="${FUNCTION}" \
    -t "${IMAGE}:${TAG}" \
    -t "${IMAGE}:latest" \
    scrumbot-app/

  echo "→ Pushing stride-${FUNCTION}..."
  docker push "${IMAGE}:${TAG}"
  docker push "${IMAGE}:latest"

  echo "✓ stride-${FUNCTION} pushed as ${TAG}"
  echo ""
done

echo "All images pushed."
echo ""
echo "Deploy with:"
echo "  cd scrumbot-infra && terraform apply -var=\"image_tag=${TAG}\""
