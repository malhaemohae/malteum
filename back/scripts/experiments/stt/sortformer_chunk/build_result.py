"""out_<N>s.json 들을 모아 RESULT.md 표를 만든다.

실행: <scratch>/diar/.venv/bin/python build_result.py
"""
import itertools
import json

SCENARIOS = ["preset-dep-a", "preset-loan-b"]
CHUNK_CANDIDATES_S = [15, 5, 2, 1]


def line_accuracy(line_results, pred_key):
    """1:1 매핑(teller/customer <-> speaker_i)을 찾아 맞은 줄 수를 센다."""
    spks = sorted({r[pred_key] for r in line_results if r[pred_key] is not None})
    best_n, best_map = -1, (None, None)
    candidates = spks + [None] * max(0, 2 - len(spks))
    for t, c in itertools.permutations(candidates, 2) if len(candidates) >= 2 else [(None, None)]:
        n = sum(
            1
            for r in line_results
            if r[pred_key] is not None and ((r["gt_speaker"] == "teller" and r[pred_key] == t) or (r["gt_speaker"] == "customer" and r[pred_key] == c))
        )
        if n > best_n:
            best_n, best_map = n, (t, c)
    return best_n, len(line_results), best_map, len(spks)


def main():
    rows = []
    for chunk_s in CHUNK_CANDIDATES_S:
        data = json.load(open(f"out_{chunk_s}s.json"))
        row = {"requested_chunk_s": chunk_s}
        dt_all, delay_all = [], []
        final_acc, online_acc, n_spk = {}, {}, {}
        reversals_total = 0
        for scenario in SCENARIOS:
            res = data[scenario]
            row["actual_chunk_s"] = res["actual_chunk_s"]
            dts = [c["dt_s"] for c in res["chunk_records"]]
            dt_all += dts
            delays = [l["delay_s"] for l in res["line_results"] if l["delay_s"] is not None]
            delay_all += delays
            reversals_total += sum(l["reversals"] for l in res["line_results"])

            n_final, n_total, _, n_spk_final = line_accuracy(res["line_results"], "final_pred")
            n_online, _, _, _ = line_accuracy(res["line_results"], "first_pred")
            final_acc[scenario] = (n_final, n_total)
            online_acc[scenario] = (n_online, n_total)
            n_spk[scenario] = n_spk_final

        row["dt_mean"] = sum(dt_all) / len(dt_all)
        row["dt_max"] = max(dt_all)
        row["rtf"] = row["dt_mean"] / row["actual_chunk_s"]
        row["delay_mean"] = sum(delay_all) / len(delay_all) if delay_all else None
        row["delay_max"] = max(delay_all) if delay_all else None
        row["final_acc"] = final_acc
        row["online_acc"] = online_acc
        row["n_spk"] = n_spk
        row["reversals_total"] = reversals_total
        row["peak_rss_mb"] = data.get("peak_rss_mb_so_far")
        rows.append(row)

    lines = []
    lines.append("| 청크(요청/실제) | 처리시간 평균/최대(s) | 실시간비율 | 라벨지연 평균/최대(s) | 최종정확도 dep-a | 최종정확도 loan-b | 온라인정확도 dep-a | 온라인정확도 loan-b | 되돌림 | 예측화자수 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        fa_d = f"{r['final_acc']['preset-dep-a'][0]}/{r['final_acc']['preset-dep-a'][1]}"
        fa_l = f"{r['final_acc']['preset-loan-b'][0]}/{r['final_acc']['preset-loan-b'][1]}"
        oa_d = f"{r['online_acc']['preset-dep-a'][0]}/{r['online_acc']['preset-dep-a'][1]}"
        oa_l = f"{r['online_acc']['preset-loan-b'][0]}/{r['online_acc']['preset-loan-b'][1]}"
        nspk = f"{r['n_spk']['preset-dep-a']},{r['n_spk']['preset-loan-b']}"
        lines.append(
            f"| {r['requested_chunk_s']}s / {r['actual_chunk_s']:.2f}s "
            f"| {r['dt_mean']:.3f} / {r['dt_max']:.3f} "
            f"| {r['rtf']:.3f} "
            f"| {r['delay_mean']:.2f} / {r['delay_max']:.2f} "
            f"| {fa_d} | {fa_l} | {oa_d} | {oa_l} "
            f"| {r['reversals_total']} | {nspk} |"
        )

    print("\n".join(lines))
    peak = max(r["peak_rss_mb"] for r in rows if r["peak_rss_mb"])
    print(f"\n피크 RSS(전체 스윕 중 최댓값): {peak:.0f} MB")

    json.dump(rows, open("table_rows.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
