FROM ghcr.io/nvidia-ai-blueprints/vss/vss-rt-vlm@sha256:23f844c9715e2d98ac01260b085fd1f9c7523d748dd594995c4ec952b7f4f65d
USER root
ENV DEBIAN_FRONTEND=noninteractive LD_PRELOAD="" NVIDIA_VISIBLE_DEVICES=void NVIDIA_DRIVER_CAPABILITIES="" BASH_ENV="" ENV=""
COPY dev-bundle/ /opt/vios-dev-bundle/
COPY verify-bundle.py /opt/verify-bundle.py
RUN python3 /opt/verify-bundle.py /opt/vios-dev-bundle \
    && printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d \
    && chmod 755 /usr/sbin/policy-rc.d \
    && dpkg --unpack /opt/vios-dev-bundle/*.deb \
    && dpkg --configure -a \
    && ldconfig \
    && rm -rf /opt/vios-dev-bundle
COPY build-native.sh /opt/build-native.sh
WORKDIR /build
ENTRYPOINT ["/bin/bash", "/opt/build-native.sh"]
