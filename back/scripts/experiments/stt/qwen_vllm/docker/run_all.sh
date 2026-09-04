#!/usr/bin/env bash
# Run every streaming configuration back to back (one GPU).  Logs/JSON land in ../out/<tag>.{log,json}
set -u; cd "$(dirname "$0")"
while read -r model mode chunk util tag; do
  [ -z "${tag:-}" ] && continue
  echo "== $tag"; ./run.sh --model "$model" --mode "$mode" --chunk "$chunk" --gpu-util "$util" --tag "$tag" > "../out/$tag.log" 2>&1
  echo "EXIT $?" >> "../out/$tag.log"; grep -E "audio=|EXIT" "../out/$tag.log"
done <<'CFG'
Qwen/Qwen3-ASR-1.7B seg  1.0 0.85 17b_seg_c1
Qwen/Qwen3-ASR-1.7B full 2.0 0.85 17b_full_c2
Qwen/Qwen3-ASR-1.7B seg  0.5 0.85 17b_seg_c05
Qwen/Qwen3-ASR-0.6B seg  2.0 0.70 06b_seg_c2
Qwen/Qwen3-ASR-0.6B full 2.0 0.70 06b_full_c2
Qwen/Qwen3-ASR-1.7B full 1.0 0.85 17b_full_c1
CFG
echo ALLDONE
