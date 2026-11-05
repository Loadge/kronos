# The screenshot baselines are made here: the same image and the same install as the e2e job of
# .gitlab-ci.yml, so a baseline made on this machine compares clean in the pipeline. Text renders
# differently on Windows, which is why the snapshot tests only run on Linux. See bin/snapshots.py.
FROM python:3.12-slim
ENV PIP_ROOT_USER_ACTION=ignore PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /deps
COPY requirements.txt requirements-dev.txt ./
RUN pip install -q -r requirements-dev.txt && playwright install --with-deps chromium
WORKDIR /work
