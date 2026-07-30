# 1. Define the version at the top
ARG PYTHON_VERSION="3.13"
ARG DEBIAN_VERSION="bookworm"

# Use a Python base image that matches the desired Python version
# We use a slim Debian-based image for smaller size.
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_VERSION}
ARG PYTHON_VERSION

LABEL maintainer="Lee Johnson <ljohnson@dettonville.org>"
LABEL description="Custom CocoIndex Container for Python ${PYTHON_VERSION}"

ARG BUILD_DATE
ARG BUILD_ID=devel
LABEL build=$BUILD_ID

# Set environment variables
ENV container=docker
ENV DEBIAN_FRONTEND=noninteractive

# Establish system workspace and cache targets
ENV APP_BIN_DIR=/usr/local/bin \
    WORKSPACE_DIR=/app \
    CACHE_DIR=/cache \
    HOME=/cache \
    XDG_CONFIG_HOME=/cache/.config \
    XDG_CACHE_HOME=/cache/.cache \
    XDG_DATA_HOME=/cache/.local/share \
    TZ=Etc/UTC \
    VIRTUAL_ENV=/opt/venv

ENV PATH="${VIRTUAL_ENV}/bin:${APP_BIN_DIR}:${PATH}"

# === System Dependencies ===
RUN apt-get update -qqy && \
    apt-get -qqy --no-install-recommends install \
      apt-transport-https ca-certificates curl wget git git-lfs \
      bash tar zip unzip \
      locales tzdata netbase \
      tree less nano jq rsync \
      dnsutils iproute2 iputils-ping inetutils-telnet && \
    sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && \
    locale-gen && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

## Ensure the following are set after running `locale-gen`
ENV LANGUAGE=en_US:en \
    LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8

#==========
# PIP - Install Python dependencies
#==========

# Create venv
RUN python3 -m venv $VIRTUAL_ENV

# Upgrade core tools
RUN pip install --no-cache-dir --upgrade pip wheel setuptools

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 1. Bake the production daemon file into the image workspace
COPY run-cocoindex.py ${APP_BIN_DIR}/run-cocoindex
RUN chmod +x ${APP_BIN_DIR}/run-cocoindex

# Create working directory
WORKDIR ${WORKSPACE_DIR}

# 2. Provision the decoupled caching matrix
RUN mkdir -p ${CACHE_DIR}/.config ${CACHE_DIR}/.local ${CACHE_DIR}/.cache

CMD ["python", "run-cocoindex"]
