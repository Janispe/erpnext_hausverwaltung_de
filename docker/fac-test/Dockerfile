ARG BASE_IMAGE=hvp:16
FROM ${BASE_IMAGE}
USER frappe
WORKDIR /home/frappe/frappe-bench
# FAC 2.5.1, pinned to the reviewed release commit, independent of moving branches.
RUN git clone https://github.com/buildswithpaul/Frappe_Assistant_Core.git apps/frappe_assistant_core \
    && cd apps/frappe_assistant_core \
    && git checkout 7ddc433772f4ade794d9f5ee30b7d9ea0af2a487 \
    && cd ../.. \
    && ./env/bin/pip install -e apps/frappe_assistant_core \
    && bench build --app frappe_assistant_core
