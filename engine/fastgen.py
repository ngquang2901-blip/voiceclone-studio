"""Faster OmniVoice decoding loop.

Adapted from omnivoice.models.omnivoice.OmniVoice._generate_iterative (k2-fsa/OmniVoice, Apache-2.0).
Change: the classifier-free-guidance ("uncond") rows only hold the target tokens, but upstream pads them to the
full conditional length (reference prompt + text + target) and runs them in the same forward. Here cond and uncond
run as two forwards, each padded only to its own longest row. Padded positions are masked out in both versions, so
the result is the same; the GPU just skips the padding (~30-40 % of the tokens with a 10 s reference).
Bound onto the model instance by core.tts_model(); re-check against upstream when upgrading omnivoice.
"""
import math

import torch

from omnivoice.models.omnivoice import _get_time_steps, _gumbel_sample


def _batch(rows, lens, device, pad_id, C):
    L = max(lens)
    ids = torch.full((len(rows), C, L), pad_id, dtype=torch.long, device=device)
    amask = torch.zeros((len(rows), L), dtype=torch.bool, device=device)
    att = torch.zeros((len(rows), 1, L, L), dtype=torch.bool, device=device)
    for i, ((x, m), n) in enumerate(zip(rows, lens)):
        ids[i, :, :n] = x; amask[i, :n] = m; att[i, :, :n, :n] = True
        if L > n:  # padded rows attend to themselves only (keeps softmax finite), as upstream does
            d = torch.arange(n, L, device=device); att[i, :, d, d] = True
    return ids, amask, att


def generate_iterative(self, task, gen_config):
    B, C = task.batch_size, self.config.num_audio_codebook
    inputs = [self._prepare_inference_inputs(task.texts[i], task.target_lens[i], task.ref_texts[i], task.ref_audio_tokens[i],
                                             task.langs[i], task.instructs[i], gen_config.denoise) for i in range(B)]
    c_lens = [inp["input_ids"].size(2) for inp in inputs]
    t_lens = list(task.target_lens)
    pad = self.config.audio_mask_id
    c_ids, c_am, c_att = _batch([(inp["input_ids"][0], inp["audio_mask"][0]) for inp in inputs], c_lens, self.device, pad, C)
    guided = gen_config.guidance_scale != 0
    if guided:
        u_ids, u_am, u_att = _batch([(inp["input_ids"][0][..., -n:], inp["audio_mask"][0][..., -n:]) for inp, n in zip(inputs, t_lens)],
                                    t_lens, self.device, pad, C)

    tokens = torch.full((B, C, max(t_lens)), pad, dtype=torch.long, device=self.device)
    timesteps = _get_time_steps(t_start=0.0, t_end=1.0, num_step=gen_config.num_step, t_shift=gen_config.t_shift).tolist()
    schedules = []
    for t_len in t_lens:
        total = t_len * C; rem = total; sched = []
        for step in range(gen_config.num_step):
            num = rem if step == gen_config.num_step - 1 else min(math.ceil(total * (timesteps[step + 1] - timesteps[step])), rem)
            sched.append(int(num)); rem -= int(num)
        schedules.append(sched)
    layer_ids = torch.arange(C, device=self.device).view(1, -1, 1)

    for step in range(gen_config.num_step):
        c_logits_all = self(input_ids=c_ids, audio_mask=c_am, attention_mask=c_att).logits.to(torch.float32)
        u_logits_all = self(input_ids=u_ids, audio_mask=u_am, attention_mask=u_att).logits.to(torch.float32) if guided else None
        for i in range(B):
            k = schedules[i][step]
            if k <= 0: continue
            c_len, t_len = c_lens[i], t_lens[i]
            c_logits = c_logits_all[i:i + 1, :, c_len - t_len:c_len, :]
            u_logits = u_logits_all[i:i + 1, :, :t_len, :] if guided else c_logits
            pred_tokens, scores = self._predict_tokens_with_scoring(c_logits, u_logits, gen_config)
            scores = scores - (layer_ids * gen_config.layer_penalty_factor)
            if gen_config.position_temperature > 0.0:
                scores = _gumbel_sample(scores, gen_config.position_temperature)
            sample = tokens[i:i + 1, :, :t_len]
            scores.masked_fill_(sample != pad, -float("inf"))
            _, topk = torch.topk(scores.flatten(), k)
            flat = sample.flatten(); flat[topk] = pred_tokens.flatten()[topk]; sample.copy_(flat.view_as(sample))
            tokens[i:i + 1, :, :t_len] = sample
            c_ids[i:i + 1, :, c_len - t_len:c_len] = sample
            if guided: u_ids[i:i + 1, :, :t_len] = sample
    return [tokens[i, :, :t_lens[i]] for i in range(B)]
