# -*- coding: utf-8 -*-
"""Firestore/Storage helper functions for meal persistence."""

import io
import json
import os
import re
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, storage
from google.cloud.firestore import Query
from PIL import Image


def _get_secret(key, default=None):
    v = os.environ.get(key)
    if v:
        return v
    try:
        return getattr(st.secrets, "get", lambda k, d=None: d)(key, default)
    except Exception:
        return default


def _get_firebase_config():
    try:
        if getattr(st.secrets, "get", None) and st.secrets.get("firebase"):
            return st.secrets["firebase"]
    except Exception:
        pass
    cfg = {"api_key": os.environ.get("FIREBASE_API_KEY", "")}
    cred_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")
    if cred_json:
        try:
            parsed = json.loads(cred_json)
            if isinstance(parsed.get("private_key"), str):
                parsed["private_key"] = parsed["private_key"].replace("\\n", "\n")
            cfg.update(parsed)
        except Exception:
            pass
    else:
        keys = [
            "type",
            "project_id",
            "private_key_id",
            "private_key",
            "client_email",
            "client_id",
            "auth_uri",
            "token_uri",
            "auth_provider_x509_cert_url",
            "client_x509_cert_url",
            "universe_domain",
        ]
        for key in keys:
            val = os.environ.get("FIREBASE_" + key.upper())
            if val and key == "private_key":
                val = val.replace("\\n", "\n")
            if val:
                cfg[key] = val
    return cfg


def _normalize_image_url(path, bucket_name):
    """저장값이 이미 절대 URL이면 그대로 두고, 상대 경로만 GCS 공개 URL로 만든다."""
    if not path:
        return ""
    s = str(path).strip()
    if s.startswith("http://") or s.startswith("https://"):
        return s
    if s.startswith("data:image"):
        return s
    if not bucket_name:
        return s
    path_encoded = urllib.parse.quote(s, safe="/")
    return f"https://storage.googleapis.com/{bucket_name}/{path_encoded}"


def _init_firebase():
    if firebase_admin._apps:
        return
    key_dict = _get_firebase_config()
    if not key_dict.get("project_id") or not key_dict.get("private_key"):
        raise RuntimeError("Firebase Admin credentials not configured.")
    cred = credentials.Certificate(key_dict)
    opts = {}
    bucket = os.environ.get("FIREBASE_STORAGE_BUCKET") or os.environ.get("STORAGE_BUCKET")
    if bucket:
        opts["storageBucket"] = bucket
    elif key_dict.get("project_id"):
        opts["storageBucket"] = f"{key_dict['project_id']}.appspot.com"
    firebase_admin.initialize_app(cred, opts)


def _compress_for_storage(img, max_width=800, quality=85):
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    w, h = img.size
    if w > max_width:
        ratio = max_width / float(w)
        nh = max(1, int(h * ratio))
        img = img.resize((max_width, nh), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def upload_image_to_storage(uid, meal_id, pil_image, max_width=800, quality=85):
    _init_firebase()
    if pil_image is None:
        return None
    img_bytes = _compress_for_storage(pil_image, max_width=max_width, quality=quality)
    bucket = storage.bucket()
    uid_safe = str(uid).replace("/", "_").replace("\\", "_")
    path = f"users/{uid_safe}/meals/{meal_id}.jpg"
    blob = bucket.blob(path)
    blob.upload_from_string(img_bytes, content_type="image/jpeg")
    image_url = None
    try:
        image_url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(days=365),
            method="GET",
        )
    except Exception as e:
        sys.stderr.write(f"[upload_image_to_storage] signed URL 생성 실패, 공개 URL로 대체: {e}\n")
    if not (image_url and str(image_url).strip().startswith("http")):
        try:
            blob.make_public()
        except Exception:
            pass
        image_url = getattr(blob, "public_url", None) or ""
        if not (image_url and str(image_url).strip().startswith("http")):
            image_url = _normalize_image_url(path, bucket.name)
    return image_url


def sanitize_for_firestore(data):
    """Firestore에 저장하기 전, 중첩 배열(Nested Arrays)을 찾아 쉼표 문자열로 평탄화하는 재귀 함수"""
    if isinstance(data, dict):
        return {k: sanitize_for_firestore(v) for k, v in data.items()}
    elif isinstance(data, list):
        sanitized_list = []
        for item in data:
            if isinstance(item, list):
                sanitized_list.append(", ".join(str(x) for x in item))
            elif isinstance(item, dict):
                sanitized_list.append(sanitize_for_firestore(item))
            else:
                sanitized_list.append(item)
        return sanitized_list
    else:
        return data


def save_meal_and_summary(uid, date_key, meal_data):
    _init_firebase()
    db = firestore.client()
    meal_ref = db.collection("users").document(str(uid)).collection("meals").document()
    summary_ref = db.collection("users").document(str(uid)).collection("daily_summaries").document(str(date_key))

    data = sanitize_for_firestore(dict(meal_data or {}))
    data["created_at"] = firestore.SERVER_TIMESTAMP
    data["date_key"] = str(date_key)
    data["meal_id"] = meal_ref.id

    total_carbs = int(data.get("total_carbs", 0) or 0)
    total_protein = int(data.get("total_protein", 0) or 0)
    total_fat = int(data.get("total_fat", 0) or 0)
    estimated_spike = int(data.get("estimated_spike", 0) or 0)

    summary_payload = {
        "date_key": str(date_key),
        "updated_at": firestore.SERVER_TIMESTAMP,
        "total_carbs": firestore.Increment(total_carbs),
        "total_protein": firestore.Increment(total_protein),
        "total_fat": firestore.Increment(total_fat),
        "spike_sum": firestore.Increment(estimated_spike),
        "meal_count": firestore.Increment(1),
    }
    safe_summary_data = sanitize_for_firestore(summary_payload)

    batch = db.batch()
    batch.set(meal_ref, data, merge=True)
    batch.set(summary_ref, safe_summary_data, merge=True)
    batch.commit()
    return meal_ref.id


def _blob_paths_for_meal_image(uid, doc_id, data, bucket_name):
    """삭제 시 시도할 Storage 객체 경로 목록(중복 제거)."""
    uid_safe = str(uid).replace("/", "_").replace("\\", "_")
    paths = []
    image_url = (data or {}).get("image_url") or ""
    if image_url and isinstance(image_url, str) and image_url.strip():
        u = image_url.strip()
        base = f"https://storage.googleapis.com/{bucket_name}/"
        if u.startswith(base):
            paths.append(urllib.parse.unquote(u[len(base) :]))
        else:
            m = re.match(r"https://storage\.googleapis\.com/([^/]+)/(.+)", u)
            if m and m.group(1) == bucket_name:
                paths.append(urllib.parse.unquote(m.group(2)))
    paths.append(f"users/{uid_safe}/meals/{doc_id}.jpg")
    mid = (data or {}).get("meal_id")
    if mid and str(mid) != str(doc_id):
        paths.append(f"users/{uid_safe}/meals/{mid}.jpg")
    seen = set()
    out = []
    for p in paths:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def get_meal_feed(uid, limit=5, start_after_doc=None, sort_field=None):
    """
    users/{uid}/meals 피드 최신순.
    - 첫 페이지(sort_field None, start_after None): created_at → saved_at_utc → __name__ 순으로 시도.
      (구문서에 created_at이 없으면 첫 쿼리가 0건이 될 수 있어 폴백 필요.)
    - 다음 페이지: 반드시 첫 응답에서 쓴 sort_field를 동일하게 넘겨야 start_after가 유효함.
    반환: (문서 dict 리스트, 마지막 DocumentSnapshot 또는 None, 사용한 정렬 필드명 또는 None)
    start_after_doc: DocumentSnapshot 또는 이전 페이지 마지막 문서 ID(str).
    """
    _init_firebase()
    db = firestore.client()
    col = db.collection("users").document(str(uid)).collection("meals")
    uid_str = str(uid)

    def _resolve_snap():
        if start_after_doc is None:
            return None
        if hasattr(start_after_doc, "reference") and getattr(start_after_doc, "exists", False):
            return start_after_doc
        snap = col.document(str(start_after_doc)).get()
        if snap is not None and getattr(snap, "exists", False):
            return snap
        if isinstance(start_after_doc, str):
            sys.stderr.write(f"[get_meal_feed] 커서 문서 없음 id={start_after_doc!r}\n")
            print(f"[get_meal_feed] 커서 문서 없음 id={start_after_doc!r}", flush=True)
        return "missing"

    snap = _resolve_snap()
    if snap == "missing":
        return [], None, None

    def _stream_for_field(field):
        q = col.order_by(field, direction=Query.DESCENDING)
        if snap is not None:
            q = q.start_after(snap)
        return list(q.limit(limit).stream())

    if start_after_doc is not None and not sort_field:
        err = "[get_meal_feed] 페이지네이션에는 첫 페이지에서 확정한 sort_field가 필요합니다."
        sys.stderr.write(err + "\n")
        print(err, flush=True)
        return [], None, None
    if sort_field:
        fields_to_try = [sort_field]
    else:
        fields_to_try = ["created_at", "saved_at_utc", "__name__"]

    docs = []
    used_field = None
    for field in fields_to_try:
        try:
            docs = _stream_for_field(field)
        except Exception as e:
            msg = f"[get_meal_feed] uid={uid_str!r} order_by({field!r}) error: {e}"
            sys.stderr.write(msg + "\n")
            print(msg, flush=True)
            docs = []
        sample_ids = [d.id for d in docs[:3]]
        print(
            f"[get_meal_feed] uid={uid_str!r} field={field!r} start_after={start_after_doc!r} "
            f"n_docs={len(docs)} sample_ids={sample_ids}",
            flush=True,
        )
        if docs:
            used_field = field
            break
        if sort_field:
            break
        if start_after_doc is not None and field == fields_to_try[-1]:
            break

    if not docs and start_after_doc is None:
        try:
            probe = list(col.limit(3).stream())
            pids = [d.id for d in probe]
            print(f"[get_meal_feed] unordered_probe n={len(probe)} ids={pids}", flush=True)
            for d in probe:
                raw = d.to_dict() or {}
                print(
                    f"[get_meal_feed] doc {d.id!r} keys has created_at={('created_at' in raw)} "
                    f"has saved_at_utc={('saved_at_utc' in raw)}",
                    flush=True,
                )
        except Exception as e:
            print(f"[get_meal_feed] unordered_probe failed: {e}", flush=True)
    bucket_name = None
    try:
        bucket_name = storage.bucket().name
    except Exception:
        pass
    loaded = []
    for d in docs:
        data = d.to_dict() or {}
        raw_url = data.get("image_url")
        image_url = _normalize_image_url(raw_url, bucket_name) if raw_url else None
        items = data.get("sorted_items", [])
        if items and isinstance(items, list) and isinstance(items[0], dict):
            sorted_lists = [
                [
                    item.get("name", ""),
                    item.get("gi", 0),
                    item.get("carbs", 0),
                    item.get("protein", 0),
                    item.get("color", ""),
                ]
                for item in items
            ]
        else:
            sorted_lists = items
        loaded.append(
            {
                "doc_id": d.id,
                "date": data.get("date", ""),
                "created_at": data.get("created_at"),
                "saved_at_utc": data.get("saved_at_utc"),
                "image": None,
                "image_url": image_url,
                "sorted_items": sorted_lists,
                "advice": data.get("advice", ""),
                "blood_sugar_score": int(data.get("blood_sugar_score", 0) or 0),
                "total_carbs": int(data.get("total_carbs", 0) or 0),
                "total_protein": int(data.get("total_protein", 0) or 0),
                "total_fat": int(data.get("total_fat", 0) or 0),
                "total_kcal": int(data.get("total_kcal", 0) or 0),
                "avg_gi": int(data.get("avg_gi", 0) or 0),
                "estimated_spike": int(data.get("estimated_spike", 0) or 0),
            }
        )
    last_snap = docs[-1] if docs else None
    return loaded, last_snap, used_field


def delete_meal_record(uid, doc_id):
    """
    meals 문서 삭제 + 일일 요약 역산 + Storage 이미지 정리.
    성공 시 (True, None), 실패 시 (False, 단계 문자열).
    """
    if not uid or not doc_id:
        return False, "uid/doc_id"
    _init_firebase()
    db = firestore.client()
    bucket = storage.bucket()
    bucket_name = bucket.name
    ref = db.collection("users").document(str(uid)).collection("meals").document(str(doc_id))
    snap = ref.get()
    if not snap.exists:
        return False, "not_found"
    data = snap.to_dict() or {}
    date_key = str(data.get("date_key") or "")
    total_carbs = int(data.get("total_carbs", 0) or 0)
    total_protein = int(data.get("total_protein", 0) or 0)
    total_fat = int(data.get("total_fat", 0) or 0)
    estimated_spike = int(data.get("estimated_spike", 0) or 0)

    batch = db.batch()
    batch.delete(ref)
    if date_key:
        summary_ref = (
            db.collection("users").document(str(uid)).collection("daily_summaries").document(date_key)
        )
        batch.set(
            summary_ref,
            {
                "date_key": date_key,
                "updated_at": firestore.SERVER_TIMESTAMP,
                "total_carbs": firestore.Increment(-total_carbs),
                "total_protein": firestore.Increment(-total_protein),
                "total_fat": firestore.Increment(-total_fat),
                "spike_sum": firestore.Increment(-estimated_spike),
                "meal_count": firestore.Increment(-1),
            },
            merge=True,
        )
    try:
        batch.commit()
    except Exception as e:
        sys.stderr.write(f"[delete_meal_record] batch 실패: {e}\n")
        return False, "Firestore"

    for path in _blob_paths_for_meal_image(uid, doc_id, data, bucket_name):
        try:
            blob = bucket.blob(path)
            blob.delete()
        except Exception as e:
            sys.stderr.write(f"[delete_meal_record] Storage 삭제 {path!r}: {type(e).__name__}: {e}\n")
    return True, None


def get_daily_summary(uid, date_key):
    _init_firebase()
    doc = (
        firestore.client()
        .collection("users")
        .document(str(uid))
        .collection("daily_summaries")
        .document(str(date_key))
        .get()
    )
    data = doc.to_dict() if doc.exists else {}
    total_carbs = int((data or {}).get("total_carbs", 0) or 0)
    total_protein = int((data or {}).get("total_protein", 0) or 0)
    total_fat = int((data or {}).get("total_fat", 0) or 0)
    meal_count = int((data or {}).get("meal_count", 0) or 0)
    spike_sum = int((data or {}).get("spike_sum", 0) or 0)
    avg_spike = int(round(spike_sum / meal_count)) if meal_count > 0 else 0
    return {
        "total_carbs": total_carbs,
        "total_protein": total_protein,
        "total_fat": total_fat,
        "meal_count": meal_count,
        "spike_sum": spike_sum,
        "avg_spike": avg_spike,
    }


def get_glucose_records(uid, period="주간"):
    """선택한 기간에 해당하는 혈당 기록을 가져온다. Firestore 필드는 `timestamp`(UTC)."""
    if not uid:
        return []
    try:
        _init_firebase()
        db = firestore.client()
        now = datetime.now(timezone.utc)
        if period == "오늘":
            start_date = now - timedelta(days=1)
        elif period == "주간":
            start_date = now - timedelta(days=7)
        elif period == "월간":
            start_date = now - timedelta(days=30)
        elif period == "연간":
            start_date = now - timedelta(days=365)
        else:
            start_date = now - timedelta(days=7)

        col = db.collection("users").document(str(uid)).collection("glucose")
        q = (
            col.where("timestamp", ">=", start_date)
            .where("timestamp", "<=", now)
            .order_by("timestamp", direction=Query.ASCENDING)
        )
        out = []
        for doc in q.stream():
            data = doc.to_dict() or {}
            ts = data.get("timestamp")
            if ts is None:
                continue
            if hasattr(ts, "timestamp"):
                ts_utc = datetime.fromtimestamp(ts.timestamp(), tz=timezone.utc)
            elif hasattr(ts, "astimezone"):
                ts_utc = ts.astimezone(timezone.utc)
            else:
                continue
            out.append(
                {
                    "type": data.get("type") or "",
                    "value": int(data.get("value") or 0),
                    "recorded_at_utc": ts_utc.isoformat(),
                }
            )
        return out
    except Exception as e:
        sys.stderr.write(f"[get_glucose_records] {e}\n")
        print(f"혈당 기록 로드 실패: {e}")
        return []
