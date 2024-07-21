FROM ubuntu:24.04

RUN rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get install -qy curl git build-essential

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get install -qy cmake

# RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
#     apt-get install -qy gcovr

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get install -qy python3-venv
RUN python3 -mvenv --upgrade-deps /tmp/venv
ENV PATH=/tmp/venv/bin:$PATH VIRTUAL_ENV=/tmp/venv
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install gcovr

WORKDIR /ayab
CMD ["/ayab/test/test.sh"]