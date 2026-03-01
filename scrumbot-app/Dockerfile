FROM public.ecr.aws/lambda/python:3.12

# Install dependencies first — this layer is cached unless requirements.txt changes
COPY requirements.txt .
RUN pip install -r requirements.txt \
      --target "${LAMBDA_TASK_ROOT}" \
      --no-cache-dir

# Copy shared library (tools, db, models, prompt, guards)
COPY shared/ ${LAMBDA_TASK_ROOT}/shared/

# Select which function handler to include at build time
# Usage: docker build --build-arg FUNCTION=checkin ...
ARG FUNCTION
COPY functions/${FUNCTION}/ ${LAMBDA_TASK_ROOT}/

CMD ["handler.handler"]
