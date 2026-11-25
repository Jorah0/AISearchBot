"""Model lab training worker (pass 59, section E). Runs ONLY inside HOME/train-env, started by labtrain.start as
`python -I labtrain_worker.py <job.json>`; it never imports lodestar (train-env does not have it) and imports torch and
the Hugging Face stack inside functions, so the app can import this module without them.

job.json: {id, kind probe|scratch|lora|export, spec, hyper, dataset_path, dataset_sha, expected_params, progress,
pause, cancel, out_dir}. Every mode appends JSON lines {step, loss, tokens, tok_per_s, vram_peak_gib, status, msg}
to `progress`; the last line's status is running, done, failed, paused or cancelled. It prints no secrets (its
environment has none: labtrain.worker_env strips them).

Modes:
- probe: LlamaConfig from spec, LlamaForCausalLM(config), param count == expected_params, save, reload; with
  hyper.converter (llama.cpp convert_hf_to_gguf.py) also a GGUF.
- scratch: tokenizer (BPE trained on spec.corpus, or a pinned spec.tokenizer ref), seed, init hash, causal-LM
  pretraining (AdamW 3e-4, betas 0.9/0.95, wd 0.1, clip 1.0, 2% warmup then cosine), padding masked, stop on a
  non-finite loss, checkpoints (model, optimizer, scheduler, RNG, data offset) at step boundaries, resume only from
  the same lineage, stop at spec.tokens_budget.
- lora: QLoRA SFT (peft + trl SFTTrainer) on spec.base with the dataset JSONL of chat "messages"; saves the adapter.
- export: merge spec.adapter into spec.base (or take spec.model), llama.cpp convert + quantize when hyper.converter /
  hyper.quantize are set, Modelfile, `ollama create hyper.tag`."""
import hashlib
import json
import math
import os
import random
import subprocess
import sys
import time
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Job:
    def __init__(self, path):
        self.d = json.loads(Path(path).read_text(encoding="utf-8"))
        self.spec, self.hyper = self.d.get("spec") or {}, self.d.get("hyper") or {}
        self.out = Path(self.d["out_dir"])
        self.out.mkdir(parents=True, exist_ok=True)

    def emit(self, status="running", step=0, loss=None, tokens=0, tok_per_s=None, msg=""):
        row = {"step": step, "loss": loss, "tokens": tokens, "tok_per_s": tok_per_s, "vram_peak_gib": vram_peak(),
               "status": status, "msg": msg, "at": time.time()}
        with open(self.d["progress"], "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        print(json.dumps(row), flush=True)

    def flag(self, name):
        return Path(self.d[name]).exists()


def vram_peak():
    torch = sys.modules.get("torch")
    if torch is None or not torch.cuda.is_available():
        return None
    return round(torch.cuda.max_memory_allocated() / 2 ** 30, 2)


def run(cmd):
    """A helper program (llama.cpp, ollama): no console window; (exit code, last lines of output)."""
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, creationflags=NO_WINDOW)
    return p.returncode, "\n".join((p.stdout + p.stderr).strip().splitlines()[-5:])


def llama_config(spec):
    from transformers import LlamaConfig

    return LlamaConfig(vocab_size=spec["vocab"], hidden_size=spec["hidden"], intermediate_size=spec["mlp"],
                       num_hidden_layers=spec["layers"], num_attention_heads=spec["heads"],
                       num_key_value_heads=spec["kv_heads"], head_dim=spec["head_dim"],
                       max_position_embeddings=spec["context"], tie_word_embeddings=spec.get("tied", True),
                       attention_bias=False, mlp_bias=False, pad_token_id=0, bos_token_id=1, eos_token_id=2)


def count(model):
    return sum(p.numel() for p in model.parameters())  # tied weights are one Parameter, counted once


def init_hash(model):
    h = hashlib.sha256()
    for name, t in sorted(model.state_dict().items()):
        h.update(name.encode())
        h.update(t.detach().cpu().contiguous().view(-1).view(__import__("torch").uint8).numpy().tobytes())
    return h.hexdigest()


def gguf(job, hf_dir, name):
    """llama.cpp's converter (+ quantize) when configured; returns the GGUF path or None."""
    conv = job.hyper.get("converter")
    if not conv:
        return None
    f16 = job.out / f"{name}-f16.gguf"
    code, tail = run([sys.executable, conv, hf_dir, "--outfile", f16, "--outtype", "f16"])
    if code:
        raise RuntimeError(f"convert_hf_to_gguf failed: {tail}")
    quant = job.hyper.get("quantize")
    if not quant:
        return f16
    q = job.out / f"{name}-{job.hyper.get('quant', 'Q4_K_M')}.gguf"
    code, tail = run([quant, f16, q, job.hyper.get("quant", "Q4_K_M")])
    if code:
        raise RuntimeError(f"llama-quantize failed: {tail}")
    return q


def probe(job):
    import torch
    from transformers import AutoModelForCausalLM, LlamaForCausalLM

    torch.manual_seed(job.spec.get("seed", 0))
    model = LlamaForCausalLM(llama_config(job.spec))
    n = count(model)
    if n != job.d.get("expected_params"):
        return job.emit("failed", msg=f"parameter count {n:,} != planned {job.d.get('expected_params'):,}")
    hf = job.out / "hf"
    model.save_pretrained(hf)
    back = AutoModelForCausalLM.from_pretrained(hf)
    if count(back) != n:
        return job.emit("failed", msg="the saved model does not load back with the same size")
    msg = f"built {n:,} params, init {init_hash(model)[:12]}, saved and reloaded"
    try:
        path = gguf(job, hf, "probe")
        msg += f"; GGUF {path.name}" if path else "; no converter configured (GGUF step skipped)"
    except RuntimeError as e:
        return job.emit("failed", msg=f"{msg}; {e}")
    job.emit("done", msg=msg)


# ---- scratch pretraining ----

def corpus_files(spec):
    src = spec.get("corpus") or []
    paths = [Path(p) for p in ([src] if isinstance(src, str) else src)]
    files = [f for p in paths for f in (sorted(p.rglob("*.txt")) + sorted(p.rglob("*.jsonl")) if p.is_dir() else [p])]
    if not files:
        raise RuntimeError("no corpus files")
    return files


def tokenizer_for(job, files):
    from transformers import AutoTokenizer, PreTrainedTokenizerFast

    ref = job.spec.get("tokenizer", "new")
    saved = job.out / "tokenizer"
    if (saved / "tokenizer.json").exists():
        return PreTrainedTokenizerFast.from_pretrained(saved)  # a resumed run keeps its tokenizer
    if ref != "new":
        tok = AutoTokenizer.from_pretrained(ref, revision=job.spec.get("tokenizer_revision"))
    else:
        from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers

        t = Tokenizer(models.BPE(unk_token="<unk>"))
        t.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
        t.decoder = decoders.ByteLevel()
        t.train([str(f) for f in files], trainers.BpeTrainer(
            vocab_size=job.spec["vocab"], special_tokens=["<pad>", "<s>", "</s>", "<unk>"],
            initial_alphabet=pre_tokenizers.ByteLevel.alphabet()))
        tok = PreTrainedTokenizerFast(tokenizer_object=t, pad_token="<pad>", bos_token="<s>", eos_token="</s>",
                                      unk_token="<unk>")
    if len(tok) > job.spec["vocab"]:
        raise RuntimeError(f"tokenizer has {len(tok)} tokens, the design's vocab is {job.spec['vocab']}")
    tok.save_pretrained(saved)
    return tok


def token_stream(job, tok, files):
    import torch

    cache = job.out / "tokens.pt"
    if cache.exists():
        return torch.load(cache, weights_only=True)
    ids = []
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        if f.suffix == ".jsonl":
            text = "\n".join(json.loads(line).get("text", "") for line in text.splitlines() if line.strip())
        ids.extend(tok(text)["input_ids"] + [tok.eos_token_id])
    stream = torch.tensor(ids, dtype=torch.int32)
    torch.save(stream, cache)
    return stream


def batch(stream, offset, seq, mb, pad_id):
    """mb blocks of seq tokens from block `offset` on (wrapping); a short last block is padded and its padding masked."""
    import torch

    blocks = max(1, math.ceil(len(stream) / seq))
    x = torch.full((mb, seq), pad_id, dtype=torch.long)
    mask = torch.zeros((mb, seq), dtype=torch.long)
    for i in range(mb):
        b = (offset + i) % blocks
        chunk = stream[b * seq:(b + 1) * seq].long()
        x[i, :len(chunk)] = chunk
        mask[i, :len(chunk)] = 1
    labels = x.masked_fill(mask == 0, -100)
    return x, mask, labels


def lr_lambda(total, warmup):
    w = max(1, int(total * warmup))

    def f(step):
        if step < w:
            return (step + 1) / w
        return 0.5 * (1 + math.cos(math.pi * min(1.0, (step - w) / max(1, total - w))))
    return f


def scratch(job):
    import torch
    from transformers import LlamaForCausalLM

    h, spec = job.hyper, job.spec
    seq, mb, accum = h.get("seq", spec["context"]), h["microbatch"], h["accum"]
    seed = spec.get("seed", 0)
    random.seed(seed)
    torch.manual_seed(seed)
    files = corpus_files(spec)
    tok = tokenizer_for(job, files)
    stream = token_stream(job, tok, files)
    model = LlamaForCausalLM(llama_config(spec))
    n = count(model)
    if n != job.d.get("expected_params"):
        return job.emit("failed", msg=f"parameter count {n:,} != planned {job.d.get('expected_params'):,}")
    lineage = {"init": init_hash(model), "plan": hashlib.sha256(json.dumps(
        {k: job.d.get(k) for k in ("kind", "spec", "hyper", "dataset_sha", "expected_params")}, sort_keys=True).encode()
    ).hexdigest()}
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(dev)
    decay = [p for p in model.parameters() if p.dim() >= 2]
    rest = [p for p in model.parameters() if p.dim() < 2]
    opt = torch.optim.AdamW([{"params": decay, "weight_decay": h["wd"]}, {"params": rest, "weight_decay": 0.0}],
                            lr=h["lr"], betas=tuple(h["betas"]))
    per = seq * mb * accum
    total = math.ceil(int(spec.get("tokens_budget") or per) / per)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lr_lambda(total, h["warmup"]))
    step, offset = 0, 0
    ckpt = job.out / "ckpt" / "state.pt"
    if ckpt.exists():
        state = torch.load(ckpt, weights_only=True)  # tensors, numbers, tuples: no pickled objects
        if state["lineage"] != lineage:
            return job.emit("failed", msg="the checkpoint belongs to another lineage (different init or plan)")
        model.load_state_dict(state["model"])
        opt.load_state_dict(state["opt"])
        sched.load_state_dict(state["sched"])
        random.setstate(state["rng"]["py"])
        torch.set_rng_state(state["rng"]["torch"])
        if dev == "cuda" and state["rng"].get("cuda") is not None:
            torch.cuda.set_rng_state_all(state["rng"]["cuda"])
        step, offset = state["step"], state["offset"]
        job.emit(step=step, tokens=step * per, msg=f"resumed at update {step}")
    else:
        job.emit(msg=f"init {lineage['init'][:12]}, {n:,} params, {total} updates of {per} tokens")

    def save():
        ckpt.parent.mkdir(parents=True, exist_ok=True)
        rng = {"py": random.getstate(), "torch": torch.get_rng_state(),
               "cuda": torch.cuda.get_rng_state_all() if dev == "cuda" else None}
        torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "sched": sched.state_dict(), "rng": rng,
                    "step": step, "offset": offset, "lineage": lineage}, str(ckpt) + ".tmp")
        os.replace(str(ckpt) + ".tmp", ckpt)

    model.train()
    t0, tokens0 = time.time(), step * per
    while step < total:
        if job.flag("cancel"):
            return job.emit("cancelled", step=step, tokens=step * per, msg="cancelled")
        if job.flag("pause"):
            save()
            return job.emit("paused", step=step, tokens=step * per, msg="checkpoint saved")
        loss_sum = 0.0
        for _ in range(accum):
            x, mask, labels = (t.to(dev) for t in batch(stream, offset, seq, mb, tok.pad_token_id))
            offset += mb
            with torch.autocast(dev, dtype=torch.bfloat16, enabled=dev == "cuda"):
                loss = model(input_ids=x, attention_mask=mask, labels=labels).loss / accum
            if not torch.isfinite(loss):
                return job.emit("failed", step=step, tokens=step * per, msg="non-finite loss; stopped (no checkpoint)")
            loss.backward()
            loss_sum += loss.item()
        torch.nn.utils.clip_grad_norm_(model.parameters(), h["clip"])
        opt.step()
        sched.step()
        opt.zero_grad(set_to_none=True)
        step += 1
        if step % h.get("ckpt_every", 200) == 0:
            save()
        if step % h.get("log_every", 10) == 0 or step == total:
            done = step * per - tokens0
            job.emit(step=step, loss=round(loss_sum, 4), tokens=step * per,
                     tok_per_s=round(done / max(1e-6, time.time() - t0)))
    save()
    model.save_pretrained(job.out / "model")
    tok.save_pretrained(job.out / "model")
    job.emit("done", step=step, tokens=step * per, msg=f"token budget reached; model in {job.out / 'model'}")


# ---- QLoRA SFT ----

def lora(job):
    import torch
    from datasets import load_dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainerCallback
    from trl import SFTConfig, SFTTrainer

    h, base = job.hyper, job.spec.get("base") or job.spec["variant_id"]  # a Hugging Face id or a local folder
    rev = job.spec.get("revision")
    tok = AutoTokenizer.from_pretrained(base, revision=rev)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(base, revision=rev, quantization_config=quant, device_map={"": 0},
                                                 dtype=torch.bfloat16)
    data = load_dataset("json", data_files=job.d["dataset_path"], split="train")
    args = SFTConfig(output_dir=str(job.out / "trainer"), num_train_epochs=h["epochs"], learning_rate=h["lr"],
                     warmup_ratio=h["warmup"], lr_scheduler_type="cosine", per_device_train_batch_size=h["microbatch"],
                     gradient_accumulation_steps=h["accum"], gradient_checkpointing=h["grad_ckpt"],
                     max_length=h["seq"], bf16=True, logging_steps=1, save_strategy="no", report_to="none",
                     seed=h.get("seed", 0))
    peft_cfg = LoraConfig(r=h["rank"], lora_alpha=h["alpha"], lora_dropout=h["dropout"], target_modules="all-linear",
                          task_type="CAUSAL_LM")
    state = {"t0": time.time(), "end": None}
    per = h["seq"] * h["microbatch"] * h["accum"]

    class Progress(TrainerCallback):
        def on_log(self, args, st, control, logs=None, **kw):
            loss = (logs or {}).get("loss")
            if loss is not None and not math.isfinite(loss):
                state["end"] = ("failed", "non-finite loss; stopped")
                control.should_training_stop = True
            elif loss is not None:
                job.emit(step=st.global_step, loss=round(loss, 4), tokens=st.global_step * per,
                         tok_per_s=round(st.global_step * per / max(1e-6, time.time() - state["t0"])))

        def on_step_end(self, args, st, control, **kw):
            if job.flag("cancel"):
                state["end"] = ("cancelled", "cancelled")
                control.should_training_stop = True
            elif job.flag("pause"):
                state["end"] = ("paused", "checkpoint saved")
                control.should_save = control.should_training_stop = True

    trainer = SFTTrainer(model=model, args=args, train_dataset=data, peft_config=peft_cfg, processing_class=tok,
                         callbacks=[Progress()])
    resume = any((job.out / "trainer").glob("checkpoint-*"))
    trainer.train(resume_from_checkpoint=True if resume else None)
    if state["end"]:
        return job.emit(state["end"][0], step=trainer.state.global_step, msg=state["end"][1])
    trainer.model.save_pretrained(job.out / "adapter")
    tok.save_pretrained(job.out / "adapter")
    job.emit("done", step=trainer.state.global_step, tokens=trainer.state.global_step * per,
             msg=f"adapter in {job.out / 'adapter'}")


# ---- export ----

def export(job):
    import torch

    h, spec = job.hyper, job.spec
    if spec.get("model"):
        merged = Path(spec["model"])  # a scratch model: nothing to merge
    else:
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        dtype = torch.float16 if h.get("dtype") == "fp16" else torch.bfloat16
        base = AutoModelForCausalLM.from_pretrained(spec["base"], revision=spec.get("revision"), dtype=dtype)
        model = PeftModel.from_pretrained(base, spec["adapter"]).merge_and_unload()
        merged = job.out / "merged"
        model.save_pretrained(merged)
        AutoTokenizer.from_pretrained(spec["adapter"]).save_pretrained(merged)
        job.emit(msg=f"merged into {merged}")
    try:
        path = gguf(job, merged, "model")
    except RuntimeError as e:
        return job.emit("failed", msg=str(e))
    if not path:
        return job.emit("done", msg=f"merged model in {merged}; no converter configured (GGUF and Ollama skipped)")
    modelfile = job.out / "Modelfile"
    modelfile.write_text(f"FROM {path}\nPARAMETER num_ctx {int(h['num_ctx'])}\n"
                         f"PARAMETER temperature {float(h['temperature'])}\n", encoding="utf-8")
    tag = h.get("tag")
    if not tag:
        return job.emit("done", msg=f"{path.name} and a Modelfile written; no tag, so not added to Ollama")
    code, tail = run([h.get("ollama", "ollama"), "create", tag, "-f", modelfile])
    if code:
        return job.emit("failed", msg=f"ollama create failed: {tail}")
    job.emit("done", msg=f"ollama model {tag} created from {path.name}")


MODES = {"probe": probe, "scratch": scratch, "lora": lora, "export": export}


def main(argv):
    job = Job(argv[1])
    try:
        MODES[job.d["kind"]](job)
    except Exception as e:  # the app reads the last line; the full traceback goes to the job log
        import traceback

        traceback.print_exc()
        job.emit("failed", msg=f"{type(e).__name__}: {str(e)[:300]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
