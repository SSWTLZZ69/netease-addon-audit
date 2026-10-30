FROM python:2.7.18-buster
WORKDIR /opt/audit
ENV PYTHONDONTWRITEBYTECODE=1 AUDIT_SKIP_INSTALL=1
COPY .ci/requirements-python2.txt .ci/requirements-python2.txt
RUN python -m pip install --disable-pip-version-check --no-cache-dir -r .ci/requirements-python2.txt
COPY .ci .ci
COPY entrypoint.sh entrypoint.sh
ENTRYPOINT ["sh", "/opt/audit/entrypoint.sh"]
