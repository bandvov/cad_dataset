# Base: an official PyTorch + CUDA devel image, matching the exact
# torch==2.6.0 triple pinned in requirements.txt (see that file's comment
# for why they must match -- an unmatched torch/torchvision pair is what
# produces "operator torchvision::nms does not exist"). Confirmed this tag
# exists on Docker Hub as of this writing; pin the CUDA minor version
# (12.4 here) to whatever your host driver actually supports -- check with
# `nvidia-smi` on the host before building -- and keep requirements.txt's
# torch/torchvision/torchaudio triple in sync if you change it.
FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-devel

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/root/.cache/huggingface

# build123d needs OCP (OpenCascade Python bindings), which pulls a fair
# amount of native/OCCT machinery via pip's manylinux wheel -- no extra
# system packages should be required, but if the wheel build fails on your
# platform you likely need OpenGL/X11 runtime libs (libgl1, libglu1-mesa)
# even for headless geometry kernel use.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        libgl1 \
        libglu1-mesa \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# training code
COPY train.py merge_adapter.py eval_geometry.py ./

# entrypoint left as a plain shell -- docker-compose.yml supplies the
# actual `command:` so you can override args at run time without rebuilding
ENTRYPOINT ["python"]
CMD ["train.py"]
