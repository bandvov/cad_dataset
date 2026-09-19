"""
chat_format.py
Single source of truth for how instructions/IR get rendered into chat
turns -- imported by BOTH build_dataset.py (training data) and
inference/generator.py (serving). Keeping this in one shared module is
what guarantees the model sees the same turn phrasing at inference time
that it was trained on. Two separate ad-hoc implementations of "how do I
word a repair turn" is exactly the kind of silent train/serve skew that's
easy to introduce by accident (this project already had one real example
of that class of bug -- the "model" vs "assistant" role-name mismatch
between the dataset and the tokenizer's chat template).
"""

from __future__ import annotations
import json


def render_generate_user_turn(instruction: str) -> str:
    return instruction


def render_regenerate_user_turn(base_ir: dict, instruction: str) -> str:
    return f"Here is the current part:\n{json.dumps(base_ir)}\n\n{instruction}"


def render_repair_user_turn(broken_ir: dict, error: str, instruction: str | None = None) -> str:
    instruction = instruction or "This part fails to build. Diagnose and fix it."
    return (
        f"{instruction}\n\n"
        f"Broken feature tree:\n{json.dumps(broken_ir)}\n\n"
        f"Error: {error}"
    )


def render_append_user_turn(base_ir: dict, instruction: str) -> str:
    """Patch-mode edit turn: asks for only the NEW feature(s) to add,
    not the whole tree -- see orchestrator.generate_append_stream() /
    patch.apply_patch(). Untrained framing as of this writing (no
    gen_patch.py yet, see README's flywheel/dataset notes) -- quality
    depends on how well the existing model generalizes to the narrower
    instruction; revisit this wording once real append-mode data exists
    to fine-tune against."""
    return (
        f"Here is the current part:\n{json.dumps(base_ir)}\n\n"
        f"{instruction}\n\n"
        f"Respond with ONLY a JSON array of the NEW feature object(s) to "
        f"add -- do not repeat any existing feature, do not return the "
        f"whole tree. Each new feature needs a unique 'id' not already "
        f"used above."
    )
