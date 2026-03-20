# -*- coding: utf-8 -*-
"""Firestore/Storage helper functions for meal persistence."""

import io
import json
import os
import urllib.parse
from datetime import datetime, timezone

import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, storage
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
    if not path:
        return ""
    path_encoded = urllib.parse.quote(path, safe="/")
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
    try:
        blob.make_public()
    except Exception:
        pass
    image_url = getattr(blob, "public_url", None) or ""
    if not (image_url and str(image_url).strip().startswith("http")):
        image_url = _normalize_image_url(path, bucket.name)
    return image_url


def save_meal_and_summary(uid, date_key, meal_data):
    _init_firebase()
    db = firestore.client()
    meal_ref = db.collection("users").document(str(uid)).collection("meals").document()
    summary_ref = db.collection("users").document(str(uid)).collection("daily_summaries").document(str(date_key))

    data = dict(meal_data or {})
    data["created_at"] = firestore.SERVER_TIMESTAMP
    data["date_key"] = str(date_key)
    data["meal_id"] = meal_ref.id

    total_carbs = int(data.get("total_carbs", 0) or 0)
    total_protein = int(data.get("total_protein", 0) or 0)
    total_fat = int(data.get("total_fat", 0) or 0)
    estimated_spike = int(data.get("estimated_spike", 0) or 0)

    batch = db.batch()
    batch.set(meal_ref, data, merge=True)
    batch.set(
        summary_ref,
        {
            "date_key": str(date_key),
            "updated_at": firestore.SERVER_TIMESTAMP,
            "total_carbs": firestore.Increment(total_carbs),
            "total_protein": firestore.Increment(total_protein),
            "total_fat": firestore.Increment(total_fat),
            "spike_sum": firestore.Increment(estimated_spike),
            "meal_count": firestore.Increment(1),
        },
        merge=True,
    )
    batch.commit()
    return meal_ref.id


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
