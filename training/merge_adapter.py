"""
merge_adapter.py
Merges a LoRA adapter (trained via train.py) into the base model weights,
producing a standalone model directory you can load with plain
AutoModelForCausalLM.from_pretrained() -- no peft/adapter dance needed at
inference time, and it's the form most downstream tools (vLLM, GGUF
conversion for Ollama/llama.cpp, etc.) expect.

Usage:
    python merge_adapter.py --base-model google/gemma-4-E4B-it \
        --adapter-dir /workspace/outputs/adapter \
        --output-dir /workspace/outputs/merged
"""

from __future__ import annotations
import argparse
import gc

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-model", required=True)
    ap.add_argument("--adapter-dir", required=True)
    ap.add_argument("--output-dir", required=True)
    args = ap.parse_args()

    print(f"loading base model {args.base_model}")
    base = AutoModelForCausalLM.from_pretrained(
        args.base_model, dtype=torch.bfloat16, device_map="cpu",
    )
    # Loaded from --base-model, NOT --adapter-dir, deliberately. The
    # adapter dir has a tokenizer re-saved by train.py's
    # tokenizer.save_pretrained(), and re-loading FROM that local save can
    # hit "Couldn't instantiate the backend tokenizer... You need to have
    # sentencepiece or tiktoken installed" even with sentencepiece already
    # installed -- transformers' slow-to-fast conversion path is sensitive
    # to sentencepiece/protobuf version combinations in ways that error
    # message doesn't actually diagnose. --base-model is the exact same
    # source train.py already loaded successfully in this same image
    # (that's how the run started), so loading the tokenizer from there
    # instead sidesteps the broken reconversion path entirely rather than
    # chasing a sentencepiece/protobuf pin. The content is identical
    # either way -- train.py's save didn't modify the tokenizer.
    tokenizer = AutoTokenizer.from_pretrained(args.base_model)

    print(f"loading adapter from {args.adapter_dir}")
    merged = PeftModel.from_pretrained(base, args.adapter_dir)

    print("merging (this can take a minute for larger models)")
    merged = merged.merge_and_unload()

    # RAM unload: `base`'s original weights are still referenced at this
    # point even though `merge_and_unload()` has folded them into `merged`
    # -- peft doesn't drop the base module's parameters for you. Explicitly
    # dropping the reference and forcing a GC pass here matters because
    # save_pretrained() below needs its own memory headroom for
    # serialization buffers while writing a full-precision (bf16) model,
    # and running that with a redundant duplicate of the weights still
    # live is the difference between fitting in RAM and swapping/OOMing on
    # a large model. No VRAM cleanup here -- this script loads to CPU only
    # (device_map="cpu" above), so there's nothing on the GPU to free.
    del base
    gc.collect()

    print(f"saving merged model to {args.output_dir}")
    merged.save_pretrained(args.output_dir, safe_serialization=True)
    tokenizer.save_pretrained(args.output_dir)
    print("done")


if __name__ == "__main__":
    main()
