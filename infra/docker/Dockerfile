# Start with a clean, small Ubuntu image
FROM ubuntu:22.04

# Prevent interactive prompts during apt install
ENV DEBIAN_FRONTEND=noninteractive

# 1. Install System Dependencies (Git, CMake, Python, QEMU)
# We install qemu-system-arm directly from Ubuntu repositories (It's smaller and works great)
RUN apt-get update && apt-get install -y \
    git \
    cmake \
    ninja-build \
    gperf \
    ccache \
    dfu-util \
    device-tree-compiler \
    wget \
    python3-dev \
    python3-pip \
    python3-setuptools \
    python3-tk \
    python3-wheel \
    xz-utils \
    file \
    make \
    gcc \
    gcc-multilib \
    g++-multilib \
    libsdl2-dev \
    libmagic1 \
    qemu-system-arm \
    && rm -rf /var/lib/apt/lists/*

# 2. Install the Zephyr SDK (Minimal Bundle)
# We only install the ARM toolchain to save 20GB+ of space.
ARG ZSDK_VERSION=0.17.4
WORKDIR /opt/toolchains
RUN wget -q "https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v${ZSDK_VERSION}/zephyr-sdk-${ZSDK_VERSION}_linux-x86_64_minimal.tar.xz" \
    && tar xf zephyr-sdk-${ZSDK_VERSION}_linux-x86_64_minimal.tar.xz \
    && zephyr-sdk-${ZSDK_VERSION}/setup.sh -t arm-zephyr-eabi -h -c \
    && rm zephyr-sdk-${ZSDK_VERSION}_linux-x86_64_minimal.tar.xz

# Set SDK Environment Variables
ENV ZEPHYR_TOOLCHAIN_VARIANT=zephyr
ENV ZEPHYR_SDK_INSTALL_DIR=/opt/toolchains/zephyr-sdk-${ZSDK_VERSION}
# Add ARM Compiler to PATH
ENV PATH="${ZEPHYR_SDK_INSTALL_DIR}/arm-zephyr-eabi/bin:${PATH}"

# 3. Install Nordic Command Line Tools (nrfjprog)
WORKDIR /tmp
RUN wget -qO - https://nsscprodmedia.blob.core.windows.net/prod/software-and-other-downloads/desktop-software/nrf-command-line-tools/sw/versions-10-x-x/10-24-0/nrf-command-line-tools_10.24.0_amd64.deb > nrf-tools.deb \
    && dpkg -i nrf-tools.deb \
    && rm nrf-tools.deb

# 4. Initialize West and Install Python Requirements for NCS v3.1.1
WORKDIR /workdir
RUN pip3 install west \
    && west init -m https://github.com/nrfconnect/sdk-nrf --mr v3.1.1 \
    && west update --narrow -o=--depth=1 \
    && pip3 install -r zephyr/scripts/requirements.txt \
    && pip3 install -r nrf/scripts/requirements.txt \
    && pip3 install -r bootloader/mcuboot/scripts/requirements.txt \
    # Cleanup source code to keep image small
    && rm -rf /workdir/*

# 5. Final Environment Setup
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8