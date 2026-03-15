#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Firebase 서비스 계정 키 정보로 serviceAccountKey.json 파일을 생성합니다.
로컬에서 set_storage_cors.py 등을 실행할 때 GOOGLE_APPLICATION_CREDENTIALS로 사용합니다.

사용법:
  1) 환경 변수에 JSON 문자열이 있을 때:
     set FIREBASE_CREDENTIALS_JSON={"type":"service_account","project_id":"..."}
     python scripts/write_service_account_key.py

  2) Firebase 콘솔에서 받은 JSON 파일이 있을 때:
     set FIREBASE_CREDENTIALS_JSON=<경로\다운로드한키.json 내용>
     python scripts/write_service_account_key.py

  3) .streamlit/secrets.toml 의 [firebase] 항목을 사용할 때:
     python scripts/write_service_account_key.py --from-secrets

생성된 파일: 프로젝트 루트의 serviceAccountKey.json (절대 Git에 커밋하지 마세요.)
"""
import argparse
import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_SCRIPT_DIR)
_OUTPUT_FILE = os.path.join(_ROOT, "serviceAccountKey.json")

# 서비스 계정 JSON에 필요한 키 (Firebase Admin SDK용)
_SA_KEYS = [
    "type", "project_id", "private_key_id", "private_key",
    "client_email", "client_id", "auth_uri", "token_uri",
    "auth_provider_x509_cert_url", "client_x509_cert_url", "universe_domain"
]


def _from_env():
    raw = os.environ.get("FIREBASE_CREDENTIALS_JSON")
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    # 파일 경로로 넣은 경우: 해당 파일 내용 읽기
    if os.path.isfile(raw):
        with open(raw, "r", encoding="utf-8") as f:
            return json.load(f)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _from_secrets_toml():
    secrets_path = os.path.join(_ROOT, ".streamlit", "secrets.toml")
    if not os.path.isfile(secrets_path):
        return None
    try:
        import tomli
    except ImportError:
        try:
            import tomllib
        except ImportError:
            return None
    with open(secrets_path, "rb") as f:
        if "tomli" in sys.modules:
            data = tomli.load(f)
        else:
            data = tomllib.load(f)
    firebase = data.get("firebase")
    if not firebase or not isinstance(firebase, dict):
        return None
    out = {}
    for k in _SA_KEYS:
        if k in firebase:
            v = firebase[k]
            if k == "private_key" and isinstance(v, str):
                v = v.replace("\\n", "\n")
            out[k] = v
    return out if out.get("project_id") and out.get("private_key") else None


def main():
    parser = argparse.ArgumentParser(description="serviceAccountKey.json 생성")
    parser.add_argument(
        "--from-secrets",
        action="store_true",
        help=".streamlit/secrets.toml 의 [firebase] 섹션에서 읽기 (toml/tomli 필요)",
    )
    parser.add_argument(
        "-o", "--output",
        default=_OUTPUT_FILE,
        help="출력 파일 경로 (기본: 프로젝트 루트/serviceAccountKey.json)",
    )
    args = parser.parse_args()

    if args.from_secrets:
        cfg = _from_secrets_toml()
        if not cfg:
            print(".streamlit/secrets.toml 에 [firebase] 항목을 찾을 수 없거나 tomli/tomllib를 사용할 수 없습니다.", file=sys.stderr)
            sys.exit(1)
    else:
        cfg = _from_env()
        if not cfg:
            print("FIREBASE_CREDENTIALS_JSON 환경 변수가 비어 있거나 유효한 JSON이 아닙니다.", file=sys.stderr)
            print("  예: set FIREBASE_CREDENTIALS_JSON={\"type\":\"service_account\",\"project_id\":\"...\"}", file=sys.stderr)
            print("  또는 Firebase 콘솔에서 받은 JSON 파일 경로: set FIREBASE_CREDENTIALS_JSON=C:\\path\\to\\key.json", file=sys.stderr)
            sys.exit(1)

    # 서비스 계정 JSON 형식에 맞게 키만 추림
    sa = {k: cfg[k] for k in _SA_KEYS if k in cfg}
    if not sa.get("project_id") or not sa.get("private_key"):
        print("project_id 또는 private_key가 없습니다. 서비스 계정 JSON을 확인하세요.", file=sys.stderr)
        sys.exit(1)

    out_path = os.path.abspath(args.output)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(sa, f, indent=2, ensure_ascii=False)
    print(f"생성됨: {out_path}")
    print("다음으로 CORS 스크립트 실행:")
    print(f"  set GOOGLE_APPLICATION_CREDENTIALS={out_path}")
    print("  set BUCKET_NAME=gluc-order-ai.appspot.com")
    print("  python scripts/set_storage_cors.py")


if __name__ == "__main__":
    main()
