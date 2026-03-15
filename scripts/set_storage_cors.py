#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Firebase Storage 버킷 CORS 설정 스크립트.
google-cloud-storage로 버킷 CORS를 업데이트합니다.

사용법:
  환경 변수로 Firebase 인증 정보 설정 후:
    python scripts/set_storage_cors.py
  또는
    python -m scripts.set_storage_cors

필요 환경 변수: FIREBASE_CREDENTIALS_JSON (전체 JSON 문자열) 또는
  FIREBASE_PROJECT_ID, FIREBASE_PRIVATE_KEY, FIREBASE_CLIENT_EMAIL 등 개별 키.
  (선택) BUCKET_NAME 미설정 시 project_id.appspot.com 사용.
"""
import json
import os
import sys

# 프로젝트 루트를 path에 추가
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_SCRIPT_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Allowed Origins: ["*"] 또는 Railway 앱 URL
CORS_ORIGINS = ["*"]
# 또는 특정 도메인만: ["https://gluc-order-ai-production.up.railway.app"]

CORS_METHODS = ["GET", "HEAD", "PUT", "POST", "DELETE"]
CORS_RESPONSE_HEADERS = ["Content-Type", "Content-Length", "Accept", "Authorization"]
CORS_MAX_AGE_SECONDS = 3600


def _get_firebase_config():
    """환경 변수에서 Firebase(서비스 계정) 설정 로드."""
    cfg = {}
    cred_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")
    if cred_json:
        try:
            cfg.update(json.loads(cred_json))
            return cfg
        except Exception as e:
            print(f"[경고] FIREBASE_CREDENTIALS_JSON 파싱 실패: {e}", file=sys.stderr)
    keys = [
        "type", "project_id", "private_key_id", "private_key",
        "client_email", "client_id", "auth_uri", "token_uri",
        "auth_provider_x509_cert_url", "client_x509_cert_url", "universe_domain"
    ]
    for key in keys:
        env_key = "FIREBASE_" + key.upper()
        val = os.environ.get(env_key)
        if val and key == "private_key":
            val = val.replace("\\n", "\n")
        if val:
            cfg[key] = val
    return cfg


def update_bucket_cors(
    bucket_name: str,
    origins: list[str] | None = None,
    methods: list[str] | None = None,
    response_headers: list[str] | None = None,
    max_age_seconds: int = 3600,
    credentials_dict: dict | None = None,
):
    """
    Google Cloud Storage 버킷의 CORS 설정을 업데이트합니다.

    :param bucket_name: 버킷 이름 (예: gluc-order-ai.appspot.com)
    :param origins: 허용 Origin 목록 (예: ["*"] 또는 ["https://gluc-order-ai-production.up.railway.app"])
    :param methods: 허용 메서드 (예: ["GET", "HEAD", "PUT", "POST", "DELETE"])
    :param response_headers: 노출할 응답 헤더
    :param max_age_seconds: preflight 캐시 시간
    :param credentials_dict: 서비스 계정 정보 딕셔너리 (없으면 환경 변수/ADC 사용)
    :return: True 성공, False 실패
    """
    try:
        from google.cloud import storage
        from google.oauth2 import service_account
    except ImportError:
        print("google-cloud-storage가 필요합니다: pip install google-cloud-storage", file=sys.stderr)
        return False

    origins = origins or CORS_ORIGINS
    methods = methods or CORS_METHODS
    response_headers = response_headers or CORS_RESPONSE_HEADERS

    if credentials_dict and credentials_dict.get("project_id"):
        project = credentials_dict["project_id"]
        creds = service_account.Credentials.from_service_account_info(credentials_dict)
        client = storage.Client(project=project, credentials=creds)
    else:
        client = storage.Client()

    bucket = client.bucket(bucket_name)
    cors_config = [
        {
            "origin": origins,
            "method": methods,
            "responseHeader": response_headers,
            "maxAgeSeconds": max_age_seconds,
        }
    ]
    bucket.cors = cors_config
    bucket.patch()
    print(f"버킷 gs://{bucket_name} CORS 설정이 적용되었습니다.")
    print(f"  origins: {origins}")
    print(f"  methods: {methods}")
    return True


def main():
    cfg = _get_firebase_config()
    project_id = (cfg.get("project_id") if cfg else None) or os.environ.get("GOOGLE_CLOUD_PROJECT")
    bucket_name = os.environ.get("BUCKET_NAME")
    if bucket_name:
        pass
    elif project_id:
        bucket_name = f"{project_id}.appspot.com"
    else:
        print("Firebase 설정을 찾을 수 없습니다.", file=sys.stderr)
        print("  방법 1: FIREBASE_CREDENTIALS_JSON (전체 JSON 문자열) 또는", file=sys.stderr)
        print("  방법 2: FIREBASE_PROJECT_ID + FIREBASE_PRIVATE_KEY + FIREBASE_CLIENT_EMAIL 등", file=sys.stderr)
        print("  방법 3: BUCKET_NAME=버킷이름 + GOOGLE_APPLICATION_CREDENTIALS=서비스계정키.json 경로", file=sys.stderr)
        sys.exit(1)

    if not project_id and cfg:
        project_id = cfg.get("project_id")
    if not project_id:
        project_id = "(ADC 또는 GOOGLE_APPLICATION_CREDENTIALS 사용)"
    print(f"버킷: gs://{bucket_name} (project: {project_id})")

    ok = update_bucket_cors(
        bucket_name=bucket_name,
        origins=CORS_ORIGINS,
        methods=CORS_METHODS,
        response_headers=CORS_RESPONSE_HEADERS,
        max_age_seconds=CORS_MAX_AGE_SECONDS,
        credentials_dict=cfg if (cfg and cfg.get("private_key")) else None,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
