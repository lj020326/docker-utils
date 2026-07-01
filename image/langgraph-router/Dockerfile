# 1. Define the version at the top
ARG PYTHON_VERSION="3.13"
ARG DEBIAN_VERSION="bookworm"

# Use a Python base image that matches the desired Python version
# We use a slim Debian-based image for smaller size.
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_VERSION}
ARG PYTHON_VERSION

LABEL maintainer="Lee Johnson <ljohnson@dettonville.org>"
LABEL description="Custom Langgraph Container for Python ${PYTHON_VERSION}"

ARG BUILD_DATE
ARG BUILD_ID=devel
LABEL build=$BUILD_ID

# Set environment variables
ENV container=docker
ENV DEBIAN_FRONTEND=noninteractive

ENV HOME=/app

ENV TZ=Etc/UTC

## 1. Core System Utilities & Locales
# These rarely change and provide the base for everything else
RUN apt-get update -qqy && \
    apt-get -qqy --no-install-recommends install \
      apt-transport-https apt-utils ca-certificates \
      bash tar zip unzip xorriso \
      curl wget git git-lfs \
      locales tzdata netbase \
      software-properties-common \
      tree less nano jq rsync && \
    sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && \
    locale-gen && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

## 2. Networking & Debugging Tools
RUN apt-get update -qqy && \
    apt-get -qqy --no-install-recommends install \
      dnsutils iproute2 iputils-ping inetutils-telnet \
      openssh-client ssh-askpass sshpass \
      gpg gpg-agent gnupg2 \
      ldap-utils \
      shellcheck groff rlwrap && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

## Ensure the following are set after running `locale-gen`
ENV LANGUAGE=en_US:en
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

#==========
# PIP - Install Python dependencies
#==========

COPY requirements.txt .

ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Upgrade core tools
RUN pip install --no-cache-dir --upgrade pip wheel setuptools

# Install requirements.txt first
RUN pip install --no-cache-dir -r requirements.txt

# Ensure non-root runtime environments can cleanly access and utilize the venv fully
RUN chmod -R 755 /opt/venv

#COPY entrypoint.sh /opt/bin/entrypoint.sh
#COPY functions.sh /opt/bin/functions.sh
#RUN chmod +x /opt/bin/entrypoint.sh \
#  && chmod +x /opt/bin/functions.sh

# COPY entrypoint.sh /opt/bin/entrypoint.sh
# RUN chmod +x /opt/bin/entrypoint.sh

# Create a working directory
WORKDIR /app

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
