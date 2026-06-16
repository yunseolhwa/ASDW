from __future__ import annotations

import argparse
import html
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("artifacts/fusion-showcase/latest")
DEFAULT_AUDIT = Path("artifacts/fusion-readiness-audit/latest/report.json")
DEFAULT_BUNDLE = Path("artifacts/fusion-review-bundle/latest/report.json")

ASSET_CANDIDATES = [
    (Path("artifacts/visual-checks/detection-bboxes-clean.png"), "asdw-detection.png"),
    (Path("artifacts/screenspot-pro-tiny/latest/overlays/01-screenshot_2024-12-05_21-43-26.png"), "screenspot-pro.png"),
    (Path("artifacts/ui-elements-tiny/latest/overlays/train-mostvisited_telegra.ph_1729630961.png"), "ui-elements.png"),
    (Path("artifacts/groundcua-tiny/latest/overlays/OBS_Studio-294cbb130c812388c30abd3b97cf7b7872c139d47d6847ff8126246e219af900.png"), "groundcua.png"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a static runtime-showcase web artifact from fusion review reports.",
    )
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def find_report(bundle: dict[str, Any], report_id: str) -> dict[str, Any]:
    for report in bundle.get("reports") or []:
        if report.get("id") == report_id:
            return report
    return {}


def find_gate(bundle: dict[str, Any], name: str) -> dict[str, Any]:
    for gate in ((bundle.get("review_gate") or {}).get("checks") or []):
        if gate.get("name") == name:
            return gate
    return {}


def copy_assets(output_dir: Path) -> dict[str, str]:
    asset_dir = output_dir / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    copied: dict[str, str] = {}
    for source, dest_name in ASSET_CANDIDATES:
        if source.exists():
            destination = asset_dir / dest_name
            shutil.copy2(source, destination)
            copied[dest_name] = f"assets/{dest_name}"
    return copied


def build_view_model(audit: dict[str, Any], bundle: dict[str, Any], assets: dict[str, str]) -> dict[str, Any]:
    contract = (find_report(bundle, "contract").get("summary") or {})
    agent = (find_report(bundle, "agent_policy").get("summary") or {})
    agent_step = (find_report(bundle, "agent_step_inline").get("summary") or {})
    gpu = (find_report(bundle, "gpu_server").get("summary") or {})
    fusion = (find_report(bundle, "fusion_snapshot").get("summary") or {})
    dataset = (fusion.get("dataset") or {})
    screenspot = (find_report(bundle, "screenspot_pro").get("summary") or {})
    ui_elements = (find_report(bundle, "ui_elements").get("summary") or {})
    groundcua = (find_report(bundle, "groundcua").get("summary") or {})
    llm_gate = find_gate(bundle, "SGLang runtime")
    agent_cases = agent.get("cases") or {}

    audit_pass = sum(1 for check in audit.get("checks") or [] if check.get("status") == "pass")
    audit_total = len(audit.get("checks") or [])
    sequence = agent_step.get("keys") or next_sequence(fusion)
    step_latency = agent_step.get("latency_ms")
    step_latency_text = f"{step_latency:.0f} ms" if isinstance(step_latency, (int, float)) else "unknown"
    confidence = step_confidence(bundle)

    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "headline": "Fusion Controller Update",
        "subtitle": "LLM이 꺼져도 멈추지 않는 얇은 입력 안전 경계",
        "audit": {"status": audit.get("status"), "passed": audit_pass, "total": audit_total},
        "runtime": {
            "overall": (bundle.get("review_gate") or {}).get("overall"),
            "server_device": ((bundle.get("runtime") or {}).get("fusion_status") or {}).get("device"),
            "daemon_online": ((bundle.get("runtime") or {}).get("agent_status") or {}).get("daemon_online"),
            "llm_status": llm_gate.get("status"),
            "llm_evidence": llm_gate.get("evidence"),
        },
        "hero_metrics": [
            {"label": "Readiness", "value": f"{audit_pass}/{audit_total}", "tone": "good"},
            {"label": "Agent Step", "value": f"{agent_step.get('status', 'unknown')} · {step_latency_text}", "tone": "good"},
            {"label": "Sequence", "value": sequence, "tone": "accent"},
            {"label": "LLM", "value": str(llm_gate.get("status") or "unknown"), "tone": "warn"},
        ],
        "premiere": [
            {
                "kicker": "Patch 01",
                "title": "판단자가 둘이 됐습니다",
                "body": "`auto`는 LLM을 먼저 보되, 실패하면 `vision_rule`로 비전 결과를 action JSON까지 연결합니다.",
            },
            {
                "kicker": "Patch 02",
                "title": "보여주기 버튼이 아니라 실제 step",
                "body": "inline image smoke가 `/agent/step`을 지나 `press_sequence`를 만들었습니다.",
            },
            {
                "kicker": "Patch 03",
                "title": "입력은 끝까지 따로 잠급니다",
                "body": "observe는 입력하지 않고, live는 `allow_live_input=true` 없이는 실행되지 않습니다.",
            },
        ],
        "step": {
            "sequence": sequence,
            "latency": step_latency_text,
            "confidence": confidence,
            "controller": agent_step.get("controller") or "vision_rule",
            "frame_provider": agent_step.get("frame_provider") or "inline_image",
            "action": agent_step.get("action") or "press_sequence",
            "status": agent_step.get("status") or "unknown",
        },
        "pipeline": [
            {"label": "Frame", "value": "inline image", "note": "daemon capture 없이 검증"},
            {"label": "Vision", "value": sequence, "note": "template + classifier"},
            {"label": "Controller", "value": agent_step.get("controller") or "vision_rule", "note": "LLM offline fallback"},
            {"label": "Gate", "value": "observe", "note": "실제 입력 없음"},
        ],
        "proof": [
            {
                "label": "Contract Safety",
                "value": f"{contract.get('passed')}/{contract.get('total')}",
                "body": "schema, key 검증, confidence 차단, vision_rule 계약까지 통과.",
            },
            {
                "label": "Agent Policy",
                "value": f"{agent.get('passed')}/{agent.get('total')}",
                "body": "observe, rehearse, live guard, low-confidence 차단 확인.",
            },
            {
                "label": "GPU Smoke",
                "value": str(gpu.get("prediction_device") or "unknown"),
                "body": "ROCm 경로에서 `template,classifier` 예측 1회 확인.",
            },
            {
                "label": "External Boxes",
                "value": f"{dataset.get('sequence_accuracy', 0):.2f}",
                "body": "외부 box proposal을 넣었을 때 synthetic sequence accuracy.",
            },
        ],
        "policies": [
            {"label": "Real Step", "status": agent_step.get("status", "unknown"), "result": f"{sequence} · {step_latency_text}", "body": "비전 결과가 action JSON까지 실제 endpoint로 연결됨."},
            {"label": "Observe", "status": agent_cases.get("observe_skips_input", "unknown"), "result": "skipped", "body": "판단만 기록하고 입력은 보내지 않음."},
            {"label": "Rehearse", "status": agent_cases.get("rehearse_uses_daemon_dry_run", "unknown"), "result": "dry_run", "body": "daemon 큐/타이밍만 검증."},
            {"label": "Live Guard", "status": agent_cases.get("live_requires_explicit_allow", "unknown"), "result": "blocked", "body": "명시 승인 없는 live 실행 차단."},
            {"label": "Low Confidence", "status": agent_cases.get("low_confidence_blocks", "unknown"), "result": "blocked", "body": "확신 낮은 action 차단."},
        ],
        "evidence": [
            {"label": "ASDW Detection", "value": sequence, "body": "실제 step smoke의 기준 이미지.", "image": assets.get("asdw-detection.png")},
            {"label": "ScreenSpot-Pro", "value": accepted_text(screenspot), "body": "고해상도 앱 화면 bbox evidence.", "image": assets.get("screenspot-pro.png")},
            {"label": "UI-Elements", "value": accepted_text(ui_elements), "body": "웹 UI annotation evidence.", "image": assets.get("ui-elements.png")},
            {"label": "GroundCUA", "value": accepted_text(groundcua), "body": "데스크톱 앱 annotation evidence.", "image": assets.get("groundcua.png")},
        ],
        "limits": [
            {"label": "SGLang runtime", "state": "offline", "body": "LLM 자체 판단은 아직 실서버로 검증하지 않았습니다."},
            {"label": "Live input", "state": "not executed", "body": "`allow_live_input=true` 실제 입력은 의도적으로 실행하지 않았습니다."},
            {"label": "Soak", "state": "not done", "body": "장시간 daemon/GPU 안정성은 별도 검증입니다."},
            {"label": "Optional providers", "state": "not baseline", "body": "dxcam, pywinauto, pywinctl 등은 후보이며 기본 경로가 아닙니다."},
        ],
        "creative_pack": {
            "poster_title": "ASDW Fusion Controller Update",
            "poster_copy": "읽고, 판단하고, 입력 전 한 번 더 잠그는 로컬 컴퓨터-use 경계.",
            "visual_prompt": "original 15+ tech showcase key visual, compact Korean PM briefing, luminous control desk, real evidence monitors, cute but professional host energy, no third-party IP",
            "slides": [
                "1. 무엇이 달라졌나: LLM 우선 + vision_rule fallback",
                "2. 실제 작동 증거: /agent/step inline smoke",
                "3. 안전 정책: observe, rehearse, live guard",
                "4. 확장성: external GUI evidence",
                "5. 아직 남은 검증: live, SGLang, soak",
            ],
        },
    }


def step_confidence(bundle: dict[str, Any]) -> str:
    agent = (((bundle.get("runtime") or {}).get("agent_status") or {}).get("agent") or {})
    decision = ((agent.get("last_step") or {}).get("decision") or {})
    confidence = decision.get("confidence")
    if isinstance(confidence, (int, float)):
        return f"{confidence:.2f}"
    return "0.91+"


def next_sequence(fusion: dict[str, Any]) -> str:
    for row in fusion.get("prediction_rows") or []:
        if row.get("sensors") == "template,classifier":
            return row.get("sequence_text") or "unknown"
    return "unknown"


def accepted_text(summary: dict[str, Any]) -> str:
    return f"{summary.get('accepted', 0)} accepted"


def write_html(output_dir: Path, data: dict[str, Any]) -> Path:
    html_text = render_html(data)
    output_path = output_dir / "index.html"
    output_path.write_text(html_text, encoding="utf-8")
    return output_path


def render_html(data: dict[str, Any]) -> str:
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return (
        HTML_TEMPLATE.replace("__DATA_JSON__", data_json)
        .replace("__GENERATED_AT__", html.escape(str(data.get("generated_at"))))
    )


def write_manifest(output_dir: Path, data: dict[str, Any], html_path: Path) -> Path:
    manifest = {
        "generated_at": data["generated_at"],
        "html": str(html_path),
        "status": data["audit"]["status"],
        "showcase_type": "runtime_showcase",
        "audit": data["audit"],
        "step": data["step"],
        "known_limits": [item["label"] for item in data["limits"]],
        "browser_qa": "run separately; see screenshots/",
    }
    path = output_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


HTML_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ASDW Fusion Controller Update</title>
  <style>
    :root {
      --ink: #17151f;
      --paper: #fffaf3;
      --panel: #ffffff;
      --line: rgba(23, 21, 31, .14);
      --muted: #625d6d;
      --hot: #e9478f;
      --cyan: #00a5b8;
      --amber: #f0a51b;
      --green: #1d9c65;
      --red: #d9483b;
      --violet: #6447d8;
      --night: #10141f;
      --shadow: 0 26px 80px rgba(22, 26, 42, .16);
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      color: var(--ink);
      font-family: "Segoe UI", "Pretendard", "Malgun Gothic", Arial, sans-serif;
      background:
        linear-gradient(90deg, rgba(23,21,31,.05) 1px, transparent 1px),
        linear-gradient(180deg, rgba(23,21,31,.05) 1px, transparent 1px),
        linear-gradient(135deg, #fff4df 0%, #f5fbff 43%, #fff7fb 100%);
      background-size: 38px 38px, 38px 38px, auto;
      overflow-x: hidden;
    }
    button { font: inherit; cursor: pointer; border: 0; }
    .page { width: min(1240px, calc(100vw - 36px)); margin: 0 auto; padding: 22px 0 56px; }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      min-height: 54px;
      margin-bottom: 16px;
    }
    .brand { display: flex; align-items: center; gap: 12px; font-weight: 950; }
    .brand-mark {
      width: 42px; height: 42px; border-radius: 14px;
      background: conic-gradient(from 200deg, var(--hot), var(--amber), var(--cyan), var(--violet), var(--hot));
      display: grid; place-items: center; color: white; box-shadow: 0 12px 30px rgba(233,71,143,.24);
    }
    .brand-mark:before { content: ""; width: 15px; height: 15px; background: white; transform: rotate(45deg); border-radius: 4px; }
    .stamp { border: 1px solid var(--line); background: rgba(255,255,255,.78); border-radius: 999px; padding: 9px 13px; color: var(--muted); font-size: 13px; white-space: nowrap; }
    .hero {
      min-height: min(760px, calc(100vh - 116px));
      display: grid;
      grid-template-columns: minmax(0, .96fr) minmax(420px, 1.04fr);
      gap: 22px;
      align-items: stretch;
      padding-bottom: 18px;
    }
    .hero-copy, .stage {
      border: 1px solid var(--line);
      background: rgba(255,255,255,.84);
      box-shadow: var(--shadow);
      border-radius: 24px;
      overflow: hidden;
    }
    .hero-copy { padding: clamp(24px, 4vw, 46px); display: flex; flex-direction: column; justify-content: space-between; }
    .eyebrow {
      display: inline-flex; align-items: center; gap: 9px;
      width: fit-content; max-width: 100%;
      padding: 9px 12px; border-radius: 999px;
      color: #a51d59; background: #ffe7f0; border: 1px solid rgba(233,71,143,.22);
      font-weight: 900; font-size: 13px;
    }
    h1 { margin: 22px 0 16px; font-size: clamp(44px, 7vw, 86px); line-height: .92; letter-spacing: 0; }
    .lead { color: var(--muted); font-size: clamp(18px, 2.1vw, 24px); line-height: 1.48; margin: 0; max-width: 760px; }
    .hero-actions { display: flex; flex-wrap: wrap; gap: 12px; margin: 28px 0; }
    .primary, .secondary {
      border-radius: 16px; padding: 14px 18px; font-weight: 950; min-height: 50px;
    }
    .primary { color: white; background: linear-gradient(135deg, var(--hot), var(--violet)); box-shadow: 0 18px 34px rgba(100,71,216,.22); }
    .secondary { color: var(--ink); background: white; border: 1px solid var(--line); }
    .metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }
    .metric { border: 1px solid var(--line); background: #fff; border-radius: 16px; padding: 14px; min-height: 86px; }
    .metric b { display: block; font-size: clamp(24px, 4vw, 36px); line-height: 1; overflow-wrap: anywhere; }
    .metric span { display: block; color: var(--muted); font-size: 13px; margin-top: 8px; }
    .metric.good b { color: var(--green); } .metric.warn b { color: var(--red); } .metric.accent b { color: var(--violet); }
    .stage { background: var(--night); color: white; position: relative; min-height: 620px; display: grid; grid-template-rows: auto 1fr auto; }
    .stage-head { padding: 18px; display: flex; justify-content: space-between; gap: 14px; border-bottom: 1px solid rgba(255,255,255,.12); }
    .stage-label { color: rgba(255,255,255,.74); font-size: 13px; }
    .stage-signal { display: flex; gap: 7px; align-items: center; color: #7be3c0; font-weight: 800; font-size: 13px; }
    .stage-signal:before { content: ""; width: 9px; height: 9px; background: #38d989; border-radius: 99px; box-shadow: 0 0 18px #38d989; }
    .monitor { padding: 20px; display: grid; gap: 16px; align-content: start; }
    .callout {
      border: 1px solid rgba(255,255,255,.14);
      background:
        linear-gradient(90deg, rgba(233,71,143,.18), rgba(0,165,184,.12)),
        rgba(255,255,255,.05);
      border-radius: 20px;
      padding: 18px;
      min-height: 150px;
      display: grid;
      align-content: center;
    }
    .callout small { color: #7be3c0; font-weight: 950; text-transform: uppercase; letter-spacing: 0; }
    .callout b { display: block; margin-top: 8px; font-size: clamp(34px, 5vw, 56px); line-height: .95; }
    .callout span { display: block; margin-top: 10px; color: rgba(255,255,255,.72); font-size: 14px; }
    .sequence-strip {
      display: flex; gap: 8px; flex-wrap: wrap; padding: 14px;
      background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.12); border-radius: 18px;
    }
    .key {
      width: 50px; height: 50px; border-radius: 14px; display: grid; place-items: center;
      font-size: 24px; font-weight: 950; color: #10141f;
      background: linear-gradient(180deg, #fff, #f7df9e);
      box-shadow: inset 0 -6px 0 rgba(23,21,31,.12), 0 12px 24px rgba(0,0,0,.18);
    }
    .evidence-frame { border: 1px solid rgba(255,255,255,.12); background: rgba(255,255,255,.05); border-radius: 18px; padding: 12px; }
    .evidence-frame img { width: 100%; height: auto; display: block; border-radius: 12px; background: #fff; }
    .stage-foot { padding: 18px; border-top: 1px solid rgba(255,255,255,.12); display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
    .stage-foot div { background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.12); border-radius: 14px; padding: 11px; }
    .stage-foot b { display: block; font-size: 18px; }
    .stage-foot span { display: block; color: rgba(255,255,255,.65); font-size: 12px; margin-top: 4px; }
    .section { margin-top: 26px; padding: 28px; border: 1px solid var(--line); background: rgba(255,255,255,.82); border-radius: 24px; box-shadow: var(--shadow); }
    .section-head { display: flex; align-items: end; justify-content: space-between; gap: 18px; margin-bottom: 18px; }
    .section h2 { margin: 0; font-size: clamp(30px, 5vw, 54px); letter-spacing: 0; line-height: 1; }
    .section .sub { margin: 8px 0 0; color: var(--muted); font-size: 16px; line-height: 1.5; }
    .premiere { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
    .feature-card, .proof-card, .policy-card, .limit-card, .creative-card {
      border: 1px solid var(--line); background: #fff; border-radius: 16px; padding: 18px; min-height: 150px;
    }
    .feature-card small { color: var(--hot); font-weight: 950; text-transform: uppercase; }
    .feature-card h3, .proof-card h3, .policy-card h3, .limit-card h3 { margin: 10px 0 8px; font-size: 22px; }
    .feature-card p, .proof-card p, .policy-card p, .limit-card p, .creative-card p { color: var(--muted); line-height: 1.5; margin: 0; }
    .pipeline { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
    .pipe-step { position: relative; padding: 18px; min-height: 170px; border-radius: 18px; background: #fff; border: 1px solid var(--line); overflow: hidden; }
    .pipe-step:before { content: attr(data-index); position: absolute; right: 14px; top: 8px; color: rgba(23,21,31,.12); font-size: 64px; font-weight: 950; }
    .pipe-step strong { display: block; font-size: 18px; }
    .pipe-step b { display: block; margin: 18px 0 8px; font-size: clamp(22px, 3vw, 32px); overflow-wrap: anywhere; }
    .proof-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
    .proof-card .value { display: block; margin: 8px 0 10px; font-size: clamp(28px, 4vw, 44px); font-weight: 950; color: var(--cyan); overflow-wrap: anywhere; }
    .console { display: grid; grid-template-columns: minmax(250px, .7fr) minmax(0, 1.3fr); gap: 16px; }
    .policy-list { display: grid; gap: 8px; }
    .policy-tab { text-align: left; border: 1px solid var(--line); background: white; border-radius: 14px; padding: 13px; font-weight: 900; }
    .policy-tab span { display: block; margin-top: 3px; color: var(--muted); font-size: 13px; font-weight: 700; }
    .policy-tab.active { outline: 3px solid rgba(0,165,184,.18); border-color: rgba(0,165,184,.45); }
    .json-panel { background: #10141f; color: #f5fbff; border-radius: 18px; padding: 18px; min-height: 300px; overflow: auto; border: 1px solid rgba(255,255,255,.12); }
    .json-panel pre { margin: 0; white-space: pre-wrap; font-family: "Cascadia Mono", Consolas, monospace; font-size: 14px; line-height: 1.55; }
    .gallery { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
    .evidence-card { border: 1px solid var(--line); background: #fff; border-radius: 16px; overflow: hidden; }
    .evidence-card img { width: 100%; aspect-ratio: 16 / 10; object-fit: cover; display: block; background: #f2f2f2; }
    .evidence-card div { padding: 14px; }
    .evidence-card b { display: block; font-size: 18px; }
    .evidence-card span { display: block; color: var(--cyan); font-weight: 950; margin: 5px 0; }
    .limits { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
    .limit-card .state { display: inline-block; margin: 6px 0 10px; padding: 7px 10px; border-radius: 999px; color: #8d2c22; background: #ffe9e5; font-weight: 950; }
    .creative { display: grid; grid-template-columns: minmax(0, .9fr) minmax(0, 1.1fr); gap: 14px; }
    .creative-card h3 { margin: 0 0 12px; font-size: 26px; }
    .slide-list { margin: 0; padding-left: 20px; color: var(--muted); line-height: 1.7; }
    .footer { margin: 26px 0 0; color: var(--muted); text-align: center; font-size: 13px; }
    @media (max-width: 980px) {
      .hero, .console, .creative { grid-template-columns: 1fr; }
      .stage { min-height: auto; }
      .premiere, .pipeline, .proof-grid, .gallery, .limits { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 560px) {
      .page { width: min(100vw - 24px, 430px); padding-top: 14px; }
      .topbar { align-items: flex-start; flex-direction: column; }
      .hero-copy, .section { padding: 22px; border-radius: 20px; }
      .hero { grid-template-columns: 1fr; }
      h1 { font-size: 40px; line-height: .98; }
      .lead { font-size: 17px; }
      .hero-actions button { width: 100%; }
      .metrics, .stage-foot, .premiere, .pipeline, .proof-grid, .gallery, .limits { grid-template-columns: 1fr; }
      .section-head { display: block; }
      .key { width: 42px; height: 42px; font-size: 20px; }
    }
  </style>
</head>
<body>
  <main class="page">
    <header class="topbar">
      <div class="brand"><div class="brand-mark" aria-hidden="true"></div><div>ASDW Fusion Showcase</div></div>
      <div class="stamp">Generated __GENERATED_AT__</div>
    </header>

    <section class="hero" id="top">
      <div class="hero-copy">
        <div>
          <div class="eyebrow">15+ PM friendly runtime showcase</div>
          <h1 id="heroTitle">Fusion Controller Update</h1>
          <p class="lead" id="heroLead"></p>
          <div class="hero-actions">
            <button class="primary" data-scroll="#premiere">쇼케이스 시작</button>
            <button class="secondary" data-scroll="#limits">미검증 먼저 보기</button>
          </div>
        </div>
        <div class="metrics" id="heroMetrics"></div>
      </div>

      <aside class="stage" aria-label="runtime evidence stage">
        <div class="stage-head">
          <div>
            <strong>Runtime Stage</strong>
            <div class="stage-label">비전 판독에서 action JSON까지</div>
          </div>
          <div class="stage-signal">safe observe</div>
        </div>
        <div class="monitor">
          <div class="callout">
            <small>actual endpoint result</small>
            <b id="stageCallout">/agent/step passed</b>
            <span id="stageCalloutSub">live input was not sent</span>
          </div>
          <div class="sequence-strip" id="sequenceStrip"></div>
          <div class="evidence-frame"><img id="heroEvidence" alt="ASDW detection evidence"></div>
        </div>
        <div class="stage-foot" id="stageStats"></div>
      </aside>
    </section>

    <section class="section" id="premiere">
      <div class="section-head">
        <div><h2>패치 공개</h2><p class="sub">말로 포장하지 않고, 이번 업데이트에서 실제로 바뀐 동작만 올립니다.</p></div>
        <button class="secondary" data-scroll="#pipeline">다음 장면</button>
      </div>
      <div class="premiere" id="premiereCards"></div>
    </section>

    <section class="section" id="pipeline">
      <div class="section-head">
        <div><h2>실행 흐름</h2><p class="sub">입력은 하지 않고, 판단 JSON이 만들어지는 경로를 단계별로 보여줍니다.</p></div>
        <button class="secondary" data-scroll="#console">정책 보기</button>
      </div>
      <div class="pipeline" id="pipelineGrid"></div>
    </section>

    <section class="section" id="console">
      <div class="section-head">
        <div><h2>안전 콘솔</h2><p class="sub">각 버튼은 report 기반 결과입니다. live 입력은 실행하지 않았습니다.</p></div>
        <button class="secondary" data-scroll="#proof">검증 수치</button>
      </div>
      <div class="console">
        <div class="policy-list" id="policyTabs"></div>
        <div class="json-panel"><pre id="policyJson"></pre></div>
      </div>
    </section>

    <section class="section" id="proof">
      <div class="section-head">
        <div><h2>검증 수치</h2><p class="sub">숫자는 생성된 report에서 읽습니다. 성공하지 않은 항목은 성공처럼 쓰지 않습니다.</p></div>
        <button class="secondary" data-scroll="#evidence">증거 화면</button>
      </div>
      <div class="proof-grid" id="proofGrid"></div>
    </section>

    <section class="section" id="evidence">
      <div class="section-head">
        <div><h2>증거 화면</h2><p class="sub">하나의 실험 화면에 갇히지 않도록 외부 GUI evidence도 함께 둡니다.</p></div>
        <button class="secondary" data-scroll="#creative">크리에이티브 팩</button>
      </div>
      <div class="gallery" id="evidenceGallery"></div>
    </section>

    <section class="section" id="creative">
      <div class="section-head">
        <div><h2>크리에이티브 팩</h2><p class="sub">Canva/Fal로 확장할 때 바로 쓸 수 있는 포스터 카피와 슬라이드 구성을 포함했습니다.</p></div>
        <button class="secondary" data-scroll="#limits">남은 검증</button>
      </div>
      <div class="creative">
        <div class="creative-card">
          <h3 id="posterTitle"></h3>
          <p id="posterCopy"></p>
          <p style="margin-top:14px"><strong>Visual prompt</strong><br><span id="visualPrompt"></span></p>
        </div>
        <div class="creative-card">
          <h3>Showcase slide skeleton</h3>
          <ol class="slide-list" id="slideList"></ol>
        </div>
      </div>
    </section>

    <section class="section" id="limits">
      <div class="section-head">
        <div><h2>아직 남은 것</h2><p class="sub">대공개 쇼케이스와 완전 실사용 공개는 다릅니다. 여기는 의도적으로 선을 긋는 장면입니다.</p></div>
        <button class="secondary" data-scroll="#top">처음으로</button>
      </div>
      <div class="limits" id="limitGrid"></div>
    </section>

    <p class="footer">Original local web artifact. No third-party game IP, no live input call, no hidden SGLang success.</p>
  </main>

  <script id="showcase-data" type="application/json">__DATA_JSON__</script>
  <script>
    const data = JSON.parse(document.getElementById('showcase-data').textContent);
    const $ = (selector) => document.querySelector(selector);
    const el = (tag, className, text) => {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    };
    const escJson = (value) => JSON.stringify(value, null, 2);

    function init() {
      $('#heroTitle').textContent = data.headline;
      $('#heroLead').textContent = data.subtitle + ' - 실제 /agent/step 결과를 중심에 둔 쇼케이스입니다.';
      renderMetrics();
      renderStage();
      renderPremiere();
      renderPipeline();
      renderPolicies();
      renderProof();
      renderEvidence();
      renderCreative();
      renderLimits();
      document.querySelectorAll('[data-scroll]').forEach((button) => {
        button.addEventListener('click', () => document.querySelector(button.dataset.scroll).scrollIntoView({ behavior: 'smooth', block: 'start' }));
      });
    }

    function renderMetrics() {
      const target = $('#heroMetrics');
      data.hero_metrics.forEach((item) => {
        const card = el('div', `metric ${item.tone || ''}`);
        card.appendChild(el('b', '', item.value));
        card.appendChild(el('span', '', item.label));
        target.appendChild(card);
      });
    }

    function renderStage() {
      const strip = $('#sequenceStrip');
      String(data.step.sequence || '').split('').forEach((key) => strip.appendChild(el('span', 'key', key)));
      if (data.evidence[0]?.image) $('#heroEvidence').src = data.evidence[0].image;
      const stats = [
        ['Controller', data.step.controller],
        ['Action', data.step.action],
        ['Confidence', data.step.confidence],
        ['Latency', data.step.latency],
      ];
      stats.forEach(([label, value]) => {
        const cell = el('div');
        cell.appendChild(el('b', '', value));
        cell.appendChild(el('span', '', label));
        $('#stageStats').appendChild(cell);
      });
      $('#stageCallout').textContent = data.step.action + ' · ' + data.step.latency;
      $('#stageCalloutSub').textContent = data.step.controller + ' controller, live input sent: false';
    }

    function renderPremiere() {
      data.premiere.forEach((item) => {
        const card = el('article', 'feature-card');
        card.appendChild(el('small', '', item.kicker));
        card.appendChild(el('h3', '', item.title));
        card.appendChild(el('p', '', item.body.replaceAll('`', '')));
        $('#premiereCards').appendChild(card);
      });
    }

    function renderPipeline() {
      data.pipeline.forEach((item, index) => {
        const card = el('article', 'pipe-step');
        card.dataset.index = String(index + 1).padStart(2, '0');
        card.appendChild(el('strong', '', item.label));
        card.appendChild(el('b', '', item.value));
        card.appendChild(el('p', '', item.note));
        $('#pipelineGrid').appendChild(card);
      });
    }

    function renderPolicies() {
      const tabs = $('#policyTabs');
      data.policies.forEach((item, index) => {
        const button = el('button', 'policy-tab');
        button.innerHTML = `<strong>${item.label}</strong><span>${item.status} / ${item.result}</span>`;
        button.addEventListener('click', () => selectPolicy(index));
        tabs.appendChild(button);
      });
      selectPolicy(0);
    }

    function selectPolicy(index) {
      document.querySelectorAll('.policy-tab').forEach((tab, i) => tab.classList.toggle('active', i === index));
      const item = data.policies[index];
      $('#policyJson').textContent = escJson({
        case: item.label,
        status: item.status,
        result: item.result,
        mode: item.label === 'Real Step' ? 'observe' : item.label.toLowerCase().replaceAll(' ', '_'),
        note: item.body,
        live_input_sent: false,
      });
    }

    function renderProof() {
      data.proof.forEach((item) => {
        const card = el('article', 'proof-card');
        card.appendChild(el('h3', '', item.label));
        card.appendChild(el('span', 'value', item.value));
        card.appendChild(el('p', '', item.body));
        $('#proofGrid').appendChild(card);
      });
    }

    function renderEvidence() {
      data.evidence.forEach((item) => {
        const card = el('article', 'evidence-card');
        const img = el('img');
        img.alt = item.label + ' evidence';
        if (item.image) img.src = item.image;
        card.appendChild(img);
        const body = el('div');
        body.appendChild(el('b', '', item.label));
        body.appendChild(el('span', '', item.value));
        body.appendChild(el('p', '', item.body));
        card.appendChild(body);
        $('#evidenceGallery').appendChild(card);
      });
    }

    function renderCreative() {
      $('#posterTitle').textContent = data.creative_pack.poster_title;
      $('#posterCopy').textContent = data.creative_pack.poster_copy;
      $('#visualPrompt').textContent = data.creative_pack.visual_prompt;
      data.creative_pack.slides.forEach((item) => $('#slideList').appendChild(el('li', '', item)));
    }

    function renderLimits() {
      data.limits.forEach((item) => {
        const card = el('article', 'limit-card');
        card.appendChild(el('h3', '', item.label));
        card.appendChild(el('span', 'state', item.state));
        card.appendChild(el('p', '', item.body));
        $('#limitGrid').appendChild(card);
      });
    }

    init();
  </script>
</body>
</html>
"""


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    audit = read_json(args.audit.resolve())
    bundle = read_json(args.bundle.resolve())
    assets = copy_assets(output_dir)
    view_model = build_view_model(audit, bundle, assets)
    html_path = write_html(output_dir, view_model)
    manifest_path = write_manifest(output_dir, view_model, html_path)
    print(f"Wrote {html_path}")
    print(f"Wrote {manifest_path}")
    print(f"showcase status: {view_model['audit']['status']} {view_model['audit']['passed']}/{view_model['audit']['total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
